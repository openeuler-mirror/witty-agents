---
name: crash-report-generator
description: |
  生成符合统一 JSON Schema 的内核宕机诊断报告。覆盖 host 基线、崩溃特征提取、
  日志异常检测、社区/内部案例检索、根因验证和完整的工作流追踪。tools: [Bash, Read, Write]
allowed-tools: Bash(python3:*) Bash(pip:*) Bash(cat:*) Bash(ls:*) Bash(rg:*) Bash(sed:*)
---

# crash-report-generator

本技能定义了内核宕机诊断报告的规范 JSON Schema 与生成提示词。当收到崩溃相关输入时，最终产物必须是符合 `schemas/crash-report-schema.json` 的单个 JSON 对象。

## 输出格式要求

最终报告必须是一个 JSON 对象，包含以下顶层章节：

- `report_id`
- `parse_log_range`
- `host_base_info`
- `crash_feature_info`（含 `log_features`：相关报错 / 重复可疑日志 / 其它异常，每条标注来源文件与行号）
- `root_cause_analysis`（`conclusion` + `standard_solution` + `temporary_workaround` + 三部分根因：崩溃特征分析 / 崩溃链路分析 / 相关案例分析）
- `diagnosis_repair_result`（内部知识库 / 社区邮件·会议纪要·Bugzilla / 上游 commit 三组）
- `workflow_trace`

完整定义见 `schemas/crash-report-schema.json`，示例见 `sample-crash-report.json`。

独立 HTML（`crash-report.html`）将报告呈现为七个章节：执行摘要 → 崩溃详情（含日志特征）→ 事件时序图（对象泳道 + 全局变量列）→ 根因分析（三部分）→ 知识库匹配（三组）→ 诊断工作流追踪。

## `diagnosis_repair_result` 的填写规则

- `internal_kernel_result` 必须是 `crash-feature-matcher:query_knowledge` / `query_cases` 返回的原生 JSON 数组的**逐字节**复制。
- `community_kernel_result` 必须是 `crash-feature-matcher:query_community_cases` 返回的原生 JSON 数组的**逐字节**复制。
- **不得**重命名字段、改写值、重新总结、归一化数值、转换类型或删除字段。
- 其余顶层对象仍须满足 `additionalProperties: false`。

## 社区案例检索（双通道）

社区案例有两种获取方式，可互为兜底，结果需合并去重：

1. **rag_core 语义检索**：`crash-feature-matcher:query_community_cases`（依赖 RAG 配置），返回 L1/L2/L3 社区案例与一手 evidence / verdict。
2. **本地源文件综合检索（grep + find）**：社区邮件、会议纪要、上游 commit 在本机保留一份本地副本（`$SHENNONG_COMMUNITY_DIR`，默认 `/data/shennong/community/`，子目录 `mails/`、`meetings/`、`commits/`）。当 RAG 未配置或无高置信命中时，用 `find` 定位相关文件、再以 `rg`/`grep` 按 `rip_function`、`bug_key`、调用栈顶层函数、模块名、内核版本等关键词综合检索，摘取「关键片段 + 原文网址 + commit 号」作为社区案例，**从中挑选最符合的 Top 3-4 条**进入报告。

无论走哪条通道，每条社区案例 / 上游 commit 在报告里都需附：**原文网址（url）、关联 commit、关键片段（解释 + 原文）**。

## 生成工作流（分片增量式）

报告应逐节增量生成，每节保存到本地临时目录，逐节校验通过后再合并。

