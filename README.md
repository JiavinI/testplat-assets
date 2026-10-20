# testplat-assets

Phase 4.1a 用例与登录流程仓库。平台在 Web 维护环境、地址和测试账号凭据；本仓库提供接口、case 和登录流程，不入 Control / Engine。

本交付分支使用 Engine 0.6.0 和精确锁定其提交的配套 Control，支持 schema 0.3；正常安装不需要相邻 Engine 源码。远程主线合并和部署另行安排。秘密不进仓库。登录模板只写 `${secret:字段名}`，字段值由 Web 账号凭据提供，不再由服务器环境变量提供。

## 平台与项目入口（2026-10-18）

清单 `workspace` 声明平台、业务项目及配置归属，需配套本轮 Control。6 个平台、10 个运行工作区：GO2 网站、E3E3 网站；GSB 下的 GO2 / E3E3；代发后台、拿货端、GO2 管理后台分别有 GO2 / E3E3 上下文。

- 旧 `gsb` ID 保留，GO2 使用 `projects/gsb_go2` 资产，配置仍为 `projects/gsb/config`；`gsb_e3e3` 沿用 `projects/gsb` 和独立 E3E3 登录配置，source 为 e3e3。
- 网站和所属 GSB 共用数据库环境／账号，不把网站 Cookie 与 API token 混用。初始网站资产仅检查匿名 SSO 入口，不提供 Page 执行或网站浏览器登录。
- 后台的两个业务项目共用该后台配置，与网站账号分开；拿货端登录 source 使用 `${workspace:project}`，由 Control 从明确的绑定解析。管理后台 Cookie 登录不凭空注入业务项目参数。
- `configuration` 指向同仓直接配置归属，双方 config 路径必须相同；旧清单可不填 workspace。
- 代发后台 `df_admin_pending` 明确标为待适配：可维护独立账号和入口，需登录接口会在发请求前失败；不伪造验证码／Redis 协议。
- 新环境模板的空 api_hosts 不用于运行，实际地址通过 Web / 安全导入维护。E3E3 旧配置没有 portal 地址，不猜测补齐。

仅接口工作区可以暂时没有场景。现有 GSB 搜索和完整场景仍未通过真实业务验收。可复现假服务验收：在 Control 执行 `bash scripts/dev.sh python scripts/verify_platform_assets.py`，使用临时库、虚构账号和本机假服务。

## 目录约定

```text
testplat-assets/
├── testplat.yaml                 # 仓库清单（必需）
├── projects/
│   └── <project>/
│       ├── api/**.yaml           # API；id 与路径一致，如 api.a.b.c → api/a/b/c.yaml
│       ├── scenarios/**.case.yaml # Case；case.a.b → scenarios/a/b.case.yaml
│       ├── scenarios/**.flow.yaml # 新版公共流程，仅供 case/flow 调用
│       └── config/
│           ├── envs/<env>.yaml   # 环境示例模板（运行时以 Web 为准，同步不覆盖）
│           └── auth/
│               ├── _profiles.yaml # 登录流程；不含地址与凭据
│               └── <env>.yaml    # 兼容夹层；平台主路径不从这里取秘密
├── scripts/validate.py           # 本地加载与引用自检（不发请求）
└── README.md
```

清单字段见设计稿 §3：`schema_version`、`projects.<key>.{name,assets,config,default_env}`。
项目键只允许 `[a-z0-9_-]{1,64}`；`assets` / `config` 必须是仓库内相对路径。

`default_env` 只是清单里的示例环境名。项目一旦在 Web 建过环境，列表、默认环境和启停以数据库为准，之后的 Git 同步不覆盖。

## 写法（Engine 0.5 已支持）

### API

- 必需字段：`id`、`name`、`method`、`url`、`host`；可选 `auth`、`request`、`success`。
- `request.type`：`json`（默认）/ `form` / `query` / `raw`。**query 参数写在 `request.body`**，不要写 `params`。
- 入参：在 `request.inputs` 声明 `{type, required, description, default}`；支持 string/number/boolean/object/array，结构化对象和数组在表单中以 JSON 编辑。
- 成功判定：`success.path` + `success.value`，或 `success.status_code`。
- 调用身份：API 不绑定账号；调试时选择 identity，场景步骤声明 identity，none 表示匿名。旧 API auth 仅保留兼容回退。
- `request.template: structured`：支持 `${x!}` 必填、`${x|默认}`、`${a.b}`、now()/date_add_days()，完整占位符保留 JSON 类型，缺失可选字段省略。未标记资产保持原字符串渲染。
- `projects: [go2]` / `[e3e3]` 限制项目专属接口；不声明即公共契约，运行上下文提供项目及账号。
- 资产内**禁止** `${secret:}` / `${login:}` / `${login_host}`（这些只属于登录流程）。

