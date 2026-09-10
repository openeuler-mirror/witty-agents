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
| Node.js | ≥ 18（仅用于 `nl2sql` CLI / npm） |
| Python | ≥ 3.10（`python3 -m venv` / pip） |
| 业务库 | 按源准备：ES 7.x（默认 `9200`）等 |
| rag-core | 已部署的 HTTP 服务（默认 `19988`） |
| LLM | OpenAI 兼容 API |

## 推荐安装（npm tgz）

```bash
# 拿到 nl2sql-0.1.0.tgz 后
npm install -g ./nl2sql-0.1.0.tgz

nl2sql init    # 交互配置 LLM / rag-core / ES / Web 端口
nl2sql start   # 建 .venv、装依赖、起 Web

# 浏览器 http://127.0.0.1:8199
```

`init` / `start` 默认作用在本包安装根目录；也可用 `nl2sql init --dir /path/to/tree`。

规则需自行同步到 rag（Web「规则中心」或 `scripts/sync_rules_to_rag.py`）。部署细节见 [docs/DEPLOY.md](docs/DEPLOY.md)，测试见 [docs/TEST.md](docs/TEST.md)。

## 进阶：源码目录直接启动

```bash
cp .env.example .env   # 或 nl2sql init --dir .
./scripts/start_web.sh
# 或完整脚本 ./scripts/start_all.sh（可选拉起本机中间件）
```

## 目录说明

| 路径 | 说明 |
|------|------|
| `bin/nl2sql.js` | CLI：`init` / `start` |
| `apps/` | HTTP API + Web UI |
| `nl2sql_core/` | Pipeline、多引擎、规则、IR（ES） |
| `configs/` | 配置模板（无密钥） |
| `docs/` | 部署与测试 |
| `fixtures/` | 规则原料 / 字段说明 |
| `scripts/` | 启动、规则同步、冷启动 |

## 不交付内容

- 业务/测试 JSON、ES dump、内部评测结果  
- 含密钥的 `.env`、`data/runtime_settings.json`  
- OpenCode 插件、打包产物 `*.tgz`、测试造数目录  
