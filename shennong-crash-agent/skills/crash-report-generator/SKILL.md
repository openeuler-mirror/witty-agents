---
name: crash-report-generator
description: |
  生成符合统一 JSON Schema 的内核宕机诊断报告。覆盖 host 基线、崩溃特征提取、
  日志异常检测、社区/内部案例检索、根因验证和完整的工作流追踪。tools: [Bash, Read, Write]
allowed-tools: Bash(python3:*) Bash(pip:*) Bash(cat:*) Bash(ls:*) Bash(rg:*) Bash(sed:*)
---

# crash-report-generator

This skill defines the canonical JSON schema and generation prompt for kernel crash analysis reports. When crash-related inputs are provided, the final answer must be a single JSON object matching `schemas/crash-report-schema.json`.

## Required Output Format

The final report must be a single JSON object with these top-level sections:

- `report_id`
- `parse_log_range`
- `host_base_info`
- `crash_feature_info`
- `root_cause_analysis`
- `diagnosis_repair_result`
- `workflow_trace`

See the full schema in `schemas/crash-report-schema.json` and an example in `sample-crash-report.json`.

## Rules for `diagnosis_repair_result`

- `internal_kernel_result` is the **byte-for-byte** native JSON array returned by `crash-feature-matcher:query_knowledge` / `query_cases`.
- `community_kernel_result` is the **byte-for-byte** native JSON array returned by `crash-feature-matcher:query_community_cases`.
- Do **not** rename fields, rewrite values, summarize, normalize numbers, convert types, or drop fields.
- Other top-level objects must still conform to `additionalProperties: false`.

## Generation Workflow (Incremental)

The report should be built incrementally, section by section, saved to a local temporary directory, and only combined after each section is validated.

1. **Create a temporary directory** (e.g., `/tmp/shennong_report_YYYYMMDD_HHMMSS`).
2. **Host baseline** — generate `host_base_info.json` using `bash`/`crash` tools or directly from `analyze_crash` `host_features`: hostname, kernel version, CPU model, machine model, CPU count (use `0` if unknown), memory size (convert MB to a human-readable string such as `"64GB"` or `"{MB}MB"`), loaded modules. This section should be **script/tool generated**, not rewritten by the LLM.
3. **Crash feature extraction** — generate `crash_feature_info.json` using `crash-feature-matcher` MCP tools (`analyze_crash`, `query_knowledge`, `query_cases`). If `crash_time` is not a valid ISO 8601 timestamp, derive it from the log or use `"unknown"`; do not leave it empty. This section should be **script/tool generated**, not rewritten by the LLM.
4. **Log anomaly detection** — use `witty-log-detection` MCP tools (`create_log_parse_task`, `get_task_result`) for supplementary evidence.
5. **Community case retrieval** — generate `diagnosis_repair_result.json` using `crash-feature-matcher:query_community_cases`. Keep internal and community cases byte-for-byte identical to the original JSON. This section should be **script/tool generated**, not rewritten by the LLM.
6. **Root cause validation** — generate `root_cause_analysis.json` after verifying call trace completeness, module consistency, and source-code mapping. If incomplete, run a second round. This section should be **LLM summarization** based on all collected evidence.
7. **Workflow trace** — generate `workflow_trace.json` recording every agent round, tool call, input, output, and timestamps. This section should be **LLM summarization** based on the actual execution trace, but tool inputs/outputs must be faithful.
8. **Section validation** — validate each section against `schemas/crash-report-schema.json` before combining. Fix any errors before proceeding.
9. **Combine sections** — use `scripts/combine_report.py` to assemble the final report:

   ```bash
   .venvs/crash-report-generator/bin/python skills/crash-report-generator/scripts/combine_report.py \
       --sections-dir /tmp/shennong_report_YYYYMMDD_HHMMSS \
       --output report.json \
       --validate
   ```

10. **Final schema validation** — run `validate_report.py` on the combined report. If it fails, fix the offending section and re-combine.

## Validation Commands

强烈推荐使用本 Skill 提供的校验脚本进行强校验：

```bash
# 校验单个报告文件
.venvs/crash-report-generator/bin/python skills/crash-report-generator/scripts/validate_report.py --report report.json

# 若希望把校验通过后的报告另存为文件
.venvs/crash-report-generator/bin/python skills/crash-report-generator/scripts/validate_report.py --report report.json --output validated-report.json

# 仅校验，不执行语义检查（仅校验 JSON schema）
.venvs/crash-report-generator/bin/python skills/crash-report-generator/scripts/validate_report.py --report report.json --no-semantics

# 合并分片并校验
.venvs/crash-report-generator/bin/python skills/crash-report-generator/scripts/combine_report.py \
    --sections-dir /tmp/shennong_report_YYYYMMDD_HHMMSS \
    --output report.json \
    --validate
```

脚本会：

1. 使用 `jsonschema` 对报告进行 JSON Schema 强校验；
2. 进行语义检查：
   - `workflow_trace.round_count` 与 `round_history` 长度一致；
   - `report_id` 符合 `HOSTNAME-YYYYMMDD-YYYYMMDD` 格式；
   - `parse_log_range` 非空；
   - `diagnosis_repair_result` 两个数组字段存在；
   - `crash_feature_info` 核心字段非空。
3. 校验失败时打印详细错误并返回非零退出码；成功时输出 `OK`。

如果尚未创建 crash-report-generator 的 venv，请先运行项目根目录的 `postinstall.mjs`：

```bash
node postinstall.mjs
```

## Rules

- Return only the JSON object; do not wrap it in markdown unless asked.
- All timestamps must be ISO 8601 with timezone.
- `match_score` values must be floats between 0 and 1.
- Do not add fields not defined in the schema.
- If any required field cannot be filled, use `null` only where the schema permits it; otherwise mark the stage as `insufficient` and explain in `reason`.
