# NL2SQL Agent

自然语言 →（可选澄清）→ 召回 rag-core 规则 → 生成只读查询 → 在**当前数据源**执行。

| 数据源 type | 生成物 | 执行 |
|-------------|--------|------|
| `elasticsearch` | IR（多步半连接） | ES |
| `opengauss` | SQL | OpenGauss（PG 协议，只读 SELECT） |
| `hbase` | JSON scan 计划 | 原生 HBase REST（非 Phoenix） |

一次只连**当前选中**的那一个库。业务数据与 API Key **不在本包内**。

## 环境要求

| 组件 | 说明 |
|------|------|
| Node.js | ≥ 18（仅用于 npm 与 CLI） |
| Python | 3.11 / 3.12（`python3 -m venv` / pip） |
| 业务库 | 按源准备：ES 7.x（默认 `9200`）等 |
| rag-core | 已部署的 HTTP 服务（默认 `19988`） |
| LLM | OpenAI 兼容 API |

## 安装与启动（npm online 包）

```bash
# 1) 安装（包名 witty-agent-nl2sql-online，内含 Python 后端）
npm install -g witty-agent-nl2sql-online

# 2) 交互配置 LLM / rag-core / ES / Web 端口（生成 .env，并写入 configs/datasources.yaml）
nl2sql init

# 3) 启动：自动创建 .venv、安装 Python 依赖、拉起 Web
nl2sql start
# 浏览器 http://127.0.0.1:8199 ；健康检查 curl -s http://127.0.0.1:8199/api/health

# 4) 注册到 OpenCode（写入 plugin 数组并软链 nl2sql skill）
nl2sql-agent configure          # register 为别名
```

`init` / `start` 默认作用在全局包根目录（`$(npm root -g)/witty-agent-nl2sql-online`）；
非交互环境（管道/CI）下 `nl2sql init` 自动接受全部默认值。

### 备选：setup + start_all.sh（CI/合同安装模型）

```bash
nl2sql-setup install            # 依赖装到 ~/.cache/witty-agents/<包名>/venvs/nl2sql
nl2sql-setup check
PKG_ROOT="$(npm root -g)/witty-agent-nl2sql-online"
SKIP_ES=1 SKIP_RAG=1 bash "$PKG_ROOT/scripts/start_all.sh"
```

`nl2sql start` 与 `start_all.sh` 各自维护包内 `.venv`，二者择一即可。

### 手动配置（不走 init）

```bash
PKG_ROOT="$(npm root -g)/witty-agent-nl2sql-online"
cp "$PKG_ROOT/.env.example" "$PKG_ROOT/.env"
vi "$PKG_ROOT/.env"     # 填 NL2SQL_LLM_API_KEY、NL2SQL_RAG_ACCESS_KEY 等
```

需填写的关键变量（模板见 `.env.example`）：

| 变量 | 说明 |
|------|------|
| `NL2SQL_LLM_BASE_URL` / `NL2SQL_LLM_API_KEY` / `NL2SQL_LLM_MODEL` | OpenAI 兼容 LLM |
| `NL2SQL_RAG_BASE_URL` / `NL2SQL_RAG_ACCESS_KEY` | rag-core 服务地址与访问密钥 |
| `NL2SQL_WEB_HOST` / `NL2SQL_WEB_PORT` | Web 监听地址（默认 `0.0.0.0:8199`） |

数据源（ES / OpenGauss / HBase）连接在 Web「数据源」页面配置，或编辑 `configs/datasources.yaml`。

### 启动 Web

主入口是 `nl2sql start`（见上文安装流程）。启动后访问 <http://127.0.0.1:8199>，健康检查：

```bash
curl -s http://127.0.0.1:8199/api/health
```

规则需同步到 rag-core（Web「规则中心」或 `scripts/sync_rules_to_rag.py`）。
部署细节见 [docs/DEPLOY.md](docs/DEPLOY.md)，测试见 [docs/TEST.md](docs/TEST.md)。

## 卸载

```bash
nl2sql-agent remove                       # 移除插件注册与 skill 软链
npm uninstall -g witty-agent-nl2sql-online
rm -rf ~/.cache/witty-agents/witty-agent-nl2sql-online   # 删除 setup 创建的 venv
```

## 包内容说明

| 路径 | 说明 |
|------|------|
| `dist/index.js` | OpenCode 插件入口（注册 agent） |
| `opencode_plugin/` | role prompt 与 `skills/nl2sql` |
| `bin/` | `nl2sql`（init/start）、`nl2sql-agent`（注册）、`nl2sql-setup`（Python 环境） |
| `lib/` | 注册/配置逻辑 |
| `apps/` | HTTP API + Web UI（uvicorn 入口 `apps.web.main:app`） |
| `nl2sql_core/` | Pipeline、多引擎、规则、IR（ES） |
| `configs/` | 配置模板（无密钥） |
| `fixtures/` | 规则原料 / 字段说明 |
| `scripts/` | 启动、规则同步、冷启动脚本 |
| `requirements.txt` | Python 第三方依赖（setup 在线安装；offline 包另带 wheelhouse） |

## 不交付内容

- 业务/测试 JSON、ES dump、内部评测结果
- 含密钥的 `.env`、`data/runtime_settings.json`
- 打包产物 `*.tgz`、测试造数目录
