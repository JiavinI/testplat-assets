# testplat-assets

Phase 4.1a 用例与登录流程仓库。平台在 Web 维护环境、地址和测试账号凭据；本仓库提供接口、case 和登录流程，不入 Control / Engine。

基线：Engine `v0.5.0`（`5231fb4`）。秘密不进仓库。登录模板只写 `${secret:字段名}`，字段值由 Web 账号凭据提供，不再由服务器环境变量提供。

## 目录约定

```text
testplat-assets/
├── testplat.yaml                 # 仓库清单（必需）
├── projects/
│   └── <project>/
│       ├── api/**.yaml           # API；id 与路径一致，如 api.a.b.c → api/a/b/c.yaml
│       ├── scenarios/**.case.yaml # Case；case.a.b → scenarios/a/b.case.yaml
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
- 入参：在 `request.inputs` 用「字段名 → 类型名」（如 `product_keyword: str`）声明；body 里用 `${字段名}`。
- 成功判定：`success.path` + `success.value`，或 `success.status_code`。
- `auth`：账号名，或 `none`（匿名）。4.1a 不增加步骤级 `account`；GSB 接口继续写 `auth: gsb`。
- 资产内**禁止** `${secret:}` / `${login:}` / `${login_host}`（这些只属于登录流程）。

### Case

- `schema_version: "0.2"`；`id` 与路径一致。
- 顺序 `steps`，每步 `type: api` + `api_id`；可用顶层 / 步骤 `params`。
- 步骤参数引用 case 参数：`${params.xxx}`。

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
- 非秘密业务字面量直接写在流程里。GSB 登录的 `source` 固定为 `go2`，不从项目键推导，也不是凭据字段。
- 注入用 `${login:名字}`；路径里可用 `${login_host}`。
- 本文件不写环境地址，不写账号密码，也不写 `TESTPLAT_*` 环境变量名。

### 环境 auth 文件（`config/auth/<env>.yaml`）

- 平台主路径不读这些文件。已有 Web 环境时，Control 用 `_profiles.yaml` 和该环境的账号凭据构造身份表，身份名是账号名。
- `test.yaml` 只保留兼容夹层：说明运行时凭据由 Web 维护，并给出空的 `identities: {}`，让历史 `load_auth` 读到一份不含秘密的空表。
- 不要在这里恢复 `TESTPLAT_GSB_USERNAME` / `TESTPLAT_GSB_PASSWORD`。没有 Web 环境时，这份空表不会再回退到服务器环境变量。

## 当前不支持的写法

| 写法 | 说明 |
|---|---|
| `${x!}` 必填后缀 | Engine 会把 `x!` 当成变量名 |
| `${x\|默认值}` | 不支持；默认值放 case 参数或字面量 |
| `${a.b.c}` 点号路径 | 只支持平铺键；嵌套对象需先拆平 |
| `request.params`（query） | 发送侧读的是 `request.body` |
| 数据驱动 case / suites / UI 步骤 | 本批不做 |
| 跨步骤取响应字段做下一步入参 | 能力未在本批资产中使用；需要时先人工传参 |
| 插件登录（如 `vcode_redis`） | 需安装插件并在 `login_plugins` 白名单声明 |
| api / case 内写秘密字面量或 `${secret:}` | 加载期直接拒绝 |
| 步骤字段 `account` | 4.1b 才扩展；当前 schema 0.2 会拒绝 |
| `${secret:TESTPLAT_*}` | 不再作为平台主路径；登录流程只用凭据字段名 |

订单创建类等依赖点号引用与默认值语法的旧接口，首批不迁移。

## 新增资产步骤

1. 在对应 `projects/<project>/api/...` 新增 YAML，补齐 `id`（与路径一致），只用上表「已支持」字段。需要登录的接口写账号名，例如 `auth: gsb`。
2. 若需登录：在 `config/auth/_profiles.yaml` 增加或复用流程。凭据字段名写入 `${secret:字段名}`，到 Web 对应该环境的账号里填写值，不要写进 Git，也不要加服务器环境变量。
3. 若需新的逻辑 host：在 Web 环境的服务地址里填写。`config/envs/<env>.yaml` 只在要更新示例模板时才改。
4. 写 case：`scenarios/.../*.case.yaml`，`api_id` 指向已有接口；参数给示例值。
5. 若是新项目：在 `testplat.yaml` 登记，并建齐 `api` / `scenarios` / `config/envs` 与 `config/auth/_profiles.yaml`。
6. 本地运行：`python scripts/validate.py`（需能 import Engine 0.5；可选 Control 的 `load_profile_catalog` / `load_auth`）。

## Web 凭据与不再使用的环境变量

GSB 冒烟在 Web 的填法：

| 项 | 值 |
|---|---|
| 账号名 | `gsb`（与 API `auth: gsb` 相同；不是登录用户名） |
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
| 账号 | Web 账号名 `gsb` 引用 `gsb_login`；凭据字段 `username`、`password` |
| API | `api.gsb.account.balance`、`api.gsb.order.search_product`（均 `auth: gsb`） |
| Case | `case.gsb.smoke`（balance → search_product） |
| 环境模板 | `config/envs/test.yaml`：`gsb=http://java.qa.gogoo.cn:8306`，`unified_login=http://tt.ximgs.net`。运行时以 Web 为准 |

其它业务系统与接口本批不做。旧矩阵如何改为平台登录不在本仓库这一批。
