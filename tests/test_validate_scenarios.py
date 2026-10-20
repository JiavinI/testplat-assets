"""Static validation reuses Engine description and never executes business requests."""

import importlib.util
from pathlib import Path

import pytest
import testplat_engine
import yaml

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def validator(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "scenario_validator", REPO / "scripts/validate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def no_execution(*args, **kwargs):
        pytest.fail("static validator must not execute an API or case")

    monkeypatch.setattr(testplat_engine.SingleApiEngine, "execute", no_execution)
    return module


def write(root, relative, document):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, allow_unicode=True))


def documents(root):
    api = {
        "id": "api.demo.echo",
        "type": "api",
        "name": "echo",
        "host": "fake",
        "method": "POST",
        "url": "/echo",
        "request": {},
        "success": {"status_code": 200},
    }
    flow = {
        "schema_version": "0.3",
        "id": "flow.demo.echo",
        "inputs": {"value": {"type": "string"}},
        "outputs": {"value": "${echo.body}"},
        "steps": [{"step_id": "echo", "type": "api", "api_id": api["id"], "output": "echo"}],
    }
    case = {
        "schema_version": "0.3",
        "id": "case.demo.run",
        "params": {"items": [{"value": "one"}]},
        "steps": [
            {
                "step_id": "each",
                "type": "map",
                "flow_id": flow["id"],
                "source": "${params.items}",
                "params": {"value": "${item.value}"},
                "output": "rows",
            },
            {
                "step_id": "values",
                "type": "transform",
                "operation": "project",
                "source": "${rows}",
                "path": ["value"],
                "output": "values",
            },
            {
                "step_id": "first",
                "type": "extract",
                "source": "${values}",
                "selector": {"path": [0]},
                "cardinality": "one",
                "value_type": "string",
                "output": "first",
            },
            {
                "step_id": "amount",
                "type": "decimal",
                "operation": "add",
                "operands": [".1", ".2"],
                "scale": 2,
                "rounding": "HALF_UP",
                "output": "amount",
            },
            {
                "step_id": "check",
                "type": "assert",
                "operation": "decimal_equal",
                "actual": "${amount}",
                "expected": "0.30",
            },
        ],
    }
    write(root, "api/demo/echo.yaml", api)
    write(root, "scenarios/demo/echo.flow.yaml", flow)
    write(root, "scenarios/demo/run.case.yaml", case)
    return case, flow


def test_new_scenarios_and_orphan_flow_pass_without_execution(validator, tmp_path):
    documents(tmp_path)
    assert validator.validate_scenarios(tmp_path) == []
    (tmp_path / "scenarios/demo/run.case.yaml").unlink()
    assert validator.validate_scenarios(tmp_path) == []
    assert not (tmp_path / "scenarios/validator_entry.case.yaml").exists()


@pytest.mark.parametrize("name", ["go2-pending", "scenario-parameters"])
def test_real_candidates_static_and_unchanged(validator, name):
    manifest = (REPO / "testplat.yaml").read_bytes()
    assert validator.validate_candidate(name) == []
    assert (REPO / "testplat.yaml").read_bytes() == manifest


@pytest.mark.parametrize(
    "problem",
    [
        "missing_api",
        "missing_flow",
        "cycle",
        "input",
        "forward",
        "selector",
        "rounding",
        "assert",
        "transform",
        "id",
        "unknown",
    ],
)
def test_invalid_new_scenarios_fail(validator, tmp_path, problem):
    case, flow = documents(tmp_path)
    if problem == "missing_api":
        (tmp_path / "api/demo/echo.yaml").unlink()
    elif problem == "missing_flow":
        case["steps"][0]["flow_id"] = "flow.demo.missing"
    elif problem == "cycle":
        flow["steps"] = [
            {
                "step_id": "self",
                "type": "flow",
                "flow_id": flow["id"],
                "params": {"value": "${inputs.value}"},
            }
        ]
    elif problem == "input":
        case["steps"][0]["params"] = {}
    elif problem == "forward":
        case["steps"][0]["source"] = "${values}"
    elif problem == "selector":
        case["steps"][2]["selector"] = {"path": [-1]}
    elif problem == "rounding":
        case["steps"][3]["rounding"] = "UNKNOWN"
    elif problem == "assert":
        case["steps"][4]["operation"] = "eval"
    elif problem == "transform":
        case["steps"][1]["operation"] = "eval"
    elif problem == "id":
        flow["id"] = "flow.demo.wrong"
    else:
        case["unexpected"] = "field"
    write(tmp_path, "scenarios/demo/run.case.yaml", case)
    write(tmp_path, "scenarios/demo/echo.flow.yaml", flow)
    assert validator.validate_scenarios(tmp_path)


