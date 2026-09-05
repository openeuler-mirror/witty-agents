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
- `crash_feature_info`（含 `log_features`：相关报错 / 重复可疑日志 / 其它异常，每条标注来源文件与行号，并标注 `relevance` 相关性等级 强相关/一般相关/弱相关）
- `root_cause_analysis`（`conclusion` + `standard_solution` + `temporary_workaround` + 三部分根因：崩溃特征分析 / 崩溃链路分析 / 相关案例分析）
- `diagnosis_repair_result`（内部知识库 / 社区邮件·会议纪要·Bugzilla / 上游 commit 三组）
- `workflow_trace`

完整定义见 `schemas/crash-report-schema.json`，示例见 `sample-crash-report.json`。

独立 HTML（`crash-report.html`）将报告呈现为七个章节：执行摘要 → 崩溃详情（含日志特征）→ 事件时序图（对象泳道 + 全局变量列）→ 根因分析（三部分）→ 知识库匹配（三组）→ 诊断工作流追踪。

## `diagnosis_repair_result` 的填写规则

- `internal_kernel_result` 必须是 `crash-feature-matcher:query_knowledge` / `query_cases` 返回的原生 JSON 数组的**逐字节**复制。
- `community_kernel_result` 必须是 `crash-feature-matcher:query_community_cases` 返回的原生 JSON 数组的**逐字节**复制。
- **不得**重命名字段、改写值、重新总结、归一化数值、转换类型或删除字段。
- **未命中即留空，禁止幻想**：内部案例 / 社区邮件 / 会议纪要 / Bugzilla / 上游 commit 每个分类只有工具真实返回匹配时才填，未检索到就写空数组 `[]`，不得编造标题、url、snippet、verdict、evidence 等任何内容（空分类显示「未检索到…」属正常）。
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
6. **根因验证** — 在核验调用栈完整性、模块一致性、源码映射后生成 `root_cause_analysis.json`；若不完整则再跑一轮。该节应由 **LLM 综合所有证据总结**，产出与 report.html 第 1/3/4 章一致的字段：
   - **`conclusion`**（一句自然中文，叙事化、通俗、书面、少术语）：用「发生了什么 → 为什么 → 结论（与业务/硬件是否有关）」讲清场景、缺陷大类与结论（推测 or 确认）。**禁止**函数名/寄存器/标志常量/十六进制/地址等实现细节；社区 `verdict=confirmed` 时去掉"推测"、以"（社区补丁已确认）"收尾，否则以"（推测）"结尾。
   - **`standard_solution`**（结构化对象）：`type`（patch/config/upgrade/none 四选一）/ `claim_tag` / `short`（**必须分「要做什么·为什么·怎么做」三句**，通俗、书面、少术语，不用函数名/寄存器/十六进制）/ `basis`（修复依据）/ `fixed_in`（版本判定）/ `patch_list`（补丁 diff）/ `method_steps`（合入步骤）/ `detail`（完整说明）/ `rollback`（回退方案，**必填**：补丁/配置失败或回归时的回退步骤与还原命令）/ `verification`（验证方案，**必填**：编译无告警、压力回归、观察 dmesg 无新 Oops、监控同类 panic 建簇等）。`patch_list[].mode` 三选一：`full`/`part`/`pick`；`patch_list[].diff` **必须给可直接合入的具体补丁示例（diff 格式，含 +/- 行），禁止留空**；`type=patch` 时必须至少一条 `patch_list`。
   - **`temporary_workaround`**（结构化对象）：`type`（config=命令行/配置规避、none=无方案）/ `summary` / `steps` / `risk` / `detail`。无有效方案时 `type=none`、`summary` 写「无」；有方案时 `steps` 优先给 shell 命令、改内核/服务配置、换机/分散部署等可落地手段。
   - **`event_scene`**（事件时序图，三类泳道：进程/内核/硬件，**每类可有多个对象**）：`participants`（`id` 简短英文如 proc_a/cpu92/timer0、`name` 具体到进程名+PID/CPU 序号/硬件类型、`type` 三选一 process/kernel/hardware、`init`、`tip` 供 hover 展示 PID/名称/内核序号/硬件类型）/ `gvars`+`ginit`（全局变量列 k/v）/ `anchor`（**ISO 8601 带毫秒**，如 `2026-07-08T06:20:00.000`，禁止写非时间字符串）/ `events`（每条 `m` 四选一 user/sys/kern/hw 区分用户态·内核态·硬件、`from`/`to` 用 participant id 表示泳道箭头、指向自身时 from=to 查看器画弯折回环箭头、`kind` 枚举 call/irq/softirq/hw/mutex/alloc/race/free/global/crash、`dt_ms` 相对 anchor 递增且不全 0、`t` 阶段标签非单调秒数、`val`/`full` 供 hover）。
   - **`propagation_chain`**（崩溃链路逐跳）：每跳给 栈帧↔源码（`src_dir`/`file`/`line`/`fn_ctx`/`stack`）、关键参数 `params`（`io`/`reg`/`formal`/`v`/`bad`，异常参数标红）、`detail`/`evidence`；**每一跳都应给出 `source_url`**（在线源码/commit/patch 链接）便于跳转对照；最后一跳写明二进制↔源码行对照。
   - **`reasoning_flow`**（三部分根因）：`stage` 用枚举 `stack`/`hypothesis`（①崩溃特征分析，两步都要有）、`path_analysis`（②崩溃链路分析，`path_mini` 填完整传播链数组）、`internal`/`community`/`commit`/`source_compare`/`conclusion`（③相关案例分析，**执行了对应检索就必须有对应 stage，未命中也要保留该 stage 并如实写「未检索到…」，最后以 `conclusion` 收尾**）；每步 `refs` 用 `anchor`（kb-internal/kb-mail/kb-meeting/kb-bugzilla/kb-commit）跳转到第 5 章对应案例卡。
   - **`deep`**（根因结论详细）：`lead` / `mechanism` / `evidence` / `confidence` / `scope`。
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