### Case

- `schema_version: "0.2"`；`id` 与路径一致。
- 顺序 `steps`，每步 `type: api` + `api_id`；可用顶层 / 步骤 `params`，并用步骤 identity 选择测试账号。
- 步骤参数引用 case 参数：`${params.xxx}`。

### 场景 0.3（交付分支）

新版 case 的集中 params 与 flow 的显式 inputs/outputs 由 Engine 公开 `describe_case` 校验。支持 api、flow、map、extract、decimal、assert、transform；语义见相邻 Engine 的 `docs/scenario-schema-0.3.md`。旧 Case 0.2 继续走严格旧加载器。

`python scripts/validate.py` 默认只检查正式清单；会递归核对新版 API/flow 引用，并独立验证未被引用的 flow。flow 在临时目录包装为仅供描述的 case，不成为运行入口，不修改源文件。缺少新版公开描述能力的 Engine 会拒绝新版资产，不静默跳过。

在配套 Control 目录使用正式精确锁验证：

```sh
uv run --isolated --locked --extra dev python ../testplat-assets/scripts/validate.py --candidate go2-pending
uv run --isolated --locked --extra dev python ../testplat-assets/scripts/validate.py --candidate scenario-parameters
uv run --isolated --locked --extra dev pytest -q ../testplat-assets/tests
```

默认清单已为 GO2 启用多商品待支付场景，E3E3 不显示此入口。`projects/gsb_go2` 保留旧 smoke 和所有原 GSB API 的逐字副本；API 变更须同步两个目录，测试检查路径集合和内容一致。独立目录防止现有 case 扫描将 GO2 入口暴露给 E3E3，不新增项目过滤语义或配置副本。

候选检查只复制 scenarios 和所需 API 到临时目录；GO2 复用当前七个 API，不复制环境、登录模板或账号数据，不加入生产清单。通过仅表示静态定义、契约形状与引用有效；不验证动态响应、金额业务结果、环境 host、账号可用性或 WAIT_PAY 状态。运行时预检和真实业务验收分别完成。验证失败只输出异常类型和可用的 YAML 行列，避免打印资产片段。

### 环境模板（`config/envs/<env>.yaml`）

- 这些文件是示例 / 初始化模板，**不是**运行时来源。
- 运行时的环境列表、`api_hosts`、超时、`case_params`、账号和启停都在 Web 维护。
- 同步资产可以更新接口、case 和登录流程，**不会覆盖**已在 Web 保存的环境、账号或启停。
- 新建 `pre` 等 Git 里没有的环境，直接在 Web 创建，不必再提交同名 yaml。
- 模板至少提供 `api_hosts`：逻辑 host 名 → 含协议的基址（如 `http://host:port`）。登录 host 与业务 host 分开（本仓库 gsb：`unified_login` 与 `gsb`）。
- 文件名即示例环境名；`_` 开头的文件不作为环境名。

### 登录流程（`config/auth/_profiles.yaml`）

- `identities.<流程名>` 是可复用登录流程，**不是**账号名。多个 Web 账号可以引用同一流程。
- 流程名：`^[a-z][a-z0-9_]*$`，保留名 `none` 不可用。本仓库 GSB 流程名为 `gsb_login`。
- 形状与原先的 `login` 相同：`host` + `steps` + `extract` + `inject`；可选 `validity.ttl_seconds`。省略 `strategy` 即 `generic_flow`。
- `host` 只写逻辑名（本仓库为 `unified_login`）。实际 URL 来自 Web 里所选环境的服务地址。
- 凭据占位符写 `${secret:字段名}`。GSB 的字段名是 `username`、`password`。Web 账号的凭据字典按这两个字段填写。
- 非秘密业务字面量直接写在流程里。原 GO2 的 GSB 登录 `source` 保持 `go2`；E3E3 的配置为 `e3e3`，不从内部工作区键推导，也不是凭据字段。
- 注入用 `${login:名字}`；路径里可用 `${login_host}`。
- 本文件不写环境地址，不写账号密码，也不写 `TESTPLAT_*` 环境变量名。

