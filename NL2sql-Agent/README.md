# NL2SQL Agent

自然语言 →（可选澄清）→ 召回 rag-core 规则 → 生成只读 SQL/DSL → 在 Elasticsearch 执行。

## 文档

- [部署指南](docs/DEPLOY.md)（含一键启动）
- [测试指南](docs/TEST.md)（规则 / 数据 / 一致性）

## 快速开始

```bash
chmod +x scripts/*.sh
./scripts/start_all.sh
# 浏览器 http://127.0.0.1:8199
```

首次请填写 `.env` 中的 LLM Key，并按测试指南同步规则、导入业务数据。

## 目录说明

| 路径 | 说明 |
|------|------|
| `apps/` | HTTP API + Web UI |
| `nl2sql_core/` | 核心 Pipeline |
| `configs/` | 配置模板（无密钥） |
| `deploy/` | ES docker-compose |
| `docs/` | 部署与测试文档 |
| `fixtures/rules` | 规则原料 |
| `fixtures/field_guide` | Schema 说明 |
| `opencode_plugin/` | OpenCode Skill |
| `scripts/` | 启动与规则同步 |
| `DESIGN.md` 等 | 历史设计/产物（请保留） |
