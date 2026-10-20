"""真实七个 API 契约 + 候选及已启用场景，MockTransport 禁止外部网络。"""

import asyncio
import copy
import json
import shutil
from pathlib import Path

import httpx
import pytest
from testplat_engine import (
    AuthTable,
    CaseExecutionRequest,
    EngineTimeoutError,
    InvalidInputError,
    SecretStr,
    SingleApiEngine,
    StaticHeaderAuth,
    describe_case,
)
from testplat_engine.plugins.httpx_client import HttpxClient

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = REPO / "examples/go2-pending"
CASE = "case.go2.order.full_pay.items_create_pending"
FAKE_AUTH = "fake-pending-auth-for-memory-tests"
API_SUFFIXES = [
    "order/search_product",
    "area/user_area_place",
    "order/intellect_express_items",
    "order/service_fee",
    "order/freight",
    "order/go2/create_items",
    "order/go2/settle",
]


@pytest.fixture(params=["candidate", "active"])
def assets(tmp_path, request):
    source = CANDIDATE if request.param == "candidate" else REPO / "projects/gsb_go2"
    api_root = REPO / "projects/gsb" if request.param == "candidate" else source
    shutil.copytree(source / "scenarios", tmp_path / "scenarios")
    # Reuse current API wire contracts verbatim; never read env/config/old YAML.
    for suffix in API_SUFFIXES:
        relative = Path("api/gsb/b2") / (suffix + ".yaml")
        dest = tmp_path / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(api_root / relative, dest)
    return tmp_path


def product(number, price, supplier):
    return {
        "productId": "id-" + number,
        "productNumber": number,
        "productType": "NORMAL",
        "supplierId": supplier,
        "supplierName": supplier + "-name",
        "supplierPhone": "mock-phone",
        "supplierAddress": supplier + "-address",
        "productionState": "AVAILABLE",
        "categoryId": "category-mock",
        "imageUrl": "https://images.invalid/mock.png",
        "skuList": [
            {
                "color": "红" if number == "MOCK-A" else "蓝",
                "size": "M" if number == "MOCK-A" else "L",
                "skuId": "sku-" + number,
                "price": price,
            }
        ],
    }


