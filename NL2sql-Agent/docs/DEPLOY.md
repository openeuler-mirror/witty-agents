# NL2SQL 部署指南

部署 **业务库**、对接 **rag-core**，并启动 **NL2SQL**（Web/API）。  
业务明细、API Key **不在本仓库**；测试步骤见 [TEST.md](./TEST.md)。

## 1. 环境要求

| 组件 | 建议 |
|------|------|
| OS | Linux x86_64 / aarch64 |
| Python | 3.10+ |
| Docker | 可选；compose 拉 ES 7.10.2，或 `scripts/start_opengauss.sh` |
| Java 11+ | 可选；仅 `scripts/start_hbase.sh` 需要 |
| rag-core | **必须另外部署**的 HTTP 服务（默认 `:19988`） |
| LLM | OpenAI 兼容 API（Base URL + API Key + Model） |
| 业务库 | 按要测的源：ES / OpenGauss / 原生 HBase REST（非 Phoenix） |

| 服务 | 默认端口 |
|------|----------|
| Elasticsearch | 9200 |
| OpenGauss | 5434（映射容器 5432） |
| HBase REST | 16080 |
| rag-core | 19988（若在 9988，可用脚本代理） |
| NL2SQL Web/API | 8199 |

## 2. 获取代码

```bash
git clone https://atomgit.com/zou-liushi/witty-agents.git
cd witty-agents/NL2sql-Agent
```

## 3. 一键启动（推荐）

```bash
chmod +x scripts/*.sh
cp -n .env.example .env
# 编辑 .env：NL2SQL_LLM_API_KEY、NL2SQL_RAG_ACCESS_KEY、NL2SQL_RAG_BASE_URL
curl -s http://127.0.0.1:19988/health_check

./scripts/start_all.sh
```

该脚本依次：检查/尝试 ES → 检查 rag-core → 创建 `.venv` 并启动 Web。  
**不会**自动起 OpenGauss / HBase；需要时另跑：

```bash
./scripts/start_opengauss.sh
./scripts/start_hbase.sh
```

然后把账号写进 `configs/datasources.yaml`（OG 的 `password` 必填）。

常用开关：

```bash
SKIP_ES=1 ./scripts/start_all.sh
SKIP_RAG=1 ./scripts/start_all.sh
REQUIRE_RAG=1 ./scripts/start_all.sh
RAG_UPSTREAM=http://127.0.0.1:9988 ./scripts/start_all.sh
```

单独脚本：`start_es.sh` / `start_rag_core.sh` / `start_web.sh`。

## 4. 分项说明

### 4.1 数据源（一次只用一个）

编辑 `configs/datasources.yaml`。Web 下拉来自该文件；健康检查只 ping **当前选中**的 `datasource_id`。

```bash
curl -s 'http://127.0.0.1:8199/api/health?datasource_id=local-es'
curl -s -X POST http://127.0.0.1:8199/api/datasources/test \
  -H 'Content-Type: application/json' \
  -d '{"datasource_id":"local-opengauss"}'
```

设置页全局 hosts **不会覆盖** yaml 里已写的连接项。

### 4.2 Elasticsearch

```bash
./scripts/start_es.sh          # 或自备集群后 SKIP_ES=1
curl -s http://127.0.0.1:9200
```

### 4.3 OpenGauss

兼容 PostgreSQL 协议，依赖 `psycopg2`（见 `requirements.txt`）。用**正版 OpenGauss**，不要用普通 Postgres 冒充验收。

```bash
./scripts/start_opengauss.sh
# 把 yaml 中 local-opengauss.password 改成脚本提示的密码
```

已有实例：只改 yaml 的 host/port/database/username/password。

### 4.4 HBase（原生表 + REST）

```bash
./scripts/start_hbase.sh
curl -s http://127.0.0.1:16080/version
```

二进制默认装到仓库 `.opt/`（已 gitignore）。现场已有 REST 时，改 yaml 的 `host` / `rest_port`（或 `rest_url`）。

### 4.5 rag-core

本仓库不内嵌 rag-core。

```bash
curl -s http://127.0.0.1:19988/health_check
```

配置 `configs/rag_core.yaml` 或 `.env` 的 `NL2SQL_RAG_BASE_URL` / `NL2SQL_RAG_ACCESS_KEY`。

### 4.6 同步规则（每个数据源各做一次）

```bash
source .venv/bin/activate
export PYTHONPATH=.
python3 scripts/sync_rules_to_rag.py --database-id local-es
```

现场空规则：见 [TEST.md](./TEST.md)「冷启动」。

### 4.7 仅启动 Web

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp -n .env.example .env
./scripts/start_web.sh
```

浏览器：`http://127.0.0.1:8199`  
OpenCode：`./scripts/register_opencode.sh`（需 Web 已在 8199）。Skill **不会**改用 OpenCode 会话模型，LLM 仍读 `.env` / 设置页。

## 5. 配置检查清单

- [ ] 当前要测的库可连（Web「测试当前数据源」）  
- [ ] rag-core 健康，`access_key` 正确  
- [ ] `.env` 已填 LLM  
- [ ] 该数据源已 sync 或冷启动 commit  
- [ ] 业务数据已导入（见 [TEST.md](./TEST.md)）  

## 6. 安全注意

- 不要提交 `.env`、`data/runtime_settings.json`、真实密码  
- 默认查询只读；勿对生产库开放写权限  
