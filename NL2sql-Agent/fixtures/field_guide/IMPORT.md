# ES 数据导入指南

## 数据内容

7 个索引，每个索引 3 个文件：

| 文件 | 内容 |
|------|------|
| *.settings.json | 索引设置（分片、副本、分析器）|
| *.mapping.json | 字段映射（字段类型定义）|
| *.data.json.gz | 数据（NDJSON 格式，每行一条文档）|

索引清单：

| 索引 | 说明 | 文档数 |
|------|------|--------|
| person_info_es | 人员主索引 | ~102万 |
| ticket_record_es_2026 | 购票记录 | ~109万 |
| checkin_record_es_2026 | 进站记录 | ~142万 |
| return_record_es_2026 | 退票记录 | ~1万 |
| resign_record_es_2026 | 改签记录 | ~31万 |
| crew_record_es_2026 | 运货记录 | ~100万 |
| zdry_info_es | 重点人员标签 | ~46万 |

## 前提条件

- Elasticsearch 7.x（推荐 7.17）
- 每索引的数据文件为 gzip 压缩，需先解压

## 导入步骤

### 1. 解压数据

```bash
gzip -d *.data.json.gz
```

### 2. 创建索引（含 settings + mapping）

```bash
# 以 person_info_es 为例，其他索引同理
curl -X PUT 'http://localhost:9200/person_info_es' -H 'Content-Type: application/json'   --data-binary @person_info_es.settings.json

# settings.json 包含索引名包裹，需提取。推荐用 python:
python3 -c '
import json
s = json.load(open(person_info_es.settings.json))
idx = list(s.keys())[0]
print(json.dumps(s[idx][settings]))
' > settings_body.json

curl -X PUT 'http://localhost:9200/person_info_es' -H 'Content-Type: application/json'   --data-binary @settings_body.json

curl -X PUT 'http://localhost:9200/person_info_es/_mapping' -H 'Content-Type: application/json'   --data-binary @person_info_es.mapping.json
```

### 3. 灌入数据（bulk API，推荐分块）

```bash
# NDJSON 需转为 bulk 格式（加一行 index 元数据）或用 elasticdump
# 方式一：elasticdump（推荐）
npm install -g elasticdump
elasticdump --input=person_info_es.data.json --output=http://localhost:9200/person_info_es --type=data --limit=10000

# 方式二：curl bulk（每行前加 index 元数据）
python3 -c '
import json
with open(person_info_es.data.json, r, encoding=utf-8) as f,      open(person_info_es.bulk.json, w, encoding=utf-8) as out:
    for line in f:
        d = json.loads(line)
        out.write(json.dumps({index: {_index: person_info_es, _id: d.pop(_id)}}) + n)
        out.write(json.dumps(d, ensure_ascii=False) + n)
'
# 分块提交（每 5000 条）
split -l 10000 person_info_es.bulk.json chunk_
for f in chunk_*; do
  curl -s -X POST 'http://localhost:9200/_bulk' -H 'Content-Type: application/json' --data-binary @
done
```

### 4. 验证

```bash
curl 'http://localhost:9200/_cat/indices?v'
# 期望 doc count 与上面表格一致
```

## 常见问题

- settings.json 里的分片数建议按客户集群规模调整（生产可保持原样）
- 数据文件含 _id 字段，导入时作为文档 ID，可保证幂等
- 若 ES 版本 < 7，字段类型可能不兼容（如 date_nanos），需调整 mapping
