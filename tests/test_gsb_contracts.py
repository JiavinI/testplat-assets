"""迁入 GSB 契约的领域约束：项目范围、必填声明和旧 ID 兼容。"""

import re
from pathlib import Path

import yaml
from testplat_engine.adapters.filesystem.registry import Registry

ROOT = Path(__file__).resolve().parents[1] / "projects/gsb"


def test_all_migrated_contracts_load_without_account_binding():
    files = sorted((ROOT / "api/gsb/b1").rglob("*.yaml"))
    files += sorted((ROOT / "api/gsb/b2").rglob("*.yaml"))
    assert len(files) == 24
    registry = Registry(ROOT)
    for path in files:
        document = yaml.safe_load(path.read_text())
        api = registry.load_api(document["id"])
        assert api.auth is None
        assert api.request["template"] == "structured"
        assert "params" not in api.request
        expected = [part for part in path.relative_to(ROOT).parts if part in ("go2", "e3e3")]
        assert list(api.projects) == expected
        assert not path.name.endswith(".checks.yaml")


def test_required_placeholders_have_required_input_declarations():
    occurrences = 0
    for path in (ROOT / "api/gsb/b2").rglob("*.yaml"):
        document = yaml.safe_load(path.read_text())
        for expr in re.findall(r"\$\{([^}]+)!\}", path.read_text()):
            root = expr.split(".")[0]
            assert document["request"]["inputs"][root]["required"] is True
            occurrences += 1
    assert occurrences > 80


def test_compatibility_ids_use_the_same_contract():
    for old, canonical in (("account/balance.yaml", "b2/account/balance.yaml"),
                           ("order/search_product.yaml", "b2/order/search_product.yaml")):
        legacy = yaml.safe_load((ROOT / "api/gsb" / old).read_text())
        new = yaml.safe_load((ROOT / "api/gsb" / canonical).read_text())
        legacy.pop("id")
        new.pop("id")
        assert legacy == new
