# NL2SQL 部署指南

本文说明如何部署 **Elasticsearch**、对接 **rag-core**，并启动 **NL2SQL**（Web/API）。  
业务明细数据、API Key **均不在本仓库**；由部署方自行配置与导入（见 [TEST.md](./TEST.md)）。

## 1. 环境要求

| 组件 | 建议 |
|------|------|
| OS | Linux x86_64 / aarch64 |
| Python | 3.10+ |
| Docker | 可选；用于 compose 拉起 ES 7.10.2（aarch64 若拉镜像失败请自备 ES） |
| rag-core | **必须另外部署**的 HTTP 服务（默认 `:19988`）；本仓库不内嵌 |
| LLM | OpenAI 兼容 API（Base URL + API Key + Model） |

端口约定：

| 服务 | 默认端口 |
|------|----------|
| Elasticsearch | 9200 |
| rag-core | 19988（若在 9988，可用脚本代理） |
| NL2SQL Web/API | 8199 |

## 2. 获取代码

```bash
git clone https://atomgit.com/zou-liushi/witty-agents.git
cd witty-agents/NL2sql-Agent
```

## 3. 一键启动（推荐）

先准备 `.env`，并确认 rag-core 健康：

```bash
chmod +x scripts/*.sh
cp -n .env.example .env
# 编辑 .env：NL2SQL_LLM_API_KEY、NL2SQL_RAG_ACCESS_KEY、NL2SQL_RAG_BASE_URL
curl -s http://127.0.0.1:19988/health_check

./scripts/start_all.sh
```

该脚本依次：

1. **ES**：若 `9200` 不可用，则尝试 `docker compose -f deploy/docker-compose.yml up -d`；失败只告警（可用自备 ES）  
2. **rag-core**：检查健康；若仅有其它端口上游，尝试 `ncat` 代理到 `19988`；失败默认告警并继续起 Web（`REQUIRE_RAG=1` 可改为硬失败）  
3. **NL2SQL**：创建 `.venv`、安装依赖、启动 `uvicorn`（8199）

常用开关：

```bash
SKIP_ES=1 ./scripts/start_all.sh                    # 已有 ES
SKIP_RAG=1 ./scripts/start_all.sh                   # 稍后配 rag
REQUIRE_RAG=1 ./scripts/start_all.sh                # 无 rag 则退出
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
curl -s http://127.0.0.1:9200
```

**方式 B（已有集群）**

修改 `configs/datasources.yaml` 中数据源的 `hosts`。  
Web「设置」中的 ES hosts **不会覆盖** yaml 里已写的 hosts。  
启动时加 `SKIP_ES=1`。

### 4.2 rag-core

本仓库**不内嵌** rag-core。请使用已有实例：

```bash
curl -s http://127.0.0.1:19988/health_check
```

配置 `configs/rag_core.yaml` 或 `.env` 中的 `NL2SQL_RAG_BASE_URL` / `NL2SQL_RAG_ACCESS_KEY`。

上游在 `9988` 时：

```bash
RAG_UPSTREAM=http://127.0.0.1:9988 ./scripts/start_rag_core.sh
```

### 4.3 同步规则（首次必做）

Web 起来后：

```bash
source .venv/bin/activate
export PYTHONPATH=.
python3 scripts/sync_rules_to_rag.py --database-id local-es
# 已有 KB：加 --reuse-kb
```

### 4.4 仅启动 Web

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp -n .env.example .env
./scripts/start_web.sh
```

浏览器：`http://127.0.0.1:8199`  
健康：`curl -s http://127.0.0.1:8199/api/health`

OpenCode Skill（可选）：`./scripts/register_opencode.sh`（需 Web 已在 8199 运行）。

## 5. 配置检查清单

- [ ] ES `9200` 可访问  
- [ ] rag-core 健康，`access_key` 正确  
- [ ] `.env` 已填 LLM  
- [ ] 已 `sync_rules_to_rag`  
- [ ] 业务数据已导入（见 [TEST.md](./TEST.md)）  
- [ ] `/api/health` 符合预期  

## 6. 安全注意

- 不要提交 `.env`、`data/runtime_settings.json` 或真实 API Key  
- 默认查询只读；勿对生产库开放写权限  
