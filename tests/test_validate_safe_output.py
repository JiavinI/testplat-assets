#!/usr/bin/env python3
"""回归：格式错误的登录 YAML 不得把片段打进 validate 的 stdout/stderr。

合成值只出现在本测试和临时文件中，不写入资产。运行前需能 import Engine 0.5。
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# 审查复现用的合成值，不是账号密码。
SECRET = "Example123"
REPO = Path(__file__).resolve().parents[1]
BROKEN_BODY = "body: {password: " + SECRET + ", x: [}\n"

BROKEN_PROFILE = (
    "identities:\n"
    "  gsb_login:\n"
    "    login:\n"
    "      host: unified_login\n"
    "      steps:\n"
    "        - name: login\n"
    "          method: GET\n"
    "          path: /site/login\n"
    "          " + BROKEN_BODY
)


def _load_validate():
    path = REPO / "scripts" / "validate.py"
    spec = importlib.util.spec_from_file_location("assets_validate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 scripts/validate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_repo(dest: Path) -> None:
    shutil.copytree(
        REPO,
        dest,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
    )


def _run_validate(root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "validate.py")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_hidden(proc: subprocess.CompletedProcess[str], label: str) -> None:
    combined = proc.stdout + proc.stderr
    if "无法 import testplat_engine" in combined:
        raise SystemExit(f"FAIL {label}: 未导入 Engine，没有跑到 YAML 解析")
    if proc.returncode == 0:
        raise SystemExit(f"FAIL {label}: 格式错误的 YAML 不应通过")
    if SECRET in combined:
        raise SystemExit(f"FAIL {label}: 校验输出含合成敏感值")
    if "ParserError" not in combined or "YAML 无效" not in combined:
        raise SystemExit(f"FAIL {label}: 输出缺少安全格式中的异常类型")
    if "位置 " not in combined:
        raise SystemExit(f"FAIL {label}: 输出缺少行列位置")


def test_broken_profile_hides_secret() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "assets"
        _copy_repo(root)
        profile = root / "projects" / "gsb" / "config" / "auth" / "_profiles.yaml"
        profile.write_text(BROKEN_PROFILE, encoding="utf-8")
        _assert_hidden(_run_validate(root), "profiles")


def test_broken_env_auth_hides_secret() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "assets"
        _copy_repo(root)
        auth = root / "projects" / "gsb" / "config" / "auth" / "test.yaml"
        auth.write_text(BROKEN_PROFILE, encoding="utf-8")
        _assert_hidden(_run_validate(root), "env auth")


def test_constructor_errors_hide_secret() -> None:
    """构造入口抛出带合成值的异常时，stdout 只保留类型名。"""
    validate = _load_validate()
    import testplat_control.services.auth_loader as auth_loader
    import testplat_control.services.login_profiles as login_profiles

    class _Item:
        name = "gsb_login"
        credential_fields = ("username",)

    class _Catalog:
        profiles = (_Item(),)

    def _catalog(_config_root: Path):
        return _Catalog()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(SECRET)

    old_catalog = login_profiles.load_profile_catalog
    old_build = auth_loader.build_auth_from_document
    old_load = auth_loader.load_auth
    login_profiles.load_profile_catalog = _catalog
    auth_loader.build_auth_from_document = _boom
    auth_loader.load_auth = _boom
    try:
        identities = {
            "gsb_login": {
                "login": {"steps": [{"body": {"fields": {"username": "${secret:username}"}}}]}
            }
        }
        from io import StringIO
        from contextlib import redirect_stderr, redirect_stdout

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            profile_errors = validate._schema_check_profiles(Path("."), identities)
            with tempfile.TemporaryDirectory() as tmp:
                config = Path(tmp)
                auth_dir = config / "auth"
                auth_dir.mkdir()
                historic = auth_dir / "test.yaml"
                historic.write_text("identities:\n  gsb: {}\n", encoding="utf-8")
                auth_errors = validate._validate_env_auth("gsb", config, "test", historic)
                shim = auth_dir / "test.yaml"
                shim.write_text("identities: {}\n", encoding="utf-8")
                shim_errors = validate._check_auth_shim("gsb", config, "test")
        combined = stdout.getvalue() + stderr.getvalue()
        listed = "\n".join(profile_errors + auth_errors + shim_errors)
        blob = combined + "\n" + listed
        if SECRET in blob:
            raise SystemExit("FAIL 构造异常输出含合成敏感值")
        if "RuntimeError" not in blob:
            raise SystemExit("FAIL 构造异常输出缺少异常类型")
    finally:
        login_profiles.load_profile_catalog = old_catalog
        auth_loader.build_auth_from_document = old_build
        auth_loader.load_auth = old_load


def main() -> int:
    test_broken_profile_hides_secret()
    test_broken_env_auth_hides_secret()
    test_constructor_errors_hide_secret()
    safe = _load_validate()._safe_error("标记", RuntimeError(SECRET))
    if SECRET in safe or "RuntimeError" not in safe:
        raise SystemExit("FAIL _safe_error 未去掉异常原文")
    print("OK    格式错误输出不含合成敏感值")
    return 0


if __name__ == "__main__":
    sys.exit(main())