1. **创建临时目录**（如 `/tmp/shennong_report_YYYYMMDD_HHMMSS`）。
2. **主机基线** — 用 `bash`/`crash` 工具或直接取 `analyze_crash` 的 `host_features` 生成 `host_base_info.json`：主机名、内核版本、CPU 型号、机型、CPU 核数（未知填 `0`）、内存大小（把 MB 换算成人类可读字符串，如 `"64GB"` 或 `"{MB}MB"`）、已加载模块。该节应由**脚本/工具生成**，不得由 LLM 改写。
3. **崩溃特征提取** — 用 `crash-feature-matcher` MCP 工具（`analyze_crash`、`query_knowledge`、`query_cases`）生成 `crash_feature_info.json`。若 `crash_time` 不是合法 ISO 8601 时间戳，则从日志推导或填 `"unknown"`，不得留空。该节应由**脚本/工具生成**，不得由 LLM 改写。
4. **日志异常检测** — 用 `witty-log-detection` MCP 工具（`create_log_parse_task`、`get_task_result`）补充证据。
5. **社区案例检索** — 用 `crash-feature-matcher:query_community_cases` 生成 `diagnosis_repair_result.json`。内部与社区案例须与原 JSON 逐字节一致，**仅** `match_score` 例外：转换成匹配等级 高/中/低（`match_score`(0-1)：高≥0.7 / 中0.4-0.69 / 低<0.4）。该节应由**脚本/工具生成**，不得由 LLM 改写。
6. **根因验证** — 在核验调用栈完整性、模块一致性、源码映射后生成 `root_cause_analysis.json`；若不完整则再跑一轮。该节应由 **LLM 综合所有证据总结**，产出以下字段：
   - **`conclusion`**（一句自然中文，高度抽象）：概括场景、缺陷大类与结论（是推测还是真实缺陷、还是预期动作）。**剔除**所有实现细节：不出现函数名、寄存器名、标志常量、机制内部细节（如"exception table"、"single-step"、"fixup"、"NMI"、"GRO"），不出现具体地址/偏移/路径。示例：
     - 简单（sysrq）："当前主机发生内核 panic，通过日志及调用栈表明，该故障由人工通过 sysrq 手动触发，并非内核缺陷。"
     - 复杂："当前主机在高网络负载下发生内核崩溃，通过调用栈定位到网卡驱动收包路径，存在内存释放后重用的并发竞态（推测）。"
   - **`analysis`**（有序数组，可选；简单问题留空 `[]`）：复杂问题给出**推理链**（3–7 步），模仿人类分析师的思路，而非一坨文字或一堆孤立事实。每一步 `{ stage, fact, evidence?, detail }` 是推理的一个环节：`stage`（必填，枚举）标注分析阶段并驱动 HTML 叙事分组，顺序为：`phenomenon`（崩溃表象：panic 日志/RIP/**调用栈**，栈是第一份证据）→ `log_location`（关键日志片段、异常首现点、dmesg 窗口）→ `source_analysis`（定位处对应源码逻辑）→ `propagation`（事件序列与污染扩散链：谁污染了谁）→ `root_cause`（缺陷本质机制）→ `kb_corroboration`（内部知识库命中 + 社区 verdict + 邮件讨论佐证）→ `fix_verification`（是否已修复的版本判定 + 修复方法）。同阶段可有多步；阶段仅在确实不适用时才跳过。`fact` 是本步证明的中间结论（是论断而非观察）；`evidence`（可选）是原始支撑数据——关键调用栈帧（3–6 帧，一行一帧）、寄存器值、dmesg 行、反汇编、结构体字段、源码行、diff 片段，用等宽字体、以换行分隔；`detail` 是推理本身（"因为看到 <evidence>，推出 <fact>，进而检查 <下一步焦点>"）。每一步回答上一步提出的问题。所有机制细节/函数名/寄存器值都放这里——不要放进 `conclusion`。
   - **`solution`**（始终必填）：简单问题——一句处置说明；复杂问题——按证据强度分层：(a) 内部/社区命中 → 采用案例的 solution；(b) git 技能查到 commit/issue → 给出参考修复并标注"参考社区 commit xxx"；(c) 都无 → 给规避建议（临时缓解、待收集信息、下一步方向），不臆造修复代码。
   完整规则与示例见 `prompts/generate-report.md`。
7. **工作流追踪** — 基于**真实会话数据**生成 `workflow_trace.json`：
   a. 运行 `scripts/extract_workflow.py` 提取当前 opencode 会话的执行时间线（用 `opencode export <sessionID>` 获取真实工具调用、时间戳、耗时、状态与 agent 的推理链）。
   b. 读取提取出的 `timeline.json`，把连续相关的轮次聚合成 **5–8 个关键决策步骤**（不是每轮一步，也不是一个大杂烩阶段）。每步填写：`stage`（init/baseline_collection/crash_feature_extraction/log_detection/knowledge_retrieval/root_cause_validation/report_generation）、`decision`（决定了什么及为什么，从推理中提炼）、`observations`（工具输出的关键发现）、`judgment`（可选：由观察得出的结论及如何引向下一步）、`tools`（从时间线逐字复制真实工具条目——名称、标题、状态、耗时、起止时间戳；**不得编造工具、状态或时间戳**）、`status`（success/failed/partial/skipped）、`reason`（仅失败时）、`start_time`/`end_time`（取组内最早/最晚工具的时间）。
   c. 顶层字段：`source="opencode_export"`、`session_id`、`total_duration_ms`、`step_count`（=步骤数）、`steps[]`。
   d. **兜底**：若提取脚本失败（如 opencode CLI 不可用），设 `source="manual"` 并沿用同样的步骤结构，但在 `reason` 中注明时间戳/工具是近似值。
   e. 诚实规则：`steps[].tools` 中列出的每个工具必须真实存在于时间线且状态一致；时间戳必须来自导出；工具失败则把步骤标为 `failed`/`partial` 并在 `reason` 中解释。
8. **逐节校验** — 合并前先对每节对照 `schemas/crash-report-schema.json` 校验，发现错误先修正。
9. **合并分片** — 用 `scripts/combine_report.py` 组装最终报告：

   ```bash
   bash skills/crash-report-generator/run_python.sh skills/crash-report-generator/scripts/combine_report.py \
       --sections-dir /tmp/shennong_report_YYYYMMDD_HHMMSS \
       --output report.json \
       --validate
   ```

10. **最终 schema 校验** — 对合并后的报告运行 `validate_report.py`；失败则修正对应分片并重新合并。
11. **生成独立 HTML 报告** — 运行 `scripts/generate_report_html.py` 产出内联 `report.json` 的自包含 `crash-report.html`（无需本地 HTTP 服务，可直接 file:// 打开）：

    ```bash
    bash skills/crash-report-generator/run_python.sh skills/crash-report-generator/scripts/generate_report_html.py \
        --report report.json \
        --output crash-report.html
    ```

## 校验命令

强烈推荐使用本技能提供的校验脚本做强校验：

```bash
# 校验单个报告文件
bash skills/crash-report-generator/run_python.sh skills/crash-report-generator/scripts/validate_report.py --report report.json

# 若希望把校验通过后的报告另存为文件
bash skills/crash-report-generator/run_python.sh skills/crash-report-generator/scripts/validate_report.py --report report.json --output validated-report.json

# 仅校验，不执行语义检查（仅校验 JSON schema）
bash skills/crash-report-generator/run_python.sh skills/crash-report-generator/scripts/validate_report.py --report report.json --no-semantics

# 合并分片并校验
bash skills/crash-report-generator/run_python.sh skills/crash-report-generator/scripts/combine_report.py \
    --sections-dir /tmp/shennong_report_YYYYMMDD_HHMMSS \
    --output report.json \
    --validate
```

脚本会：

1. 使用 `jsonschema` 对报告进行 JSON Schema 强校验；
2. 进行语义检查：
   - `workflow_trace.step_count` 与 `steps` 数组长度一致，`source` 必须是 `opencode_export` 或 `manual`；
   - `report_id` 符合 `HOSTNAME-YYYYMMDD-YYYYMMDD` 格式；
   - `parse_log_range` 非空；
   - `diagnosis_repair_result` 两个数组字段存在；
   - `crash_feature_info` 核心字段非空。
3. 校验失败时打印详细错误并返回非零退出码；成功时输出 `OK`。

如果尚未创建 crash-report-generator 的 venv，请先显式运行 Python 依赖安装命令：

```bash
npm exec --offline -- shennong-setup install
```

## 规则

- 只返回 JSON 对象；除非明确要求，否则不要用 markdown 包裹。
- 所有时间戳必须为带时区的 ISO 8601。
- `match_score` 必须是 0 到 1 之间的浮点数。
- 不得添加 schema 未定义的字段。
- 若某必填字段无法填写，仅允许在 schema 允许的位置用 `null`；否则把该阶段标为 `insufficient` 并在 `reason` 中说明。
