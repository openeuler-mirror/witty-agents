# NL2SQL Agent

自然语言 →（可选澄清）→ 召回 rag-core 规则 → 生成只读查询 → 在**当前数据源**执行。

| 数据源 type | 生成物 | 执行 |
|-------------|--------|------|
| `elasticsearch` | IR（多步半连接） | ES |
| `opengauss` | SQL | OpenGauss（PG 协议，只读 SELECT） |
| `hbase` | JSON scan 计划 | 原生 HBase REST（非 Phoenix） |

一次只连**当前选中**的那一个库。业务数据与 API Key **不在本仓库**。

功能/一致性怎么测，见 **[docs/TEST.md](docs/TEST.md)**（测试同学从这篇开始）。部署见 [docs/DEPLOY.md](docs/DEPLOY.md)。

## 环境要求

| 组件 | 说明 |
|------|------|
| Python | 3.10+ |
| 业务库 | 按要测的源准备：ES 7.x（默认 `9200`）、和/或 OpenGauss、和/或 HBase REST |
| rag-core | 已部署的 HTTP 服务（默认 `19988`）；无则 Web 能起，但无法问答 |
| LLM | OpenAI 兼容 API（填进 `.env`） |
| Java 11+ | 仅当用本仓库脚本拉起本机 HBase 时需要 |

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

curl -s http://127.0.0.1:19988/health_check

./scripts/start_all.sh
# 已有 ES：  SKIP_ES=1 ./scripts/start_all.sh
# 暂无 rag： SKIP_RAG=1 ./scripts/start_all.sh

# 浏览器 http://127.0.0.1:8199
# 下拉框选一个数据源 →「测试当前数据源」→ 再问答 / 一致性
```

按当前源同步规则（首次必做，**换源要换 `--database-id`**）：

```bash
cd witty-agents/NL2sql-Agent
source .venv/bin/activate
export PYTHONPATH=.
python3 scripts/sync_rules_to_rag.py --database-id local-es
# 或 OpenGauss / HBase：
# python3 scripts/sync_rules_to_rag.py --database-id local-opengauss
# python3 scripts/sync_rules_to_rag.py --database-id local-hbase
```

现场只有库、没有规则时，用冷启动（预览 JSON → 确认后再入库）：

```bash
PYTHONPATH=. python3 scripts/init_rules_from_db.py --database-id local-es
PYTHONPATH=. python3 scripts/init_rules_from_db.py --commit --from-file data/rules/init_bundles/init_local-es_xxx.json
```

## 目录说明

| 路径 | 说明 |
|------|------|
| `apps/` | HTTP API + Web UI |
| `nl2sql_core/` | Pipeline、多引擎、规则、IR（ES） |
| `configs/` | 配置模板（无密钥；`datasources.yaml` 里填连接） |
| `deploy/` | ES docker-compose |
| `docs/` | 部署与测试 |
| `fixtures/rules` | 规则原料（方言 / 领域示例） |
| `fixtures/field_guide` | Schema 文字说明（非数据 dump） |
| `opencode_plugin/` | OpenCode Skill |
| `scripts/` | 启动、规则同步、冷启动、本机 OG/HBase |
| `test/` | 造数与 demo 问句（不含大 JSON） |

## 不交付内容

- 业务/测试 JSON、ES dump  
- 含密钥的 `.env`、`data/runtime_settings.json`  
- 内部评测结果目录  
