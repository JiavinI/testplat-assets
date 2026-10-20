# GO2 多商品全款待支付场景

本目录保留 TestPlat schema 0.3 示例；同内容已启用至 `projects/gsb_go2/scenarios`，只对 GO2 的 GSB 工作区可见。需使用精确锁定 Engine 0.6.0（bddb200）的配套 Control；无需相邻源码覆盖。E3E3 继续原资产目录，原配置和账号归属保留。

入口：`case.go2.order.full_pay.items_create_pending`。

- case：集中维护 `params.common.order` 和 `params.private.items`，只使用虚构样本。
- create_items_pending.flow：约束全款标记，准备商品，计算服务费和提交金额，创建一次订单，核对后端预结算的订单号、金额、数量；只导出后端权威金额。
- prepare_items.flow：先校验并汇总全部数量，再依序解析商品；投影订单项和快递商品列表，识别地址，唯一选择整单快递、默认快递和服务费，计算一次运费。
- resolve_item.flow：完整货号精确匹配商品，再从同一商品的 skuList 按颜色/尺码唯一匹配；订单项只使用这一商品自己的供应商信息；计算单行金额。

所有 flow 显式绑定输入，不保存调用方业务默认值、不读取根 case 参数。所有 API 步骤使用身份引用 `gsb.b2.primary`；凭据仍通过已有运行身份表提供。商品类型、GOODS、MATCHED_SKU 等协议值保留在映射中，其余可配置选项集中在 case。参数覆盖沿用顶层替换，修改 common/private 时需提供完整对象。

复用的 API 是当前 `projects/gsb/api/gsb/b2` 中的 search_product、user_area_place、intellect_express_items、service_fee、freight、go2.create_items、go2.settle，未修改这些 API 契约；启用目录保留它们及旧 smoke 的副本。运行测试时只将这七个契约与候选 scenarios 复制到临时目录；不复制生产环境配置或任何真实身份数据。

## 安全复现

从 Control 目录运行：

```sh
uv run --isolated --locked --extra dev python ../testplat-assets/scripts/validate.py --candidate go2-pending
uv run --isolated --locked --extra dev pytest -q ../testplat-assets/tests/test_go2_pending.py
```

该入口使用 Control 远程精确锁，不加载相邻 Engine。动态测试对示例和启用目录分别运行相同用例。测试使用 httpx.MockTransport 内存假目标与明显的虚构身份材料，不监听端口、不发网络请求、不启动预览、不读取真实账号。测试中的 pending.invalid 只用于匹配请求，不能作为真实运行环境。

两商品分别来自两供应商，数量 2/3。假目标每次验证实际 wire 请求：两次搜索 + 地址 + 快递 + 服务费 + 运费 + 创建 + 预结算 = 8 次。商品金额 `0.335×2 → 0.67`、`2.675×3 → 8.03`，加整单运费 `2.00` 和服务费 `0.10×5 → 0.50`，提交 `11.20`。后端模拟返回 `11.200`，场景通过 Decimal 相等校验并保留后端原值作为导出金额。

测试覆盖空列表、零/负/非整数数量、商品/SKU/快递/默认快递/费用零或多匹配、缺失收件信息或费用、非法价格、建单业务拒绝、预结算订单号/金额/数量不符和超时。建单前失败不创建订单；建单成功后校验失败不重新创建、不导出本地估算金额；第二商品失败保留第一迭代成功记录，停止后续请求。公开结果不包含假身份秘密。

## 限制与后续

这是 Assets + Engine 的假目标闭环，不代表真实 GO2 已下单、已验证 WAIT_PAY 状态或已完成支付。当前只向创建接口提交全款标记并执行预结算，没有支付动作；真实业务状态需要专门授权和业务验收。建单返回的订单号沿现有响应契约读取 `data[0].orderNo`，商品、SKU、快递和预结算订单使用唯一匹配校验。

场景已通过新版静态验证器与 Control 隔离展示验收。静态检查复用 Engine 公开描述入口，独立检查三个 flow，不执行请求；不能代替动态金额、环境和账号校验。启用顺序为 Engine 提交推送、Control 精确锁及无源码覆盖安装验证、再更新 GO2 清单。交付分支启用不代表主线合并或部署；现有预览和数据库未更新，真实业务验收另行安排。
