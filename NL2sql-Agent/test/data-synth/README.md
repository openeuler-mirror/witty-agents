# data-synth：五表造数 + 旧规则兼容视图 + 校验 + 导入 ES

## 设计（不改 NL2SQL 规则）

**五张业务基表**（各 `rows_per_table` 行）+ **一张规则兼容视图**：

| 输出 | 作用 |
|------|------|
| `resident_population` | 人员主档，**含 zz/sjlysd/ywrksj**（旧规则直接查主档） |
| `person_residence` | 住址明细（与人员 1:1） |
| `ticket_trip` | 行程 |
| `ticket_order` | 售票明细（与行程 1:1） |
| `tag_person` | 标签 |
| `ticket_sales` | **trip ⋈ order**，字段与旧 demo 一致，供现有规则使用 |

规则侧仍只用：`resident_population` / `ticket_sales` / `tag_person`。  
多出来的 `person_residence` / `ticket_trip` / `ticket_order` 满足「五表 × 同规模」需求。

另有 `query_hotspot_fraction`：按常见评测问句灌 (标签×OD)，提高非空命中率。  
酒店/飞机/大巴本身无表，仍靠规则「忽略该条件」——忽略后若有年龄/标签/城市条件，可命中。

## 用法

```bash
cd /home/zls/nl2sql/data-synth
pip install pyyaml

python3 generate.py --rows-per-table 100000
python3 validate.py
python3 import_es.py   # 默认导入全部 6 个索引（含 ticket_sales）

# 全量 2kw/基表
python3 generate.py --rows-per-table 20000000
```

只导入规则三表：

```bash
python3 import_es.py --indices resident_population,ticket_sales,tag_person
```

## 关联

- `person_residence.idcardno` = `resident_population.idcardno`
- `ticket_trip.id_no` = `resident_population.idcardno`
- `ticket_order.ticket_no` = `ticket_trip.ticket_no`
- `ticket_sales.ticket_no` = `ticket_trip.ticket_no`（合并视图）
- `tag_person.idcardno` = `resident_population.idcardno`
