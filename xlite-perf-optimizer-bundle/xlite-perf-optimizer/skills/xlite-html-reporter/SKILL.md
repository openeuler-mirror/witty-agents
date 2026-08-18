# xlite-html-reporter

## 用途

读取瓶颈分析、复杂度估算、性能测试结果与原子修改记录，生成静态 HTML 报告。

## 何时使用

- 每次优化迭代完成后。
- 用户要求查看性能报告时。

## 输入

- `.xlite-opt/journal/<ts>/bottleneck_report.json`
- `.xlite-opt/journal/<ts>/complexity_report.json`
- `.xlite-opt/reports/profile-<ts>.json`
- `.xlite-opt/reports/ascend-test-<ts>.json`
- `.xlite-opt/journal/*/status.json`

## 输出

- `.xlite-opt/reports/report-<timestamp>.html`

## 执行步骤

1. **读取数据**
   - 读取瓶颈报告、复杂度报告、最新 profiling 与测试结果。
   - 读取所有 journal 目录的 `status.json`，汇总原子修改记录。

2. **填充模板**
   - 使用 `skills/xlite-html-reporter/templates/report-template.html`。
   - 替换模板中的占位符：
     - `{{TASK_GOAL}}`
     - `{{BOTTLENECK_TABLE}}`
     - `{{COMPLEXITY_CHART_DATA}}`
     - `{{PERF_BEFORE_AFTER}}`
     - `{{JOURNAL_TABLE}}`
     - `{{CONCLUSION}}`

3. **输出 HTML**
   - 将生成的 HTML 写入 `.xlite-opt/reports/report-<ts>.html`。

## 工具

- `Read`：读取模板与 JSON 数据。
- `Write`：输出最终 HTML。
- Python / Node：模板渲染（可在 skill 说明中通过 Bash 调用脚本实现）。

## 报告内容

1. 任务概述与优化目标。
2. 当前瓶颈算子表格（self 时间、占比、调用次数、单次耗时）。
3. 优化前后性能对比（wall / tpot / throughput）。
4. 时间复杂度估算（单算子 + 端到端）。
5. 原子修改记录及状态（kept / rolled_back）。
6. 关键代码片段与说明。
7. 结论与下一步建议。

## 输出示例

```text
.xlite-opt/reports/report-20260816-143052.html
```
