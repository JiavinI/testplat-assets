#!/usr/bin/env python3
"""用 Engine 0.5 加载本仓库全部资产，并检查 case 对 api 的引用。

不发 HTTP 请求，也不写入凭据。登录流程在 ``config/auth/_profiles.yaml``：
``${secret:字段名}`` 不得是 ``TESTPLAT_*``。运行时凭据由 Web 维护，
无需 ``config/auth/<env>.yaml``；若旧资产仍有该文件，则继续校验。

若 PYTHONPATH 含 testplat-control，则用 ``load_profile_catalog`` /
``build_auth_from_document`` 校验流程 schema，并用历史 ``load_auth`` 校验可选的
旧环境身份文件。流程构造只用等长占位符满足最小长度，不读取、不写入真实凭据；
字段名路径不得要求 ``TESTPLAT_GSB_*``。

用法::

    PYTHONPATH=../testplat-engine/src:../testplat-control/src \\
      python scripts/validate.py

退出码：0 全部通过；1 有失败。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "testplat.yaml"
PROJECT_KEY_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
# 环境夹层不提供秘密。流程 schema 只用等长占位符，避免缺失字段提前变成 UnavailableAuth
# 而跳过 inject / extract 校验；该字符串不是账号密码，也不写入仓库数据文件。
_EMPTY_SECRETS: dict[str, str] = {}
_SCHEMA_PLACEHOLDER = "x" * 8
_PROFILE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SECRET_FIELD_RE = re.compile(r"\$\{secret:([A-Za-z0-9_]+)\}")
_TESTPLAT_SECRET_RE = re.compile(r"\$\{secret:(TESTPLAT_[A-Za-z0-9_]+)\}")
# 历史 load_auth 允许的根键。兼容夹层只保留空 identities，避免夹带默认身份。
_AUTH_ROOT_KEYS = frozenset({"identities", "default_identity", "connections", "login_plugins"})


def _fail(msg: str) -> None:
    print(f"FAIL  {msg}")


def _yaml_mark_location(exc: BaseException) -> str:
    """取 PyYAML 行列。只读整数坐标，不读 mark 的 buffer 或片段。"""
    mark = getattr(exc, "problem_mark", None)
    line = getattr(mark, "line", None)
    column = getattr(mark, "column", None)
    if isinstance(line, int) and isinstance(column, int) and line >= 0 and column >= 0:
        return f" 位置 {line + 1}:{column + 1}"
    return ""


def _safe_error(label: str, exc: BaseException) -> str:
    """校验失败只留固定说明、异常类型和可选行列。

    禁止拼接 ``str(exc)``。PyYAML 异常原文含文件片段，可能带出凭据。
    """
    return f"{label}: {type(exc).__name__}{_yaml_mark_location(exc)}"


def _ok(msg: str) -> None:
    print(f"OK    {msg}")


def _load_manifest() -> dict:
    path = REPO_ROOT / MANIFEST_NAME
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("testplat.yaml 根节点必须是对象")
    if data.get("schema_version") != "1":
        raise ValueError(f"schema_version 必须为 '1'，实际 {data.get('schema_version')!r}")
    projects = data.get("projects")
    if not isinstance(projects, dict) or not projects:
        raise ValueError("projects 必须是非空对象")
    return data


def _check_rel_path(label: str, rel: object) -> Path:
    """清单路径必须是仓库内相对路径，拒绝绝对路径与 ..。"""
    if not isinstance(rel, str) or not rel.strip():
        raise ValueError(f"{label} 必须是非空相对路径")
    if Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise ValueError(f"{label} 非法路径: {rel}")
    resolved = (REPO_ROOT / rel).resolve()
    if not resolved.is_relative_to(REPO_ROOT.resolve()):
        raise ValueError(f"{label} 逃逸仓库根: {rel}")
    return resolved


def _discover_api_ids(assets_root: Path) -> list[str]:
    api_root = assets_root / "api"
    if not api_root.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(api_root.rglob("*.yaml")):
        if path.name.startswith("_"):
            continue
        rel = path.relative_to(assets_root).with_suffix("")
        ids.append(".".join(rel.parts))
    return ids


def _discover_case_ids(assets_root: Path) -> list[str]:
    scenarios = assets_root / "scenarios"
    if not scenarios.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(scenarios.rglob("*.case.yaml")):
        rel = path.relative_to(scenarios)
        stem = rel.name[: -len(".case.yaml")]
        parts = list(rel.parent.parts) + [stem] if rel.parent != Path(".") else [stem]
        ids.append("case." + ".".join(parts))
    return ids


def _list_envs(config_root: Path) -> list[str]:
    envs_dir = config_root / "envs"
    if not envs_dir.is_dir():
        return []
    return sorted(
        p.stem for p in envs_dir.glob("*.yaml") if p.is_file() and not p.name.startswith("_")
    )


def _looks_like_literal_secret(auth_text: str) -> bool:
    """拦截 password/token 写成字面量（允许 ${secret:}）。"""
    return (
        re.search(
            r"(?im)^\s*(password|token)\s*:\s*(?!\$\{secret:)['\"]?[^$\s'\"#]+",
            auth_text,
        )
        is not None
    )


def _secret_field_names(node: object) -> list[str]:
    """按出现顺序收集 ${secret:字段名}，同一字段只留一次。"""
    found: list[str] = []
    if isinstance(node, str):
        found.extend(_SECRET_FIELD_RE.findall(node))
    elif isinstance(node, dict):
        for value in node.values():
            found.extend(_secret_field_names(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_secret_field_names(value))
    return list(dict.fromkeys(found))


def _source_literals(node: object) -> list[object]:
    """收集 body.fields.source。字面量必须原样保留，不能改成秘密占位符。"""
    found: list[object] = []
    if isinstance(node, dict):
        fields = node.get("fields")
        if isinstance(fields, dict) and "source" in fields:
            found.append(fields["source"])
        for value in node.values():
            found.extend(_source_literals(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_source_literals(value))
    return found


def _check_gsb_profile(body: object, fields: list[str]) -> str | None:
    """4.1a 的 gsb_login 约束：逻辑 host、字段名、source 字面量。"""
    if not isinstance(body, dict):
        return "gsb_login 必须是对象"
    login = body.get("login")
    if not isinstance(login, dict):
        return "gsb_login 缺少 login"
    if login.get("host") != "unified_login":
        return "gsb_login.host 必须是逻辑名 unified_login"
    if fields != ["username", "password"]:
        return f"gsb_login 凭据字段必须是 username、password，实际 {fields}"
    sources = _source_literals(login)
    if sources != ["go2"]:
        return "gsb_login 的 source 必须保持字面量 go2"
    return None


def _schema_check_profiles(config_root: Path, identities: dict) -> list[str]:
    """用平台账号构造入口校验流程。占位符只满足长度，构造结果必须是 LoginAuth。"""
    errors: list[str] = []
    try:
        from testplat_control.services.auth_loader import build_auth_from_document
        from testplat_control.services.login_profiles import load_profile_catalog
    except ImportError:
        _ok("profiles YAML 结构 ok（未装 Control，跳过流程 schema）")
        return errors
    try:
        catalog = load_profile_catalog(config_root)
    except Exception as exc:  # noqa: BLE001 — 汇总后继续，消息不得含异常原文
        message = _safe_error("auth/_profiles.yaml 无法加载", exc)
        errors.append(message)
        _fail(f"profiles catalog: {message}")
        return errors
    catalog_fields = {item.name: list(item.credential_fields) for item in catalog.profiles}
    if catalog_fields != {name: _secret_field_names(body) for name, body in identities.items()}:
        errors.append("load_profile_catalog 提取的凭据字段与文件不一致")
        _fail("profiles 字段提取不一致")
        return errors
    for name, body in identities.items():
        fields = catalog_fields[name]
        secrets = {field: _SCHEMA_PLACEHOLDER for field in fields}
        try:
            result = build_auth_from_document(
                {"identities": {name: body}},
                env="profiles",
                secrets=secrets,
            )
        except Exception as exc:  # noqa: BLE001 — 消息不得含异常原文
            message = _safe_error(f"流程 {name} 无法构造", exc)
            errors.append(message)
            _fail(f"profile {name}: {message}")
            continue
        material = result.table.identities.get(name)
        reason = getattr(material, "public_reason", "")
        kind = type(material).__name__
        # 字段名路径应构造出登录材料。白名单失败会把字段名说成 TESTPLAT_ 环境变量。
        if kind != "LoginAuth" or "TESTPLAT_" in reason:
            errors.append(f"流程 {name} 期望 LoginAuth，实际 {kind}: {reason}")
            _fail(f"profile {name}: {kind} {reason}")
            continue
        _ok(f"profile {name} schema ok（LoginAuth，字段 {fields}）")
    return errors


def _validate_profiles(key: str, config_root: Path) -> list[str]:
    """登录流程文件：无真实凭据，秘密引用必须是字段名。"""
    errors: list[str] = []
    path = config_root / "auth" / "_profiles.yaml"
    if not path.is_file():
        if key == "gsb":
            errors.append("gsb 缺少 config/auth/_profiles.yaml")
            _fail(f"{key} profiles: 缺少 _profiles.yaml")
        else:
            _ok(f"{key} profiles: 无 _profiles.yaml（允许）")
        return errors
    raw_text = path.read_text(encoding="utf-8")
    if _looks_like_literal_secret(raw_text):
        errors.append("auth/_profiles.yaml 疑似含秘密字面量")
        _fail(f"{key} profiles: 疑似秘密字面量")
        return errors
    banned = sorted(set(_TESTPLAT_SECRET_RE.findall(raw_text)))
    if banned:
        errors.append(f"auth/_profiles.yaml 不得引用环境变量 {', '.join(banned)}")
        _fail(f"{key} profiles: 仍引用 {', '.join(banned)}")
        return errors
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        message = _safe_error("auth/_profiles.yaml YAML 无效", exc)
        errors.append(message)
        _fail(f"{key} profiles: {message}")
        return errors
    if not isinstance(data, dict) or not isinstance(data.get("identities"), dict):
        errors.append("auth/_profiles.yaml 缺少 identities 对象")
        _fail(f"{key} profiles: 缺少 identities")
        return errors
    identities: dict = data["identities"]
    if not identities:
        errors.append("auth/_profiles.yaml 没有登录流程")
        _fail(f"{key} profiles: 空 identities")
        return errors
    for name, body in identities.items():
        if not isinstance(name, str) or not _PROFILE_NAME_RE.fullmatch(name) or name == "none":
            errors.append(f"登录流程名非法: {name!r}")
            _fail(f"{key} profile {name}: 流程名非法")
            continue
        fields = _secret_field_names(body)
        if any(field.startswith("TESTPLAT_") for field in fields):
            errors.append(f"流程 {name} 的秘密必须是凭据字段名")
            _fail(f"{key} profile {name}: 字段名仍像环境变量")
            continue
        if key == "gsb" and name == "gsb_login":
            problem = _check_gsb_profile(body, fields)
            if problem:
                errors.append(problem)
                _fail(f"{key} profile {name}: {problem}")
                continue
        _ok(f"{key} profile {name} fields={fields}")
    if key == "gsb" and "gsb_login" not in identities:
        errors.append("gsb 缺少登录流程 gsb_login")
        _fail(f"{key} profiles: 缺少 gsb_login")
    if not errors:
        errors.extend(_schema_check_profiles(config_root, identities))
    return errors


def _validate_env_auth(key: str, config_root: Path, env: str, auth_path: Path) -> list[str]:
    """环境 auth 文件。空 identities 是 Web 凭据兼容夹层，不再要求 TESTPLAT_*。"""
    errors: list[str] = []
    raw_text = auth_path.read_text(encoding="utf-8")
    if _looks_like_literal_secret(raw_text):
        errors.append(f"auth/{env}.yaml 疑似含秘密字面量")
        _fail(f"{key} auth {env}: 疑似秘密字面量")
        return errors
    banned = sorted(set(_TESTPLAT_SECRET_RE.findall(raw_text)))
    if banned:
        errors.append(
            f"auth/{env}.yaml 仍引用 {', '.join(banned)}；平台主路径不再使用这些环境变量"
        )
        _fail(f"{key} auth {env}: 仍引用 {', '.join(banned)}")
        return errors
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        message = _safe_error(f"auth/{env}.yaml YAML 无效", exc)
        errors.append(message)
        _fail(f"{key} auth {env}: {message}")
        return errors
    # 只有空身份表才是本批夹层。注释不足以让历史 load_auth 通过（根节点会变成 None）。
    if data == {"identities": {}}:
        return _check_auth_shim(key, config_root, env)
    if not isinstance(data, dict) or not isinstance(data.get("identities"), dict):
        errors.append(
            f"auth/{env}.yaml 须为 identities 对象；兼容夹层应是空 identities，不能只写注释"
        )
        _fail(f"{key} auth {env}: 不是合法夹层或历史身份表")
        return errors
    unknown = sorted(set(data) - _AUTH_ROOT_KEYS)
    if unknown:
        errors.append(f"auth/{env}.yaml 含未知字段: {', '.join(unknown)}")
        _fail(f"{key} auth {env}: 未知字段 {unknown}")
        return errors
    try:
        from testplat_control.services.auth_loader import load_auth
    except ImportError:
        _ok(f"{key} auth {env} YAML ok（未装 Control，跳过 auth_loader）")
        return errors
    try:
        result = load_auth(config_root, env, environ=_EMPTY_SECRETS)
    except Exception as exc:  # noqa: BLE001 — 消息不得含异常原文
        message = _safe_error(f"auth {env} 无法加载", exc)
        errors.append(message)
        _fail(f"{key} auth {env}: {message}")
        return errors
    if result is None:
        errors.append(f"auth/{env}.yaml 存在但 load_auth 返回 None")
        _fail(f"{key} auth {env}: load_auth None")
        return errors
    names = sorted(result.table.identities)
    _ok(f"{key} auth {env} identities={names} default={result.table.default_identity}")
    return errors


def _check_auth_shim(key: str, config_root: Path, env: str) -> list[str]:
    """空身份表必须能被历史 load_auth 接受，且不带出任何身份。"""
    errors: list[str] = []
    try:
        from testplat_control.services.auth_loader import load_auth
    except ImportError:
        _ok(f"{key} auth {env}: 兼容夹层（未装 Control，跳过 load_auth）")
        return errors
    try:
        result = load_auth(config_root, env, environ=_EMPTY_SECRETS)
    except Exception as exc:  # noqa: BLE001 — 消息不得含异常原文
        message = _safe_error(f"auth {env} 兼容夹层无法加载", exc)
        errors.append(message)
        _fail(f"{key} auth {env}: {message}")
        return errors
    if result is None:
        errors.append(f"auth/{env}.yaml 兼容夹层被 load_auth 当成缺失文件")
        _fail(f"{key} auth {env}: load_auth None")
        return errors
    names = sorted(result.table.identities)
    if names or result.table.default_identity is not None:
        errors.append(f"auth/{env}.yaml 兼容夹层不应声明身份，实际 {names}")
        _fail(f"{key} auth {env}: 夹层含身份 {names}")
        return errors
    _ok(f"{key} auth {env}: 兼容夹层（空身份表，运行时凭据由 Web 维护）")
    return errors


def validate_project(key: str, meta: dict) -> list[str]:
    from testplat_engine.adapters.filesystem.registry import Registry

    errors: list[str] = []
    if not PROJECT_KEY_RE.fullmatch(key):
        return [f"项目键非法: {key}"]

    try:
        assets_root = _check_rel_path(f"projects.{key}.assets", meta.get("assets"))
        config_root = _check_rel_path(f"projects.{key}.config", meta.get("config"))
    except ValueError as exc:
        return [str(exc)]

    if not assets_root.is_dir():
        return [f"assets 目录不存在: {assets_root}"]
    if not config_root.is_dir():
        return [f"config 目录不存在: {config_root}"]

    registry = Registry(assets_root)
    api_ids = _discover_api_ids(assets_root)
    case_ids = _discover_case_ids(assets_root)
    loaded_apis: set[str] = set()

    if not api_ids:
        errors.append(f"项目 {key} 无 api 资产")
    for api_id in api_ids:
        try:
            api = registry.load_api(api_id)
            loaded_apis.add(api.id)
            _ok(f"{key} api {api.id} ({api.method} {api.url})")
        except Exception as exc:  # noqa: BLE001 — 汇总全部加载错误
            errors.append(f"加载 api {api_id}: {type(exc).__name__}: {exc}")
            _fail(f"{key} api {api_id}: {exc}")

    if not case_ids:
        errors.append(f"项目 {key} 无 case 资产")
    for case_id in case_ids:
        try:
            case = registry.load_case(case_id)
            _ok(f"{key} case {case.id} ({len(case.steps)} steps)")
            for step in case.steps:
                if step.type != "api":
                    errors.append(f"case {case_id} step {step.step_id} 不支持的 type={step.type}")
                    _fail(f"{key} case {case_id} step {step.step_id}: type={step.type}")
                    continue
                if step.api_id not in loaded_apis:
                    try:
                        registry.load_api(step.api_id)
                        loaded_apis.add(step.api_id)
                    except Exception as exc:  # noqa: BLE001
                        msg = f"case {case_id} 引用缺失 api {step.api_id}: {exc}"
                        errors.append(msg)
                        _fail(msg)
                        continue
                _ok(f"  {case_id} step {step.step_id} → {step.api_id}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"加载 case {case_id}: {type(exc).__name__}: {exc}")
            _fail(f"{key} case {case_id}: {exc}")

    errors.extend(_validate_profiles(key, config_root))

    envs = _list_envs(config_root)
    default_env = meta.get("default_env")
    if default_env is not None and default_env not in envs:
        errors.append(f"default_env={default_env!r} 不在 envs {envs}")

    for env in envs:
        env_path = config_root / "envs" / f"{env}.yaml"
        try:
            env_data = yaml.safe_load(env_path.read_text(encoding="utf-8"))
            if not isinstance(env_data, dict) or not isinstance(env_data.get("api_hosts"), dict):
                raise ValueError("缺少 api_hosts 对象")
            hosts = env_data["api_hosts"]
            for hname, hurl in hosts.items():
                if not isinstance(hurl, str) or not (
                    hurl.startswith("http://") or hurl.startswith("https://")
                ):
                    raise ValueError(f"api_hosts.{hname} 须为 http(s) URL")
            _ok(f"{key} env {env} hosts={sorted(hosts)}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"env {env}: {exc}")
            _fail(f"{key} env {env}: {exc}")

        auth_path = config_root / "auth" / f"{env}.yaml"
        if not auth_path.is_file():
            _ok(f"{key} auth {env}: 文件不存在（允许；凭据由 Web 维护）")
            continue
        errors.extend(_validate_env_auth(key, config_root, env, auth_path))

    return errors


def main() -> int:
    print(f"REPO_ROOT={REPO_ROOT}")
    try:
        import testplat_engine

        print(f"Engine import ok: {getattr(testplat_engine, '__file__', '?')}")
    except ImportError as exc:
        print(f"无法 import testplat_engine: {exc}", file=sys.stderr)
        print(
            "请将 Engine 0.5 的 src 加入 PYTHONPATH，例如:\n"
            "  PYTHONPATH=../testplat-engine/src:../testplat-control/src "
            "python scripts/validate.py",
            file=sys.stderr,
        )
        return 1

    try:
        manifest = _load_manifest()
        _ok(f"manifest projects={list(manifest['projects'])}")
    except Exception as exc:  # noqa: BLE001
        _fail(f"manifest: {exc}")
        return 1

    all_errors: list[str] = []
    for key, meta in manifest["projects"].items():
        if not isinstance(meta, dict):
            all_errors.append(f"projects.{key} 必须是对象")
            continue
        print(f"--- project {key} ---")
        all_errors.extend(validate_project(key, meta))

    print("--- summary ---")
    if all_errors:
        print(f"FAILED ({len(all_errors)}):")
        for item in all_errors:
            print(f"  - {item}")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
