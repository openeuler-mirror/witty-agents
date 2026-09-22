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

独立 HTML（`crash-report.html`）将报告呈现为五个章节：故障总览 → 宕机特征 → 故障机制（事件时序图）→ 判断依据 → 技术附件。判断依据章节按 `deep.evidence[]` 逐条渲染，每条核心依据必须携带独立的 `reasoning[]` 推理链；不再把多条依据合并成一个页面级总推理链。

### HTML 渲染层约定

`templates/crash-report-viewer.html` 负责把 JSON 渲染为自包含 HTML，以下行为由模板层保证：

1. **正文链接指向技术附件**：故障总览、宕机特征、故障机制、判断依据等正文区域出现的 commit / URL，若命中 `diagnosis_repair_result` 中的案例条目，则渲染为当前 HTML 内部锚点 `#case-{group}-{index}`；点击后自动展开技术附件的多层折叠并高亮目标卡片。未命中索引的 commit / URL 保持纯文本，正文区域不生成外部跳转链接。
2. **技术附件保留外链**：案例卡片内的「查看原始资料」等链接仍指向外部一手资料。
3. **案例按「是否支撑推荐修复方案」分层展示**：
   - **修复依据**：`verdict === 'confirmed'` 的案例，**以及被 `standard_solution.basis` / `patch_list` 明确引用的案例**（按 url/sha 匹配；即使 verdict 为 `same_area`，只要被方案引用就升格到此组），默认展开。被引用但非 confirmed 的案例标注「方案引用」徽标，其论证区标题改为「与推荐方案的关系」，并在有 diff 时展示补丁摘录。
   - **其他案例**：其余 `same_area` / `not_relevant` / `unverified` 案例默认折叠，仅作为诊断旁证。
   - 该规则保证第 1 章「规避手段 · 修复依据」引用的案例一定出现在技术附件「修复依据」组中，两处不再脱节。