### 测试账号与环境

- GSB 不再提供 `config/auth/<env>.yaml`；原先空的 `auth/test.yaml` 已删除。
- Control 用 `_profiles.yaml` 和 Web 中所选环境的账号凭据构造身份表，完整账号引用如 `gsb.b2.primary`。
- 使用前须在 Web 配置项目环境和测试账号。不要在 Git 中恢复账号密码或 `TESTPLAT_GSB_*` 环境变量引用。

## 当前不支持的写法

| 写法 | 说明 |
|---|---|
| `request.params`（query） | 发送侧读的是 `request.body` |
| 数据驱动 case / suites / UI 步骤 | 本批不做 |
| schema 0.3 在正式旧 Engine 上运行 | 使用本交付分支配套的 Engine 0.6.0 精确锁；跨步骤引用由公开描述与运行时预检校验 |
| 插件登录（如 `vcode_redis`） | 需安装插件并在 `login_plugins` 白名单声明 |
| api / case 内写秘密字面量或 `${secret:}` | 加载期直接拒绝 |
| 步骤字段 `account` | 使用 identity；account 仍为未知字段 |
| `${secret:TESTPLAT_*}` | 不再作为平台主路径；登录流程只用凭据字段名 |

2026-10-19 已迁移 24 个 GSB 接口与 1 份只读 checks 参考；完整路径、项目、必填与兼容说明见 [迁移清单](docs/gsb-api-migration-2026-10-19.md)。

## 新增资产步骤

1. 在对应 `projects/<project>/api/...` 新增 YAML，补齐 `id`（与路径一致），只用上表「已支持」字段。需要登录时由调用者选择账号，不把账号名写入 API。
2. 若需登录：在 `config/auth/_profiles.yaml` 增加或复用流程。凭据字段名写入 `${secret:字段名}`，到 Web 对应该环境的账号里填写值，不要写进 Git，也不要加服务器环境变量。
3. 若需新的逻辑 host：在 Web 环境的服务地址里填写。`config/envs/<env>.yaml` 只在要更新示例模板时才改。
4. 写 case：`scenarios/.../*.case.yaml`，`api_id` 指向已有接口；参数给示例值。
5. 若是新项目：在 `testplat.yaml` 登记，并建齐 `api` / `scenarios` / `config/envs` 与 `config/auth/_profiles.yaml`。
6. 本地运行：`python scripts/validate.py`（需能 import Engine 0.5；可选 Control 的 `load_profile_catalog` / `load_auth`）。

## Web 凭据与不再使用的环境变量

GSB 冒烟在 Web 的填法：

| 项 | 值 |
|---|---|
| 账号名 | `gsb.b2.primary`（gsb / b2 分组下的 primary 引用；不是登录用户名） |
| 登录流程 | `gsb_login` |
| 凭据字段 | `username`、`password` |

登录用户名、密码只存在 Web。改登录用户名或密码不改 case，也不改账号名。

以下环境变量**不再使用**，平台主路径不会读取，也不要写回资产：

- `TESTPLAT_GSB_USERNAME`
- `TESTPLAT_GSB_PASSWORD`

服务器环境变量只留给平台自身配置和加密主密钥（如 `TESTPLAT_MASTER_KEY`），不用来保存被测账号。

## 本批范围（gsb）

| 类型 | 内容 |
|---|---|
| 登录流程 | `gsb_login`：`unified_login` + `GET /site/login`（query：`username` / `password` / 字面量 `source: go2`）；token=`$.data.hash`→`X-TOKEN`，user_id=`$.data.userId`→`X-USER-ID`；`ttl_seconds=14400` |
| 账号 | Web 账号完整引用 `gsb.b2.primary` 引用 `gsb_login`；凭据字段 `username`、`password` |
| API | 24 个规范接口 `api.gsb.b1.*` / `api.gsb.b2.*`；旧余额和搜索 ID 保留兼容，不绑定账号 |
| Case | `case.gsb.smoke`（balance → search_product） |
| 环境模板 | `config/envs/test.yaml`：`gsb=http://java.qa.gogoo.cn:8306`，`unified_login=http://tt.ximgs.net`。运行时以 Web 为准 |

上述表是已有 GSB 范围；新增平台入口范围见本文开头。没有新增真实订单写操作。
