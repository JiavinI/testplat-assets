# 场景参数与公共流程最小示例

本目录独立于生产项目清单，不会自动同步进现有工作区。需要配套 Control 精确锁定的 Engine 0.6.0，无需相邻 Engine 源码。

`scenarios/demo/repeat.case.yaml` 的 `params` 集中维护 common/private。两个步骤显式引用同一 flow，分别绑定私有商品数量，共用 enabled；流程只读取自己的 inputs，通过 outputs 导出结果，末步引用两次调用各自的输出。步骤不维护业务值副本。

Web 中沿用场景统一参数区及默认值、环境覆盖和单次输入保存能力。覆盖按顶层键替换：修改 private 时需提交完整 private 对象。flow 没有独立运行入口，需要 case 包装。

从 Control 目录验证：

```sh
uv run --isolated --locked --extra dev pytest -q ../testplat-assets/tests/test_scenario_example.py
```

测试使用 `httpx.MockTransport` 在内存回显，断言实际请求数量、类型、两次调用隔离和下游来源；不监听端口，不连接真实被测系统。示例不包含账号、地址配置或凭据。