4. **历史案例格只取内部案例库**：第 1 章「故障总览」的「历史案例」格仅依据 `diagnosis_repair_result.internal_kernel_result`；无命中时显示「未匹配到内部案例」。社区 issue/commit/bugzilla/邮件/会议只出现在技术附件与修复依据组，不进入本格。**禁止读取/引用既往诊断报告**（输出目录、现场目录中的 `report_*.json` / `crash-report_*.html` 一律忽略，最多在 workflow_trace 记为「已忽略」）。
5. **宕机特征章只留崩溃直接事实**：「宕机现场」章依次为「现场初印象」→「原始崩溃日志」（正文主卡）→「其他异常信息」；异常类型/故障地址/崩溃位置/现场进程统一收在技术附件「主机与运行环境」卡（附件第一卡），「宕机栈」也在其后（默认收起）。重复可疑日志、其它异常等背景信号另收在技术附件「日志特征明细」（三类全量 + 相关性徽标 + 逐行 desc），避免低参考价值内容干扰主线阅读。
6. **原始崩溃日志：关键行高亮 + 行尾注释**：「宕机特征」章的「原始崩溃日志」优先渲染 `crash_feature_info.raw_crash_log`（完整连续崩溃段，**默认收起、展开后限高滚动**）；无则退化为 `related_errors[].line` 按行号拼装摘录；两者都没有才展示「崩溃调用栈」（`call_trace_text`，不冒充原始日志）。渲染样式与第 4 章现场日志一致：只对关键行（崩溃首行/BUG、故障地址、RIP/pc/lr、Call Trace、`<IRQ>`/`</IRQ>`、Code、panic）做**琥珀高亮 + 行尾 `◀` 注释**，注释优先取 `raw_crash_log_ann`，缺失时模板按行类型自动兜底；**注释只做初步定位**（约 15~40 字：这行是什么 + 为何值得看），因果机制与数值来由留给第 4 章、不得与第 4 章注释重复（规范见 generate-report.md）；卡片不显示「现场日志」徽标与提示行；**无注释行保持素色，仅带 `◀` 注释的行着色（琥珀底 + 类别色左条）**；图例只列「有注释行的类别」，顺序按各类别在日志中**首次出现**的顺序，点击可跳转到该类别第一条注释行；不恢复悬浮解读。
7. **判断依据为连续追问链（索引 + 步骤卡）**：第 4 章「为什么得出这个结论」顶部为 `1./2./3.` 索引导航（标签取 `deep.evidence[].short`，缺失回退标题截断，点击锚点跳转）；每条依据是一张折叠步骤卡：摘要行 = 序号 + 设问标题 + **结论预览条**（展开后隐藏）；展开体依次为 `现场证据`（每个证据步一张卡，卡摘要 = 步骤名 + 一句话含义）→ `由此推导`（推导步 detail）→ `结论`（summary + 彩色证据级别徽标）；链间用 `connect` 渲染为箭头过渡条（上一条结论 → 引出下一条要回答的问题）。未决/不确定信息并入结论末尾一句，不单列「证据边界」块。
8. **案例卡片字段零丢失**：卡片按分支渲染 `how`/`fix_scope`/`files`/`diff`/`excerpt`/`corroboration` 等字段（commit 类案例的 meta 附短 sha，非 confirmed commit 同样渲染涉及文件、diff 摘录与原文摘录折叠区）；「查看其余字段（未在上方展示）」采用**动态追踪**——只收纳实际未渲染的字段（已渲染的不重复出现），任何字段都不会既不在卡片正文、也不在其余字段中静默丢失。
9. **证据链要求「数值/偏移必有来由」**：第 4 章 `deep.evidence[].reasoning[]` 的 `detail`（通俗因果层）必须讲清其中偏移/地址/寄存器值「为什么是这个值」（如 `#64` 是 `on_rq` 字段在结构体里的字节偏移），`evidence`（专业出处层）给出实证来源（如 crash `struct -o`、反汇编对照）；模板原样渲染这两层，报告生成时不得只报数值而不说明来源（规范见 `prompts/generate-report.md` 写作铁律第 11 条）。同时遵守**内容顺读五铁律**（对象先解释 / 环间复述 / 推导列前提 / 术语编号一致 / 量化有据，见 `prompts/generate-report.md` 的 `deep.evidence` 规范），并做单环自洽 + 全链通读自检。
10. **现场初印象数据驱动**：宕机现场章的「现场初印象」优先渲染 `crash_feature_info.stack_impression`（按本次宕机栈生成的一句话）；缺失时模板按 `call_trace_signature` + `rip_function` + `bug_type` 动态生成通用文案。任何情况下不得出现与本次宕机栈无关的固定话术。
11. **内核源码摘录卡与源码互链**（origin 以行内彩色文字标签显示在 📍 路径:行号 旁，非 pill 徽标；附录源码卡不渲染高亮）
12. **推理步内联原文证据块（snippets）**：`reasoning[].snippets` 渲染为原文块（**第 4 章证据卡内完全内联、不再二次折叠**；其他位置短日志 inline 直出、其余默认折叠），逐行+行号+琥珀高亮+行尾 ◀ 注释（现场日志/调用栈/反汇编/源码/内存取证的关键行必配 `ann`，**每行 ≤35 字**：动词句写「为什么看它 + 这行在做什么 + 得到/证明什么」，避免名词堆叠与同义反复）；**注释优先写行内**（内容行尾 `◀ 注释`，模板自动解析并高亮该行，`ann` 保留兼容；第 2 章原始日志仍用 `raw_crash_log_ann` 且保持逐字）；**crash 类块（内存取证/反汇编/调用栈）必须为 crash 原始输出逐字**（首行 `crash>` 命令），`title` 必填、`loc` 只写范围/对象不重复命令、内容不自造「项N」编号；**源码块设 `first_line`（跳段/多文件拆 `segs`，content 不带行号前缀）**，`hl`/`ann` 键=内容第 N 行（模板兼容绝对文件行号写法）；`hl` 命中空行/省略行不高亮；**非原文类块（定性/上游对照/版本对照/检索记录/事实记录）渲染为结论清单卡**（无行号、非等宽，`ann` 收成卡底「小结/结论」条）；`segs` 多段子框每段独立文件行号/ref；无 snippets 的步骤自动转为块状事实块。
13. **补丁来源四档分级标签**：`classifyFixProvenance()` 从 verdict/mode/type 自动推断 confirmed/derived/speculative/none，在「根治措施」卡标题行右侧显示对应颜色小标签（副文案悬停可见），speculative 级 diff 区域琥珀色调 + subject 前缀 (自研)。
14. **内核源码摘录卡与源码互链**：`root_cause_analysis.local_source.refs` 渲染为技术附件「内核源码摘录」卡（默认收起），每条含文件:行号、函数、源码摘录与 `origin` 标注（`本地源码` 徽标 + 独立成行的本地路径 / `上游基线` 可外链「上游对照 ↗」，无 url 不渲染链接；标题与右侧标签分组固定，长路径不挤压标题）；**excerpt 逐行渲染并按 `hl` 行号高亮关键行**（崩溃行/关键调用行/补丁落点行，带行号强调）；补丁卡「涉及文件」命中 refs 时渲染为卡片锚点（复用 commit 关联的展开高亮机制）。
4. **论证展示规则**：
   - `confirmed` 的 commit：合并为单一区域「为什么这个 commit 能修复当前问题」，包含 `how` / `fix_scope` / 涉及文件 / `diff` 摘录。
   - `same_area` 的 commit / 社区案例：展示「匹配论证」+「适用性 / 参考性说明」，明确为什么只能参考、不能直接采用。
   - 内部案例：展示 `corroboration` 多维匹配论证表格 + `applicability` 采用前提 + `fingerprints` 匹配指纹。