def test_invalid_orphan_and_broken_yaml_do_not_leak_values(validator, tmp_path, capsys):
    documents(tmp_path)
    (tmp_path / "scenarios/demo/run.case.yaml").unlink()
    secret = "synthetic-sensitive-value-734"
    (tmp_path / "scenarios/demo/echo.flow.yaml").write_text("password: " + secret + "\nbroken: [}")
    errors = validator.validate_scenarios(tmp_path)
    assert errors
    assert secret not in capsys.readouterr().out + str(errors)


def test_old_engine_keeps_legacy_and_rejects_new(validator, tmp_path, monkeypatch):
    case, flow = documents(tmp_path)
    monkeypatch.delattr(testplat_engine, "describe_case")
    assert validator.validate_scenarios(tmp_path)
    (tmp_path / "scenarios/demo/echo.flow.yaml").unlink()
    case = {
        "schema_version": "0.2",
        "id": "case.demo.run",
        "steps": [{"step_id": "echo", "type": "api", "api_id": "api.demo.echo"}],
    }
    write(tmp_path, "scenarios/demo/run.case.yaml", case)
    assert validator.validate_scenarios(tmp_path) == []
    (tmp_path / "api/demo/echo.yaml").unlink()
    assert validator.validate_scenarios(tmp_path)


def test_api_only_project_still_allowed(validator, tmp_path, monkeypatch):
    documents(tmp_path)
    for path in (tmp_path / "scenarios").rglob("*.yaml"):
        path.unlink()
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(validator, "REPO_ROOT", tmp_path)
    assert validator.validate_project("demo", {"assets": ".", "config": "config"}) == []


def test_new_engine_still_validates_legacy(validator, tmp_path):
    documents(tmp_path)
    write(
        tmp_path,
        "scenarios/demo/run.case.yaml",
        {
            "schema_version": "0.2",
            "id": "case.demo.run",
            "steps": [{"step_id": "echo", "type": "api", "api_id": "api.demo.echo"}],
        },
    )
    assert validator.validate_scenarios(tmp_path) == []


@pytest.mark.parametrize("target", ["case", "api"])
def test_asset_parse_failures_hide_source(validator, tmp_path, capsys, target):
    documents(tmp_path)
    secret = "synthetic-sensitive-value-129"
    path = tmp_path / ("api/demo/echo.yaml" if target == "api" else "scenarios/demo/run.case.yaml")
    path.write_text("password: " + secret + "\nbroken: [}")
    errors = validator.validate_scenarios(tmp_path)
    assert errors
    assert secret not in capsys.readouterr().out + str(errors)


def test_empty_candidate_fails(validator, tmp_path, monkeypatch):
    (tmp_path / "examples/go2-pending/scenarios").mkdir(parents=True)
    monkeypatch.setattr(validator, "REPO_ROOT", tmp_path)
    with pytest.raises(ValueError, match="缺少 case"):
        validator.validate_candidate("go2-pending")


@pytest.mark.parametrize("candidate", ["go2-pending", "scenario-parameters", None])
def test_cli_success(validator, monkeypatch, candidate):
    import sys

    monkeypatch.setattr(
        sys, "argv", ["validate.py"] + (["--candidate", candidate] if candidate else [])
    )
    assert validator.main() == 0


def test_cli_candidate_failure_exit_code(validator, tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(validator, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["validate.py", "--candidate", "go2-pending"])
    assert validator.main() == 1
