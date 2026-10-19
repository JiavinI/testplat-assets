# GSB API 迁移清单

源：testplat-new/assets/api/gsb。24 个 API + 1 份 checks，保留目录领域层级。API 不绑定账号；调试时选择 identity，场景步骤声明 identity。

公共 API 在 GO2/E3E3 复用；专属目录显式声明 projects。业务项目由 Control 运行上下文传给 Engine，不由账号名推断。GSB token 登录请求 source 为 go2/e3e3，业务注入 X-TOKEN、X-USER-ID；CSRF 独立流程注入 X-CSRF-Token、X-USER-ID、X-SOURCE（GO2_WEB/E3E3_WEB），不把这些值写进 API。

request.template: structured 保留 !、默认值、点分路径、now()/date_add_days()。inputs.required 标记顶层必填，嵌套必填叶路径由 Engine 发送前检查；完整请求内容模式绕过模板 body。缺失的可选字段省略，显式 null 保留，false/0 不视为缺失；默认值保持源 DSL 字符串类型。

| 源相对路径 | 目标 API ID | 项目 | 必填顶层参数 |
| --- | --- | --- | --- |
| b1/withdraw/apply.yaml | api.gsb.b1.withdraw.apply | GO2 / E3E3 | bank_card_no, withdraw_amount |
| b2/account/balance.yaml | api.gsb.b2.account.balance | GO2 / E3E3 | 无 |
| b2/aftersale/orders/create.yaml | api.gsb.b2.aftersale.orders.create | GO2 / E3E3 | apply_reason, items, order_no, business_after_sale_type, return_goods_type |
| b2/aftersale/orders/return_service_fee_product_info.yaml | api.gsb.b2.aftersale.orders.return_service_fee_product_info | GO2 / E3E3 | items |
| b2/area/user_area_place.yaml | api.gsb.b2.area.user_area_place | GO2 / E3E3 | receiver_text |
| b2/fund/transfer/list.yaml | api.gsb.b2.fund.transfer.list | GO2 / E3E3 | page_no, page_size, search_field, search_terms |
| b2/fund/transfer/settle.yaml | api.gsb.b2.fund.transfer.settle | GO2 / E3E3 | ids |
| b2/order/e3e3/coupons.yaml | api.gsb.b2.order.e3e3.coupons | e3e3 | product, quantity |
| b2/order/e3e3/coupons_items.yaml | api.gsb.b2.order.e3e3.coupons_items | e3e3 | items |
| b2/order/e3e3/create.yaml | api.gsb.b2.order.e3e3.create | e3e3 | product, express, service_fee_total_origin, service_fee_total, quantity, freight_fee, web_order_amount, shipping |
| b2/order/e3e3/create_items.yaml | api.gsb.b2.order.e3e3.create_items | e3e3 | order_items, express, service_fee_total_origin, service_fee_total, total_quantity, freight_fee, web_order_amount, supplier_id, send_type, send_time |
| b2/order/e3e3/create_items_with_coupon.yaml | api.gsb.b2.order.e3e3.create_items_with_coupon | e3e3 | order_items, express, service_fee_total_origin, service_fee_total, total_quantity, freight_fee, discounted_web_order_amount, coupon, supplier_id, send_type, send_time |
| b2/order/e3e3/create_with_coupon.yaml | api.gsb.b2.order.e3e3.create_with_coupon | e3e3 | product, express, service_fee_total_origin, service_fee_total, quantity, freight_fee, coupon, discounted_web_order_amount, shipping |
| b2/order/freight.yaml | api.gsb.b2.order.freight | GO2 / E3E3 | express_id, quantity, receiver_province |
| b2/order/go2/create.yaml | api.gsb.b2.order.go2.create | go2 | quantity, freight_fee, web_order_amount |
| b2/order/go2/create_items.yaml | api.gsb.b2.order.go2.create_items | go2 | order_items, freight_fee, web_order_amount |
| b2/order/go2/settle.yaml | api.gsb.b2.order.go2.settle | go2 | order_nos |
| b2/order/intellect_express.yaml | api.gsb.b2.order.intellect_express | GO2 / E3E3 | sku_color, sku_size, quantity |
| b2/order/intellect_express_items.yaml | api.gsb.b2.order.intellect_express_items | GO2 / E3E3 | product_infos |
| b2/order/search_page.yaml | api.gsb.b2.order.search_page | GO2 / E3E3 | search_field, search_terms, page_size, page_no, error_print_tag |
| b2/order/search_product.yaml | api.gsb.b2.order.search_product | GO2 / E3E3 | product_keyword |
| b2/order/service_fee.yaml | api.gsb.b2.order.service_fee | GO2 / E3E3 | 无 |
| b2/pay/e3e3/order.yaml | api.gsb.b2.pay.e3e3.order | e3e3 | password, order_nos |
| b2/pay/withdraw_refuse_notify.yaml | api.gsb.b2.pay.withdraw_refuse_notify | GO2 / E3E3 | ori_biz_order_no, ori_order_no, refuse_order_no, refuse_amount, fee, refuse_reason |

旧 api.gsb.account.balance、api.gsb.order.search_product 保留兼容入口，已移除 auth。新调用使用 api.gsb.b2.*。

create.checks.yaml 迁到 docs/reference/gsb/b2/order/go2/，仅保留源校验用例参考，不进入 API 树；当前 Engine 不支持旧 checks DSL。未迁移场景、数据、真实账号或秘密。资产元数据 idempotent 保留，但不因此自动重试资金/订单接口。静态/假服务验证不代表真实业务验收。