## `diagnosis_repair_result` 的填写规则

- `internal_kernel_result` 的**核心字段**（`knowledge_id`/`bug_summary`/`root_cause`/`solution`/`hotpatch`/`kernel_versions`/`case_count`/`match_level` 等）必须逐值复制 `crash-feature-matcher:query_knowledge` / `query_cases` 返回的原生 JSON，再由 LLM 补齐分析字段（`id`/`anchor`/`title`/`verdict`/`fingerprints`/`affected_component`/`history`/`corroboration`/`applicability`，`match_score` 换算成 高/中/低），禁止改写核心字段的 value；`fingerprints`（匹配指纹）由 LLM 写成人类可读的多维特征列表（子系统/内核版本/CPU/机型/业务/访问模式），不要只写签名串。
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
3. **崩溃特征提取** — 用 `crash-feature-matcher` MCP 工具（`analyze_crash`、`query_knowledge`、`query_cases`）生成 `crash_feature_info.json`。若 `crash_time` 不是合法 ISO 8601 时间戳，则从日志推导或填 `"unknown"`，不得留空。另补 `stack_impression`（按本次宕机栈一句话的现场初印象，规范见 generate-report.md）。该节应由**脚本/工具生成**，不得由 LLM 改写。
4. **日志异常检测** — 用 `witty-log-detection` MCP 工具（`create_log_parse_task`、`get_task_result`）补充证据。
5. **社区案例检索** — 用 `crash-feature-matcher:query_community_cases` 生成 `diagnosis_repair_result.json`。内部案例核心字段须与原 JSON 逐值一致、再补齐分析字段（见 generate-report.md「内部案例条目细化」）；社区案例须与原 JSON 逐字节一致。**仅** `match_score` 例外：转换成匹配等级 高/中/低（`match_score`(0-1)：高≥0.7 / 中0.4-0.69 / 低<0.4）。该节应由**脚本/工具生成**，不得由 LLM 改写。
6. **根因验证** — 在核验调用栈完整性、模块一致性、源码映射后生成 `root_cause_analysis.json`；若不完整则再跑一轮。该节应由 **LLM 综合所有证据总结**，产出与 report.html 第 1/3/4 章一致的字段：
   - **`conclusion`**（**一句到三句**自然中文，叙事化、通俗、书面、少术语，**尽量短、只留结论**）：用「发生了什么 → 为什么 → 与业务/硬件是否有关」讲清场景与缺陷大类。**禁止**函数名/寄存器/标志常量/十六进制/地址/版本号/commit 号/进程名/PID 等实现细节；社区 `verdict=confirmed` 时去掉"推测"、以"（社区补丁已确认）"收尾，否则以"（推测）"结尾。
   - **`standard_solution`**（结构化对象）：`type`（patch/config/upgrade/none 四选一）/ `claim_tag` / `short`（**必须分「要做什么·为什么·怎么做」三句，每句一到两句话，通俗、书面、少术语，只写结论性表述**，不用函数名/寄存器/十六进制/文件行/循环位置）/ `basis`（修复依据）/ `fixed_in`（版本判定）/ `patch_list`（补丁 diff）/ `method_steps`（合入步骤）/ `detail`（完整说明）/ `rollback`（回退方案，**必填**：补丁/配置失败或回归时的回退步骤与还原命令）/ `verification`（验证方案，**必填**：编译无告警、压力回归、观察 dmesg 无新 Oops、监控同类 panic 建簇等）。`patch_list[].mode` 三选一：`full`/`part`/`pick`；`patch_list[].diff` **必须给可直接合入的具体补丁示例（diff 格式，含 +/- 行），禁止留空**；`type=patch` 时必须至少一条 `patch_list`。
   - **`temporary_workaround`**（结构化对象）：`type`（config=命令行/配置规避、none=无方案）/ `title` / `case_refs` / `summary` / `steps` / `risk` / `detail`。**从 `trigger_scenario` 出发写针对性手段**（如针对高频迁移/睡眠唤醒的绑核、降频），**禁止周期性重启/kdump 兜底等任何宕机都能套的通用手段**；无针对性方案时 `type=none`、`summary=暂无`、`steps=[]`（HTML 仍渲染该卡并显示「暂无临时规避手段」）。有方案时 `steps` 优先给 shell 命令、改内核/服务配置、降低迁移/并发等可落地手段。
   - **`event_scene`**（事件时序图，采用固定骨架+有限推断）：泳道固定为 process/kernel/hardware，CFS、hrtimer、CPU 均归入 kernel；主链路按“触发动作→进入内核→关键处理→异常状态→崩溃指令”组织，建议 4–8 步。每条事件填写 `evidence_level`（L1=直接证据、L2=强推断、L3=机制补全）与 `evidence`，主图只允许 L1/L2，L3 只能进入 `full` 并标注推断；只有两个并发路径、共享状态和明确交错关系同时成立时才使用 race。`participants`（`id`、`name`、`type` 三选一 process/kernel/hardware、`init`、`tip`）/ `gvars`+`ginit` / `anchor` / `events`（`m`、`from`/`to`、`kind`、`dt_ms`、`t`、`val`/`full`、`g[]`）。机制概述、当前判断必须引用同一条主链路，不得各自补造另一套过程。
   - **`propagation_chain`**（崩溃链路**必须拆成一步步**，每步一个栈帧↔源码对应）：每跳给 栈帧↔源码（`src_dir`/`file`/`line`/`fn_ctx`/`stack`，`from`/`to` 用**函数名**，`stack` 形如 `set_next_entity+0x20/0x6f8 (L2660)`）、关键参数 `params`（**寄存器值 ↔ 实际变量/形参**：`io`/`reg`/`n`/`formal`/`v`/`bad`，异常参数标红，**每个有实参的跳都要给 params**）、`detail`/`evidence`；**每一跳都应给出 `source_url`**（在线源码/commit/patch 链接）便于跳转对照；最后一跳写明二进制↔源码行对照。该字段仍为 schema 必填（后端追踪与原始数据），但 HTML **不再渲染**「完整技术传播链」折叠块，`source_url` 仅存数据不渲染。
   - **`deep.evidence[]`**（逐条核心依据）：每条使用对象 `{title, short, summary, level, reasoning[], connect}`（`title` 必填设问式、`short` 4~10 字索引导航标签、`connect` 串联、`level` 证据级别徽标，规则见 generate-report.md）；`reasoning[]` 是该依据自己的证据推理链，每步填写 `step`/`detail`/`evidence`（`evidence` 用类别前缀结构化清单，禁堆工具原始输出），**建议以 `step="推导与结论"` 步收尾**（可复核推导 → `conclusion`，该步可不配 snippet）。HTML 把 `level` 渲染为结论行徽标（实测=绿/推断=琥珀/未定=灰），并为每条依据单独提供展开面板。
   - **`local_source`**（内核源码摘录，本地源码分析时填）：诊断对照过的源码片段（id/file/lines/func/excerpt/origin/url/note/path），渲染为附件「内核源码摘录」卡并与补丁卡互链；上游无 confirmed 补丁且有本地源码时，自研补丁 diff 落点文件必须列入 refs（规范见 generate-report.md）。
   - **`reasoning_flow`**（结构化后端追踪，schema 必填）：保留三部分根因阶段，供机器校验和原始数据追溯；HTML 不再将其作为独立的“总体诊断推理链”展示，避免与 `deep.evidence[].reasoning[]` 重复。
   - **`deep`**（根因结论详细）：`lead` / `mechanism_summary` / `judgment` / `mechanism` / `evidence` / `confidence` / `scope`。其中 `mechanism_summary` 是给读者看的 1–3 句人话概述，只解释发生了什么、为什么崩溃、影响是什么；`judgment` 是当前根因判断和处置方向；`mechanism` 保留技术触发链，供泳道图下方的详细链条使用，三者不可互相替代。
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
3. 进行**质量软检查（WARN 级，不影响退出码）**——以下形态会在 stderr 打印 `[WARN]`，交付前应逐条修正到零 WARN：
   - `deep.evidence[].title` 缺失或非设问式（缺失同时会被 schema 硬拒；非设问式改写为含「为什么/怎么/在哪/从哪/有没有」的标题）；
   - `deep.evidence[].level` 缺失或不含 `实测/推断/未定` 之一——补证据级别（徽标按实测=绿/推断=琥珀/未定=灰渲染）；
   - 全报告没有任何 `reasoning[]` 步带 `conclusion`——建议每条依据以 `step="推导与结论"` 收尾（可复核推导 → 结论）；
   - `现场日志`/`反汇编`/`调用栈`/`源码`/`内存取证` 的 snippet 有 `hl` 但无 `ann`——关键行补行尾 `◀` 注释；
   - `raw_crash_log` 存在但 `raw_crash_log_ann` 缺失/为空——给 BUG/故障地址/RIP/Call Trace/Code/panic 等关键行（3~6 条）补行尾 `◀` 注释；
   - `reasoning[].evidence` / `detail` 含检索工具原始输出（`query_*`、`match_score`、`commits=[]`、`patch_mails=[]`、`issue-…-NNN`）——改写为人话（如「内部库命中 1 条同位置旧案例（匹配度中等）· 未给出根因与修复」），原始标识只留在 `workflow_trace`；
   - `standard_solution.type=patch` 而 `patch_list` 为空或某条 `diff` 为空——自研补丁也必须给出可合入 diff；
   - `local_source.refs` 的 `id` 缺失/重复或 `excerpt` 为空——源码摘录必须逐字真实非空、锚点唯一；
   - 三路检索均无 `confirmed` 而 `fixed_brief` 宣称「已有补丁」——直写「上游无对应补丁，需自研适配或提供更多信息诊断」。
4. 校验失败时打印详细错误并返回非零退出码；成功时输出 `OK`（含未清零的 WARN 清单）。

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
