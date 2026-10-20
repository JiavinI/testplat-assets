"""GO2 启用保持原账号配置，且不向 E3E3 暴露 GO2 建单入口。"""

from pathlib import Path

import yaml
from testplat_engine import describe_case

from testplat_control.services.asset_service import AssetService

REPO = Path(__file__).resolve().parents[1]
CASE = "case.go2.order.full_pay.items_create_pending"


def manifest():
    return yaml.safe_load((REPO / "testplat.yaml").read_text())["projects"]


def test_go2_activation_preserves_workspace_and_configuration():
    projects = manifest()
    go2 = projects["gsb"]
    e3e3 = projects["gsb_e3e3"]
    assert len(projects) == 10
    assert go2["assets"] == "projects/gsb_go2"
    assert go2["config"] == "projects/gsb/config"
    assert go2["workspace"]["project"] == "go2"
    assert e3e3["assets"] == "projects/gsb"
    assert e3e3["config"] == "projects/e3e3/config"
    assert not (REPO / go2["assets"] / "config").exists()


def test_go2_activation_retains_existing_contracts_and_smoke():
    original = REPO / "projects/gsb"
    active = REPO / manifest()["gsb"]["assets"]
    original_api = {path.relative_to(original) for path in (original / "api").rglob("*.yaml")}
    assert {path.relative_to(active) for path in (active / "api").rglob("*.yaml")} == original_api
    for relative in original_api | {Path("scenarios/gsb/smoke.case.yaml")}:
        assert (active / relative).read_bytes() == (original / relative).read_bytes()
    candidate = REPO / "examples/go2-pending/scenarios"
    for path in candidate.rglob("*.yaml"):
        assert (
            active / "scenarios" / path.relative_to(candidate)
        ).read_bytes() == path.read_bytes()


def test_go2_case_is_visible_only_in_go2_workspace():
    projects = manifest()
    for key, visible in [("gsb", True), ("gsb_e3e3", False)]:
        workspace = projects[key]
        service = AssetService(
            REPO / workspace["assets"],
            REPO / workspace["config"],
            business_project=workspace["workspace"]["project"],
        )
        service.scan_assets()
        assert (service.get_asset(CASE) is not None) is visible
        assert service.get_asset("case.gsb.smoke") is not None
    assert describe_case(CASE, REPO / projects["gsb"]["assets"])["schema_version"] == "0.3"
