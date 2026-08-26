# KG 模块占位说明

本期 **不实现** 知识图谱验证（避免名不副实）。

预留入口：`nl2sql_core.kg.verify(result, rules) -> dict`

后续若启用：
1. 将 `configs/app.yaml` 中 `kg.enabled` 设为 `true`
2. 在本目录实现 build / verify / serialize
3. 增加 Web `/api/kg` 与前端 Tab
