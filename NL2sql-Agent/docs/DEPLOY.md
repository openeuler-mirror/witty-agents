# NL2SQL 部署指南

本文说明如何部署 **Elasticsearch**、对接 **rag-core**，并启动 **NL2SQL**（Web/API）。  
业务明细数据不在本仓库，由测试环境自行导入（见 [TEST.md](./TEST.md)）。

## 1. 环境要求

| 组件 | 建议 |
|------|------|
| OS | Linux x86_64 / aarch64 |
| Python | 3.10+ |
| Docker | 用于一键起 ES 7.10.2（也可用已有 ES） |
| rag-core | 已部署的 HTTP 服务（默认期望 `:19988`，可改配置） |
| LLM | OpenAI 兼容 API（Base URL + API Key + Model） |

端口约定：

| 服务 | 默认端口 |
|------|----------|
| Elasticsearch | 9200 |
| rag-core | 19988（若实例在 9988，脚本可代理） |
| NL2SQL Web/API | 8199 |

## 2. 获取代码

```bash
git clone https://atomgit.com/zou-liushi/witty-agents.git
cd witty-agents/NL2sql-Agent
```

目录中原有的 `DESIGN.md`、历史包等文件请保留；业务代码与 `apps/`、`nl2sql_core/` 等并列。

## 3. 一键启动（推荐）

```bash
cd NL2sql-Agent
chmod +x scripts/*.sh
./scripts/start_all.sh
```

该脚本依次：

1. **ES**：若 `9200` 不可用，则 `docker compose -f deploy/docker-compose.yml up -d`
2. **rag-core**：检查 `19988` 健康；若仅有 `9988` 等上游，则尝试 `ncat` 代理到 `19988`
3. **NL2SQL**：创建 `.venv`（若无）、安装依赖、启动 `uvicorn`（8199）

常用开关：

```bash
SKIP_ES=1 ./scripts/start_all.sh          # 已有 ES
SKIP_RAG=1 ./scripts/start_all.sh         # 稍后手动配 rag
RAG_UPSTREAM=http://127.0.0.1:9988 ./scripts/start_all.sh
```

单独脚本：

```bash
./scripts/start_es.sh
./scripts/start_rag_core.sh
./scripts/start_web.sh
```

## 4. 分项说明

### 4.1 Elasticsearch

**方式 A（本仓库 Compose）**

```bash
./scripts/start_es.sh
# 或
docker compose -f deploy/docker-compose.yml up -d
curl -s http://127.0.0.1:9200
```

**方式 B（已有集群）**

修改 `configs/datasources.yaml` 中 `local-es.hosts`，或启动后在 Web「设置」页填写。  
`./scripts/start_all.sh` 时加 `SKIP_ES=1`。

### 4.2 rag-core

本仓库**不内嵌**完整 rag-core 二进制/依赖（其还需标量库、向量库等）。请使用测试环境已有实例。

1. 确认健康检查通过，例如：

```bash
curl -s http://127.0.0.1:19988/health_check
# 或
curl -s http://127.0.0.1:9988/health_check
```

2. 配置 `configs/rag_core.yaml`：

```yaml
base_url: "http://127.0.0.1:19988"
access_key: "<你们的 access_key>"
default_kb_id: ""   # 首次 sync 规则后会写入数据源的 rules_kb_id
```

也可在 Web「设置」或 `.env` 中配置 `NL2SQL_RAG_BASE_URL` / `NL2SQL_RAG_ACCESS_KEY`。

3. 若服务在 `9988` 而希望 NL2SQL 仍访问 `19988`：

```bash
RAG_UPSTREAM=http://127.0.0.1:9988 ./scripts/start_rag_core.sh
```

### 4.3 NL2SQL

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填写 LLM Key
./scripts/start_web.sh
```

浏览器：`http://127.0.0.1:8199`  
健康：`curl -s http://127.0.0.1:8199/api/health`

OpenCode Skill（可选）：

```bash
./scripts/register_opencode.sh
```

Skill 通过 HTTP 调用本机 `8199`，因此 **Web/API 进程必须保持运行**。

## 5. 配置检查清单

- [ ] ES `9200` 可访问  
- [ ] rag-core 健康检查通过，`access_key` 正确  
- [ ] `.env` 或设置页已填 LLM  
- [ ] `/api/health` 中 ES / RAG 为可用（或按环境预期）  
- [ ] 已按 [TEST.md](./TEST.md) 导入规则（及业务数据）

## 6. 安全注意

- 不要提交 `.env`、`data/runtime_settings.json` 或真实 API Key  
- 默认查询只读；勿对生产库开放写权限  
