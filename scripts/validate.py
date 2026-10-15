#!/usr/bin/env python3
"""用 Engine 0.5 加载本仓库全部资产，并检查 case 对 api 的引用。

不发 HTTP 请求。若 PYTHONPATH 含 testplat-control，则用 auth_loader 校验
鉴权 YAML schema（注入占位秘密，仅用于结构检查，值不入库）。

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
# auth_loader 结构校验时不注入任何秘密值（缺失 → UnavailableAuth，schema 仍通过）。
_EMPTY_SECRETS: dict[str, str] = {}


def _fail(msg: str) -> None:
    print(f"FAIL  {msg}")


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
            _ok(f"{key} auth {env}: 文件不存在（允许）")
            continue
        raw_text = auth_path.read_text(encoding="utf-8")
        if _looks_like_literal_secret(raw_text):
            errors.append(f"auth/{env}.yaml 疑似含秘密字面量")
            _fail(f"{key} auth {env}: 疑似秘密字面量")
            continue
        try:
            from testplat_control.services.auth_loader import load_auth

            result = load_auth(config_root, env, environ=_EMPTY_SECRETS)
            if result is None:
                errors.append(f"auth/{env}.yaml 存在但 load_auth 返回 None")
                _fail(f"{key} auth {env}: load_auth None")
            else:
                names = sorted(result.table.identities)
                _ok(
                    f"{key} auth {env} identities={names} "
                    f"default={result.table.default_identity}"
                )
        except ImportError:
            data = yaml.safe_load(raw_text)
            if not isinstance(data, dict) or "identities" not in data:
                errors.append(f"auth/{env}.yaml 缺少 identities")
                _fail(f"{key} auth {env}: 缺少 identities")
            else:
                _ok(f"{key} auth {env} YAML ok（未装 Control，跳过 auth_loader）")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"auth {env}: {type(exc).__name__}: {exc}")
            _fail(f"{key} auth {env}: {exc}")

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
