# NL2SQL Agent

自然语言 →（可选澄清）→ 召回 rag-core 规则 → 生成只读查询 → 在 Elasticsearch 执行（**IR 多步半连接**）。

业务数据与 API Key **不在本仓库**。

## 环境要求

| 组件 | 说明 |
|------|------|
| Python | 3.10+ |
| Elasticsearch | 7.x，默认 `9200`（可用 Docker，或自备后 `SKIP_ES=1`） |
| rag-core | 已部署的 HTTP 服务（默认 `19988`）；无则 Web 能起，但无法问答 |
| LLM | OpenAI 兼容 API（填进 `.env`） |
| Docker | 仅「本机自动起 ES」时需要 |

## 快速开始

```bash
git clone https://atomgit.com/zou-liushi/witty-agents.git
cd witty-agents/NL2sql-Agent

chmod +x scripts/*.sh
cp .env.example .env
# 编辑 .env：至少填写
#   NL2SQL_LLM_API_KEY=...
#   NL2SQL_RAG_ACCESS_KEY=...   # 与 rag-core 一致
#   NL2SQL_RAG_BASE_URL=http://127.0.0.1:19988

# 确认 rag-core 已可用（必做，否则规则同步失败）
curl -s http://127.0.0.1:19988/health_check

./scripts/start_all.sh
# 已有 ES：  SKIP_ES=1 ./scripts/start_all.sh
# 暂无 rag： SKIP_RAG=1 ./scripts/start_all.sh
# rag 在 9988：RAG_UPSTREAM=http://127.0.0.1:9988 ./scripts/start_all.sh

# 浏览器 http://127.0.0.1:8199
```

另开终端，同步规则（首次必做）：

```bash
cd witty-agents/NL2sql-Agent
source .venv/bin/activate
export PYTHONPATH=.
python3 scripts/sync_rules_to_rag.py --database-id local-es
```

再将业务数据导入 ES（索引/字段与 `fixtures/field_guide`、规则一致），即可在 Web 问答。

更细步骤见 [docs/DEPLOY.md](docs/DEPLOY.md)、[docs/TEST.md](docs/TEST.md)。

## 目录说明

| 路径 | 说明 |
|------|------|
| `apps/` | HTTP API + Web UI |
| `nl2sql_core/` | Pipeline、引擎、规则、IR（ES） |
| `configs/` | 配置模板（无密钥） |
| `deploy/` | ES docker-compose |
| `docs/` | 部署与测试 |
| `fixtures/rules` | 规则原料（方言 / 领域示例） |
| `fixtures/field_guide` | Schema 文字说明（非数据 dump） |
| `opencode_plugin/` | OpenCode Skill |
| `scripts/` | 启动与规则同步 |

## 不交付内容

- 业务/测试 JSON、ES dump、造数脚本  
- 含密钥的 `data/runtime_settings.json`  
- 内部 demo 数据源与评测结果目录  