class FakeOrderService:
    def __init__(self, problem=None):
        self.problem = problem
        self.calls = []
        self.created = []
        self.products = {
            "MOCK-A": product("MOCK-A", "0.335", "supplier-a"),
            "MOCK-B": product("MOCK-B", "2.675", "supplier-b"),
        }

    def handler(self, request):
        assert request.url.host == "pending.invalid"
        assert request.headers["Authorization"] == FAKE_AUTH
        body = json.loads(request.content) if request.content else dict(request.url.params)
        path = request.url.path
        self.calls.append((path, body))
        if path.endswith("/search/product"):
            row = copy.deepcopy(self.products[body["keywords"]])
            data = [row]
            if self.problem == "no_product":
                data = []
            if self.problem == "duplicate_product":
                data *= 2
            if self.problem == "no_sku" or (
                self.problem == "no_second_sku" and body["keywords"] == "MOCK-B"
            ):
                row["skuList"] = []
            if self.problem == "duplicate_sku":
                row["skuList"] *= 2
            if self.problem == "bad_price":
                row["skuList"][0]["price"] = "NaN"
        elif path.endswith("/userAreaPlace"):
            data = {
                "province": "mock-province",
                "provinceId": "p",
                "city": "mock-city",
                "cityId": "c",
                "county": "mock-county",
                "countyId": "d",
                "name": "虚构收件人",
                "mobile": "mock-mobile",
                "address": "虚构地址",
            }
            if self.problem == "missing_receiver":
                del data["name"]
        elif path.endswith("/intellect/express"):
            assert [item["productId"] for item in body["productInfos"]] == [
                "id-MOCK-A",
                "id-MOCK-B",
            ]
            assert [item["quantity"] for item in body["productInfos"]] == [2, 3]
            data = [
                {
                    "code": "DEFAULT_OTHER",
                    "defaultState": 1,
                    "id": "default-id",
                    "name": "other",
                    "firstScaleAmount": "999",
                    "intellectExpressId": "other-intellect",
                    "strategyId": "other-strategy",
                    "costFirstTag": False,
                },
                {
                    "code": "MOCK_EXPRESS",
                    "defaultState": 0,
                    "id": "selected-id",
                    "name": "selected",
                    "firstScaleAmount": "0.00",
                    "intellectExpressId": "selected-intellect",
                    "strategyId": "selected-strategy",
                    "costFirstTag": True,
                },
            ]
            if self.problem == "no_express":
                data = data[:1]
            if self.problem == "duplicate_express":
                data.append(copy.deepcopy(data[1]))
            if self.problem == "duplicate_default":
                data[1]["defaultState"] = 1
        elif path.endswith("/serviceFee"):
            data = [
                {"type": "OTHER", "price": "888.00"},
                {"type": "PLATFORM_DELIVER_FEE", "price": "0.10"},
            ]
            if self.problem == "no_fee":
                data = []
            if self.problem == "duplicate_fee":
                data.append(copy.deepcopy(data[1]))
            if self.problem == "missing_fee_price":
                del data[1]["price"]
        elif path.endswith("/freight"):
            assert body == {
                "expressId": "selected-id",
                "productCount": 5,
                "receiverProvince": "mock-province",
            }
            assert type(body["productCount"]) is int
            data = {"freightFee": "2.00"}
            if self.problem == "missing_freight":
                data = {}
        elif path.endswith("/create"):
            if self.problem == "create_rejected":
                return httpx.Response(200, json={"errorCode": "FAIL", "data": []})
            self.created.append(body)
            order = body["orderCreateParameters"][0]
            assert order["goodsPayLaterFlag"] == "0"
            assert order["webOrderAmount"] == "11.20"  # 0.67 + 8.03 + 2.00 + 0.50
            assert order["freightFee"] == "2.00"
            assert order["defaultExpressId"] == "default-id"
            assert order["expressId"] == "selected-id"
            assert order["strategyId"] == "selected-strategy"
            assert order["intellectExpressId"] == "selected-intellect"
            assert order["firstScaleAmount"] == "0.00"
            assert len(order["expressList"]) == 2
            assert [item["supplierId"] for item in order["orderItems"]] == [
                "supplier-a",
                "supplier-b",
            ]
            assert [item["supplierAddress"] for item in order["orderItems"]] == [
                "supplier-a-address",
                "supplier-b-address",
            ]
            assert [item["quantity"] for item in order["orderItems"]] == [2, 3]
            assert [item["productNumber"] for item in order["orderItems"]] == [
                "MOCK-A",
                "MOCK-B",
            ]
            data = [{"orderNo": "MOCK-PENDING-1"}]
        elif path.endswith("/settle"):
            assert body == {"orderNos": ["MOCK-PENDING-1"]}
            if self.problem == "settle_timeout":
                raise httpx.ReadTimeout("fake timeout", request=request)
            data = {
                "totalAmount": "11.200",
                "orders": [{"orderNo": "MOCK-PENDING-1", "itemQuantity": 5}],
            }
            if self.problem == "wrong_amount":
                data["totalAmount"] = "11.21"
            if self.problem == "wrong_quantity":
                data["orders"][0]["itemQuantity"] = 4
            if self.problem == "wrong_order":
                data["orders"][0]["orderNo"] = "different"
            if self.problem == "duplicate_settled_order":
                data["orders"] *= 2
        else:
            raise AssertionError("Unexpected mock route")
        return httpx.Response(200, json={"errorCode": "0", "data": data})


def run(root, target, params=None):
    engine = SingleApiEngine(
        client_factory=lambda: HttpxClient(transport=httpx.MockTransport(target.handler))
    )
    return asyncio.run(
        engine.execute(
            CaseExecutionRequest(
                CASE,
                root,
                {
                    "api_hosts": {"gsb": "http://pending.invalid"},
                    "business_project": "go2",
                },
                params=params or {},
                auth=AuthTable(
                    identities={
                        "gsb.b2.primary": StaticHeaderAuth(
                            headers={"Authorization": SecretStr(FAKE_AUTH)},
                            secret_values=(SecretStr(FAKE_AUTH),),
                        )
                    }
                ),
            )
        )
    ).to_dict()


def walk(steps):
    for step in steps:
        yield step
        if step.get("trace"):
            yield from walk(step["trace"]["children"])


