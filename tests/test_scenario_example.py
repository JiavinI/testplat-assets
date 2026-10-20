"""隔离示例走公开 Engine 入口；MockTransport 保证零外部网络。"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import testplat_engine
from testplat_engine import CaseExecutionRequest, SingleApiEngine
from testplat_engine.plugins.httpx_client import HttpxClient

ROOT = Path(__file__).resolve().parents[1] / "examples/scenario-parameters"


@pytest.mark.skipif(
    not hasattr(testplat_engine, "describe_case"), reason="需本地候选 Engine 场景 0.3"
)
def test_repeat_flow_example_isolated_and_typed():
    calls = []

    def handler(request):
        assert request.url.host == "scenario.invalid"
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json=body)

    engine = SingleApiEngine(
        client_factory=lambda: HttpxClient(transport=httpx.MockTransport(handler))
    )
    description = testplat_engine.describe_case("case.demo.repeat", ROOT)
    assert description["params"]["private"]["second"]["quantity"] == 2
    result = asyncio.run(
        engine.execute(
            CaseExecutionRequest(
                "case.demo.repeat",
                ROOT,
                {"api_hosts": {"scenario_fake": "http://scenario.invalid"}},
                params={},
            )
        )
    ).to_dict()
    assert result["status"] == "success"
    assert len(calls) == 3
    assert calls[0] == {"value": {"enabled": True, "item": {"quantity": 1}}}
    assert calls[1] == {"value": {"enabled": True, "item": {"quantity": 2}}}
    assert calls[2]["value"] == {"first": calls[0]["value"], "second": calls[1]["value"]}
    assert result["steps"][2]["trace"]["bindings"][0]["source_node_id"] == "node-1"
