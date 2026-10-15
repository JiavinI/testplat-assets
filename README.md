# testplat-assets

Phase 4.0 用例与配置仓库。平台只做「选仓库 → 同步 → 选项目 / 环境 → 运行 → 看结果」；本仓库不入 Control / Engine。

基线：Engine `v0.5.0`（`5231fb4`）。秘密不进仓库，只写 `${secret:NAME}`，值由平台服务器环境变量提供。

## 目录约定

```text
testplat-assets/
├── testplat.yaml                 # 仓库清单（必需）
├── projects/
│   └── <project>/
│       ├── api/**.yaml           # API；id 与路径一致，如 api.a.b.c → api/a/b/c.yaml
│       ├── scenarios/**.case.yaml # Case；case.a.b → scenarios/a/b.case.yaml
│       └── config/
│           ├── envs/<env>.yaml   # 环境 hosts 等（文件名即环境名；_ 开头忽略）
│           └── auth/<env>.yaml   # 身份；秘密只用 ${secret:}
├── scripts/validate.py           # 本地加载与引用自检（不发请求）
└── README.md
```

清单字段见设计稿 §3：`schema_version`、`projects.<key>.{name,assets,config,default_env}`。
项目键只允许 `[a-z0-9_-]{1,64}`；`assets` / `config` 必须是仓库内相对路径。

## 写法（Engine 0.5 已支持）

### API

- 必需字段：`id`、`name`、`method`、`url`、`host`；可选 `auth`、`request`、`success`。
- `request.type`：`json`（默认）/ `form` / `query` / `raw`。**query 参数写在 `request.body`**，不要写 `params`。
- 入参：在 `request.inputs` 用「字段名 → 类型名」（如 `product_keyword: str`）声明；body 里用 `${字段名}`。
- 成功判定：`success.path` + `success.value`，或 `success.status_code`。
- `auth`：身份名，或 `none`（匿名）；省略则走环境 `default_identity`。
- 资产内**禁止** `${secret:}` / `${login:}` / `${login_host}`（这些只属于 auth 配置）。

### Case

- `schema_version: "0.2"`；`id` 与路径一致。
- 顺序 `steps`，每步 `type: api` + `api_id`；可用顶层 / 步骤 `params`。
- 步骤参数引用 case 参数：`${params.xxx}`。

### 环境（`config/envs/<env>.yaml`）

- 至少提供 `api_hosts`：host 名 → 含协议的基址（如 `http://host:port`）。
- 登录 host 与业务 host 可分开配置（本仓库 gsb：`unified_login` 与 `gsb`）。

### 鉴权（`config/auth/<env>.yaml`）

- `identities.<名>`：要么静态 `headers`，要么 `login`（互斥）。
- 登录用 `generic_flow`（省略 `strategy` 即默认）：`host` + `steps` + `extract` + `inject`；可选 `validity.ttl_seconds`。
- 秘密只写 `${secret:TESTPLAT_...}`；注入用 `${login:名字}`；路径里可用 `${login_host}`。
- 身份名：`^[a-z][a-z0-9_]*$`，保留名 `none` 不可用。

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

订单创建类等依赖点号引用与默认值语法的旧接口，首批不迁移。

## 新增资产步骤

1. 在对应 `projects/<project>/api/...` 新增 YAML，补齐 `id`（与路径一致），只用上表「已支持」字段。
2. 若需登录：在 `config/auth/<env>.yaml` 增加或复用身份；秘密变量名加入下方清单并由运维注入服务器。
3. 若需新 host：写入 `config/envs/<env>.yaml` 的 `api_hosts`。
4. 写 case：`scenarios/.../*.case.yaml`，`api_id` 指向已有接口；参数给示例值。
5. 若是新项目：在 `testplat.yaml` 登记，并建齐 `api` / `scenarios` / `config/{envs,auth}`。
6. 本地运行：`python scripts/validate.py`（需能 import Engine 0.5；可选 Control auth_loader）。

## 秘密环境变量名清单

只列名，不含值。变量名须匹配 `^TESTPLAT_[A-Z0-9_]+$`。

- `TESTPLAT_GSB_USERNAME`
- `TESTPLAT_GSB_PASSWORD`

## 本批范围（gsb）

| 类型 | 内容 |
|---|---|
| 身份 | `gsb`：`unified_login` + `GET /site/login`（query：username / password / source）；token=`$.data.hash`→`X-TOKEN`，user_id=`$.data.userId`→`X-USER-ID`；`ttl_seconds=14400` |
| source | 字面量 `go2`（非秘密；换项目需另配身份或改此值） |
| API | `api.gsb.account.balance`、`api.gsb.order.search_product` |
| Case | `case.gsb.smoke`（balance → search_product） |
| 环境 | `test`：`gsb=http://java.qa.gogoo.cn:8306`，`unified_login=http://tt.ximgs.net` |

其它业务系统与接口本批不做。