def test_pending_two_suppliers_uses_real_wire_contracts_and_backend_amount(assets):
    target = FakeOrderService()
    description = describe_case(CASE, assets)
    assert len(description["params"]["private"]["items"]) == 2
    assert target.calls == []
    result = run(assets, target)
    assert result["status"] == "success", json.dumps(result, ensure_ascii=False)
    assert len(target.calls) == 8
    assert len(target.created) == 1
    assert [p for p, _ in target.calls] == [
        "/api/b2/orders/search/product",
        "/api/b2/orders/search/product",
        "/api/b2/area/userAreaPlace",
        "/api/b2/orders/intellect/express",
        "/api/b2/orders/serviceFee",
        "/api/b2/orders/freight",
        "/api/b2/orders/create",
        "/api/b2/orders/settle",
    ]
    output = result["steps"][0]["trace"]["outputs"]
    assert output == {
        "order": {"order_no": "MOCK-PENDING-1", "amount": "11.200", "item_quantity": 5},
        "web_order_amount": "11.200",
    }
    assert FAKE_AUTH not in json.dumps(result)
    map_step = next(step for step in walk(result["steps"]) if step["type"] == "map")
    assert [s["trace"]["iteration_index"] for s in map_step["trace"]["children"]] == [
        0,
        1,
    ]
    failed = [s for s in walk(result["steps"]) if s["status"] != "success"]
    assert failed == []


@pytest.mark.parametrize("quantity", [0, -1, "2", 1.5, True, None])
def test_invalid_item_quantity_rejects_before_all_requests(assets, quantity):
    target = FakeOrderService()
    items = copy.deepcopy(describe_case(CASE, assets)["params"]["private"]["items"])
    items[1]["quantity"] = quantity
    with pytest.raises(InvalidInputError):
        run(assets, target, {"private": {"items": items}})
    assert target.calls == []


def test_empty_items_zero_requests(assets):
    target = FakeOrderService()
    with pytest.raises(InvalidInputError):
        run(assets, target, {"private": {"items": []}})
    assert target.calls == []


@pytest.mark.parametrize(
    "problem",
    [
        "no_product",
        "duplicate_product",
        "no_sku",
        "no_second_sku",
        "duplicate_sku",
        "bad_price",
        "missing_receiver",
        "no_express",
        "duplicate_express",
        "duplicate_default",
        "no_fee",
        "duplicate_fee",
        "missing_fee_price",
        "missing_freight",
        "create_rejected",
    ],
)
def test_failures_before_creation_do_not_create(assets, problem):
    target = FakeOrderService(problem)
    result = run(assets, target)
    assert result["status"] == "failed"
    assert target.created == []
    assert all(not path.endswith("/settle") for path, _ in target.calls)
    assert result["steps"][0]["trace"]["outputs"] == {}
    failed = [s for s in walk(result["steps"]) if s["status"] == "failed"]
    assert failed
    assert failed[-1]["error"]["kind"] in (
        "variable_resolution",
        "assertion_failed",
        "assertion",
    )


@pytest.mark.parametrize(
    "problem",
    [
        "wrong_amount",
        "wrong_quantity",
        "wrong_order",
        "duplicate_settled_order",
        "settle_timeout",
    ],
)
def test_settlement_failure_never_repeats_create_or_exports_estimate(assets, problem):
    target = FakeOrderService(problem)
    if problem == "settle_timeout":
        with pytest.raises(EngineTimeoutError) as caught:
            run(assets, target)
        result = caught.value.partial_outcome.to_dict()
    else:
        result = run(assets, target)
    assert result["status"] == "failed"
    assert len(target.created) == 1
    assert len(target.calls) == 8
    assert result["steps"][0]["trace"]["outputs"] == {}
    assert [s["status"] for s in result["steps"][1:]] == ["skipped", "skipped"]
    assert FAKE_AUTH not in json.dumps(result)


def test_full_payment_contract_rejects_pay_later_before_requests(assets):
    target = FakeOrderService()
    common = copy.deepcopy(describe_case(CASE, assets)["params"]["common"])
    common["order"]["goods_pay_later_flag"] = "1"
    result = run(assets, target, {"common": common})
    assert result["status"] == "failed"
    assert target.calls == []
    failed = [s for s in walk(result["steps"]) if s["status"] == "failed"]
    assert failed[-1]["step_id"] == "full_payment_only"
    assert failed[-1]["error"]["kind"] == "assertion_failed"


def test_second_item_failure_retains_first_iteration_and_nested_failure(assets):
    target = FakeOrderService("no_second_sku")
    result = run(assets, target)
    mapped = next(s for s in walk(result["steps"]) if s["type"] == "map")
    first, second = mapped["trace"]["children"]
    assert [first["status"], second["status"]] == ["success", "failed"]
    assert [path for path, _ in target.calls] == ["/api/b2/orders/search/product"] * 2
    assert first["trace"]["outputs"]["order_item"]["supplierId"] == "supplier-a"
    assert second["trace"]["outputs"] == {}
    sku = next(s for s in second["trace"]["children"] if s["step_id"] == "sku")
    assert sku["trace"]["extracts"][0]["match_count"] == 0
    assert sku["trace"]["parent_id"] == second["trace"]["node_id"]
