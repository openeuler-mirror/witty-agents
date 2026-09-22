#!/usr/bin/env python3
"""对照规范 JSON Schema 校验神农内核宕机诊断报告。

Usage:
    python3 validate_report.py --report report.json [--schema schema.json]
    python3 validate_report.py --report report.json --output validated.json

退出码:
    0 - 报告有效
    1 - schema 错误或报告缺失
    2 - 报告校验失败
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def validate_schema(report: Any, schema: Any) -> list[str]:
    try:
        import jsonschema
        from jsonschema.exceptions import ValidationError
    except ImportError as exc:  # pragma: no cover
        return [f"jsonschema not installed: {exc}. Run: pip install jsonschema>=4.0.0"]

    errors: list[str] = []
    try:
        jsonschema.validate(instance=report, schema=schema)
    except ValidationError as exc:
        errors.append(f"[schema] {exc.message} (path: {'/'.join(str(p) for p in exc.path)})")
    return errors


def validate_semantics(report: Any) -> list[str]:
    """JSON Schema 之外的额外语义检查。"""
    errors: list[str] = []

    if not isinstance(report, dict):
        errors.append("report must be a JSON object")
        return errors

    # workflow_trace step_count must match steps length
    workflow_trace = report.get("workflow_trace")
    if isinstance(workflow_trace, dict):
        step_count = workflow_trace.get("step_count")
        steps = workflow_trace.get("steps", [])
        if isinstance(step_count, int) and isinstance(steps, list):
            if step_count != len(steps):
                errors.append(
                    f"workflow_trace.step_count ({step_count}) does not match "
                    f"len(steps) ({len(steps)})"
                )
        source = workflow_trace.get("source")
        if source not in ("opencode_export", "manual"):
            errors.append(f"workflow_trace.source must be 'opencode_export' or 'manual', got '{source}'")

    # report_id format: HOSTNAME-YYYYMMDD-YYYYMMDD
    report_id = report.get("report_id")
    if isinstance(report_id, str) and not re.fullmatch(r"[^-]+-\d{8}-\d{8}", report_id):
        errors.append(
            f"report_id '{report_id}' does not match expected format HOSTNAME-YYYYMMDD-YYYYMMDD"
        )

    # parse_log_range must be non-empty
    parse_log_range = report.get("parse_log_range")
    if isinstance(parse_log_range, list) and len(parse_log_range) == 0:
        errors.append("parse_log_range must not be empty")

    # diagnosis_repair_result must be an object with both arrays
    result = report.get("diagnosis_repair_result")
    if isinstance(result, dict):
        for key in ("community_kernel_result", "internal_kernel_result"):
            if not isinstance(result.get(key), list):
                errors.append(f"diagnosis_repair_result.{key} must be an array")
            else:
                for idx, item in enumerate(result[key]):
                    if not isinstance(item, dict):
                        errors.append(f"diagnosis_repair_result.{key}[{idx}] must be an object")

    # crash_feature_info must not be empty
    crash_feature_info = report.get("crash_feature_info")
    if isinstance(crash_feature_info, dict):
        for key in (
            "crash_time",
            "signature",
            "bug_type",
            "bug_key",
            "bug_summary",
            "rip",
            "rip_function",
            "rip_offset",
        ):
            value = crash_feature_info.get(key)
            if value is None or (isinstance(value, str) and value == ""):
                errors.append(f"crash_feature_info.{key} is empty or missing")

    return errors


TITLE_QUESTION_WORDS = ("为什么", "怎么", "在哪", "从哪", "有没有", "如何")
RAW_TOOL_OUTPUT_RE = re.compile(
    r"query_knowledge|query_community_cases|query_upstream_online|match_score"
    r"|commits=\[\]|patch_mails=\[\]|issue-[a-z0-9-]+-\d{2,}"
)


def validate_quality(report: Any) -> list[str]:
    """报告质量软检查（WARN 级，不影响退出码）：
    - deep.evidence[].title 必填且设问式（缺失会被 HTML 渲染成「依据 N」）
    - deep.evidence[].level 证据级别（HTML 渲染为结论行徽标）
    - deep.evidence 建议以「推导与结论」步收尾（可复核推导 → conclusion）
    - 现场日志/反汇编/调用栈/源码/内存取证的 snippet 每个 hl 行都应配 ann（行尾 ◀ 注释）
    - 第 4 章 snippet 应有 title；crash 块 loc 不重复命令；禁止自造「项N」编号摘要
    - snippet 行号一致性：hl/ann 键不得越界、hl 不得指向空行/省略行
    - deep.evidence 环间 connect 不得缺失（i>0）、单条 reasoning 至少 2 步、step/detail 非空
    - 源码块必须 first_line（跳段拆 segs）、内容不得带行号前缀或用「...」跳段
    - 源码块 ann 关键标识必须落在所标行（错位/缺锚点告警）
    - 行内注释（行尾 `◀ 注释`）与 ann 重复、只有 ◀ 无文本、清单类块使用行内注释 → WARN
    - raw_crash_log 存在时应有 raw_crash_log_ann（关键行注释）
    - evidence/detail 禁止堆检索工具原始输出（应翻译成人话）
    - type=patch 必须有非空 patch_list[].diff
    - local_source.refs 的 id 唯一、excerpt 非空
    - 三库无 confirmed 而 fixed_brief 宣称「已有补丁」
    """
    warns: list[str] = []
    if not isinstance(report, dict):
        return warns

    rca = report.get("root_cause_analysis") or {}
    deep = rca.get("deep") or {}

    # 1) evidence title 必填且设问式
    for i, ev in enumerate(deep.get("evidence") or []):
        if not isinstance(ev, dict):
            continue
        title = str(ev.get("title") or "").strip()
        if not title:
            warns.append(
                f"deep.evidence[{i}].title 缺失（HTML 将渲染为「依据 {i + 1}」）；"
                f"应写设问式标题，如「{str(ev.get('summary') or '')[:12]}…从哪来/为什么」"
            )
        elif not any(w in title for w in TITLE_QUESTION_WORDS):
            warns.append(
                f"deep.evidence[{i}].title 「{title[:24]}」非设问式（应含 为什么/怎么/在哪/从哪/有没有 等疑问词）"
            )

    # 1b) evidence 证据级别（level 徽标）
    LEVEL_WORDS = ("实测", "推断", "未定")
    evs = [e for e in (deep.get("evidence") or []) if isinstance(e, dict)]
    for i, ev in enumerate(evs):
        level = str(ev.get("level") or "").strip()
        if not level:
            warns.append(
                f"deep.evidence[{i}].level 缺失（HTML 结论行将没有证据级别徽标）；"
                f"建议取「现场实测」「实测+推断」「推断」「未定」之一"
            )
        elif not any(w in level for w in LEVEL_WORDS):
            warns.append(
                f"deep.evidence[{i}].level 「{level[:24]}」不含 实测/推断/未定 ——按实际证据强度标注，不得拔高"
            )

    # 1c) 建议以「推导与结论」步收尾（报告级提示，避免逐条刷屏）
    has_conclusion = any(
        isinstance(r, dict) and str(r.get("conclusion") or "").strip()
        for ev in evs
        for r in (ev.get("reasoning") or [])
    )
    if evs and not has_conclusion:
        warns.append(
            "deep.evidence 中没有任何 reasoning[].conclusion ——建议每条依据以 "
            "step=\"推导与结论\" 收尾（detail=可复核推导，conclusion=该条结论）"
        )

    # 1d) 五类原文块的关键行注释（有 hl 应有 ann）
    ANN_REQUIRED_KINDS = ("现场日志", "反汇编", "调用栈", "源码", "内存取证")
    LIST_KINDS = ("定性", "推断", "上游对照", "版本对照", "检索记录", "事实记录")
    for i, ev in enumerate(evs):
        for j, r in enumerate(ev.get("reasoning") or []):
            if not isinstance(r, dict):
                continue
            for k, sn in enumerate(r.get("snippets") or []):
                if not isinstance(sn, dict):
                    continue
                if (
                    str(sn.get("kind") or "") in ANN_REQUIRED_KINDS
                    and (sn.get("hl") or [])
                    and not (sn.get("ann") or {})
                ):
                    warns.append(
                        f"deep.evidence[{i}].reasoning[{j}].snippets[{k}]（{sn.get('kind')}）有 hl 但无 ann ——"
                        f"崩溃行/故障指令行/关键调用帧应补行尾 ◀ 注释"
                    )

    # 1e) 第 4 章 snippet 规范：title 必填；crash 块 loc 不重复命令；禁止自造编号摘要
    for i, ev in enumerate(evs):
        for j, r in enumerate(ev.get("reasoning") or []):
            if not isinstance(r, dict):
                continue
            for k, sn in enumerate(r.get("snippets") or []):
                if not isinstance(sn, dict):
                    continue
                label = f"deep.evidence[{i}].reasoning[{j}].snippets[{k}]"
                title = str(sn.get("title") or "").strip()
                if not title:
                    warns.append(f"{label} 缺少 title —— 应写一句话说明这块看的是什么")
                loc = str(sn.get("loc") or "")
                content = str(sn.get("content") or "").lstrip()
                m_cmd = re.match(r"crash>\s*(\S+)", content)
                if m_cmd and loc.strip().lower().startswith("crash"):
                    sub = m_cmd.group(1).rstrip(">").lower()
                    if sub and sub in [t.lower().rstrip(":：") for t in loc.split()[:4]]:
                        warns.append(
                            f"{label} loc 与内容首行命令重复 —— 命令放 content 首行，loc 只写范围/对象"
                        )
                if re.search(r"项\s*\d+", content) and not content.startswith("crash>"):
                    warns.append(
                        f"{label} 疑似自造的「项N」编号摘要 —— crash 类块应贴 crash 原始输出（首行 `crash>` 命令）"
                    )

    # 1f) snippet 行号/注释一致性：first_line/segs、hl/ann 键范围、空行、逐行覆盖、源码前缀
    SRC_NUM_PREFIX_RE = re.compile(r"^\s*\d+\s+\S")
    DOTS_LINE_RE = re.compile(r"^[.\u2026]{2,}$")

    def _is_blank_line(line: str) -> bool:
        t = line.strip()
        return (not t) or bool(DOTS_LINE_RE.match(t))

    def _ann_dict(raw):
        out = {}
        if isinstance(raw, dict):
            for ak, av in raw.items():
                try:
                    ak2 = int(ak)
                except (TypeError, ValueError):
                    continue
                if ak2 > 0 and isinstance(av, str) and av.strip():
                    out[ak2] = av
        return out

    def _key_ok(key: int, n: int, abs_start) -> bool:
        if 1 <= key <= n:
            return True
        return abs_start is not None and abs_start <= key <= abs_start + n - 1

    def _rel_of(key: int, n: int, abs_start):
        if 1 <= key <= n:
            return key
        if abs_start is not None and abs_start <= key <= abs_start + n - 1:
            return key - abs_start + 1
        return None

    ANN_TOKEN_RE = re.compile(
        r"0x[0-9a-fA-F]+|[A-Za-z_][A-Za-z0-9_]*(?:->[A-Za-z_][A-Za-z0-9_]*)?|\b\d+\b"
    )
    ANN_TOKEN_STOP = {
        "the", "and", "for", "with", "from", "this", "that", "not", "are", "to", "of",
        "in", "on", "is", "it", "if", "else", "return", "goto", "while", "int", "void",
        "struct", "static", "const", "unsigned", "char", "long", "size", "num", "line",
    }

    def _ann_tokens(text: str):
        toks = []
        for m in ANN_TOKEN_RE.finditer(str(text or "")):
            t = m.group(0)
            if t.isdigit():
                # 纯数字过短（如 1/12/13）过于泛化，不作为锚点；保留 ≥3 位（如 100）
                if len(t) < 3:
                    continue
            elif len(t) < 3:
                continue
            if t.lower() in ANN_TOKEN_STOP:
                continue
            if t not in toks:
                toks.append(t)
        return toks

    for i, ev in enumerate(evs):
        for j, r in enumerate(ev.get("reasoning") or []):
            if not isinstance(r, dict):
                continue
            for k, sn in enumerate(r.get("snippets") or []):
                if not isinstance(sn, dict):
                    continue
                label = f"deep.evidence[{i}].reasoning[{j}].snippets[{k}]"
                kind = str(sn.get("kind") or "")
                blocks = []
                segs = [sg for sg in (sn.get("segs") or []) if isinstance(sg, dict)]
                if segs:
                    blocks = [(f"{label}.segs[{si}]", sg) for si, sg in enumerate(segs)]
                else:
                    blocks = [(label, sn)]
                for blabel, blk in blocks:
                    if not isinstance(blk.get("content"), str):
                        continue
                    lines = str(blk.get("content") or "").split("\n")
                    n = len(lines)
                    first_line = blk.get("first_line")
                    abs_start = first_line if isinstance(first_line, int) and first_line > 0 else None
                    hl = [x for x in (blk.get("hl") or []) if isinstance(x, int)]
                    ann = _ann_dict(blk.get("ann"))
                    hint = f"1..{n}" + ("（或绝对行号）" if abs_start else "")
                    # 行内注释（保守规则：整行只有一个 ◀，且前后均有非空文本）
                    inline_ann = {}
                    inline_empty = []
                    for ln_i, ln_txt in enumerate(lines, 1):
                        pos = ln_txt.rfind("◀")
                        if pos < 0:
                            continue
                        if "◀" in ln_txt[:pos]:
                            continue  # 多个 ◀ → 视为正文，不解析
                        before, after = ln_txt[:pos], ln_txt[pos + 1:]
                        if not before.strip():
                            continue
                        if after.strip():
                            # 与模板同规则：◀ 前必须紧邻空白，避免把代码里的 "◀" 字符串误判为注释
                            if before.endswith((" ", "\t")):
                                inline_ann[ln_i] = after.strip()
                        else:
                            if before.endswith((" ", "\t")):
                                inline_empty.append(ln_i)
                    if str(kind or "") in LIST_KINDS and (inline_ann or inline_empty):
                        warns.append(f"{blabel}（{kind}）清单类块不支持行内注释 —— 请把小结写入 ann（卡底展示）")
                    for ln_i in inline_empty:
                        warns.append(f"{blabel} 第 {ln_i} 行只有 ◀ 没有注释文本 —— 请补文本或删除该符号")
                    for ln_i in sorted(inline_ann):
                        if ann.get(ln_i) is not None or (
                            abs_start is not None and ann.get(abs_start + ln_i - 1) is not None
                        ):
                            warns.append(
                                f"{blabel} 第 {ln_i} 行同时有行内注释与 ann 条目 —— 行内优先，请删掉重复的 ann"
                            )
                    for key in sorted(set(hl)):
                        if not _key_ok(key, n, abs_start):
                            warns.append(f"{blabel} hl 行号 {key} 越界 —— 键按内容第 N 行：{hint}")
                    for key in sorted(ann):
                        if not _key_ok(key, n, abs_start):
                            warns.append(f"{blabel} ann 行号 {key} 越界 —— 键按内容第 N 行：{hint}")
                    for key in sorted(set(hl)):
                        rel = _rel_of(key, n, abs_start)
                        if rel is None:
                            continue
                        if _is_blank_line(lines[rel - 1]):
                            warns.append(f"{blabel} hl 指向空行/省略行（第 {rel} 行）—— 请标注有效内容行")
                        if kind in ANN_REQUIRED_KINDS and ann.get(rel) is None and (
                            abs_start is None or ann.get(abs_start + rel - 1) is None
                        ) and rel not in inline_ann:
                            warns.append(f"{blabel} hl 第 {rel} 行缺少 ann —— 高亮行应配行尾 ◀ 注释")
                    if kind == "源码":
                        if abs_start is None:
                            warns.append(
                                f"{blabel} 源码块缺少 first_line —— 内容不带行号前缀，行号由 first_line/segs 渲染"
                            )
                        first_text = next((ln for ln in lines if ln.strip()), "")
                        if abs_start is None and SRC_NUM_PREFIX_RE.match(first_text):
                            warns.append(
                                f"{blabel} 源码块内容带行号前缀（如「422 for_each_sg…」）—— 去掉前缀并改用 first_line/segs"
                            )
                        if not segs and any(DOTS_LINE_RE.match(ln.strip()) for ln in lines):
                            warns.append(f"{blabel} 源码块用「...」表示跳段 —— 请拆成 segs（每段独立 first_line）")
                        # 注释错位检测：ann 文本中的关键标识（标识符/字段/数值）应出现在所标注行；
                        # 只出现在邻近 ±3 行 → 疑似错位；四处都没有 → 缺锚点（均为 WARN）
                        for key in sorted(ann):
                            rel = _rel_of(key, n, abs_start)
                            if rel is None:
                                continue
                            toks = _ann_tokens(ann[key])
                            if not toks:
                                continue
                            if any(t in lines[rel - 1] for t in toks):
                                continue
                            found_at = None
                            found_tok = None
                            for off in range(1, 4):
                                for rr in (rel - off, rel + off):
                                    if not (1 <= rr <= n):
                                        continue
                                    for t in toks:
                                        if t in lines[rr - 1]:
                                            found_at, found_tok = rr, t
                                            break
                                    if found_at:
                                        break
                                if found_at:
                                    break
                            if found_at:
                                warns.append(
                                    f"{blabel} 源码注释疑似错位：关键标识「{found_tok}」在第 {found_at} 行，"
                                    f"但注释挂在第 {rel} 行 —— 请把 ann 移到对应行"
                                )
                            else:
                                warns.append(
                                    f"{blabel} 源码注释缺少行内锚点：关键标识 "
                                    f"{'/'.join(sorted(_ann_tokens(ann[key]))[:3])} 未出现在第 {rel} 行"
                                )

    # 1g) deep.evidence 内容结构：环间连接、步骤完整性、步骤字段非空
    for i, ev in enumerate(evs):
        if not isinstance(ev, dict):
            continue
        if i > 0 and not str(ev.get("connect") or "").strip():
            warns.append(
                f"deep.evidence[{i}] 缺少 connect —— 应先复述上一环结论（人话一句）再引出本环问题"
            )
        reasoning = [r for r in (ev.get("reasoning") or []) if isinstance(r, dict)]
        if len(reasoning) < 2:
            warns.append(f"deep.evidence[{i}] 的 reasoning 少于 2 步 —— 至少「证据步 + 推导与结论步」")
        for j, r in enumerate(reasoning):
            if not str(r.get("step") or "").strip():
                warns.append(f"deep.evidence[{i}].reasoning[{j}] 缺少 step —— 每步都要有一个设问短句")
            if not str(r.get("detail") or "").strip():
                warns.append(f"deep.evidence[{i}].reasoning[{j}] 缺少 detail —— 每步都要有一句人话发现")

    # 2) evidence/detail 禁止工具原始输出
    for i, ev in enumerate(deep.get("evidence") or []):
        if not isinstance(ev, dict):
            continue
        for j, r in enumerate(ev.get("reasoning") or []):
            if not isinstance(r, dict):
                continue
            for field in ("evidence", "detail"):
                text = r.get(field)
                if isinstance(text, str):
                    m = RAW_TOOL_OUTPUT_RE.search(text)
                    if m:
                        warns.append(
                            f"deep.evidence[{i}].reasoning[{j}].{field} 含工具原始输出「{m.group(0)}」；"
                            f"应翻译成人话（如「内部库命中 1 条同位置旧案例（匹配度中等）」）"
                        )

    # 3) type=patch 必须有非空 diff
    ss = rca.get("standard_solution") or {}
    if ss.get("type") == "patch":
        patches = ss.get("patch_list") or []
        if not patches:
            warns.append("standard_solution.type=patch 但 patch_list 为空")
        for k, p in enumerate(patches):
            if not isinstance(p, dict) or not str(p.get("diff") or "").strip():
                warns.append(f"standard_solution.patch_list[{k}].diff 为空（自研补丁也必须给可合入 diff）")

    # 4) local_source.refs id 唯一、excerpt 非空
    ls = rca.get("local_source") or {}
    seen_ids: set[str] = set()
    for k, ref in enumerate(ls.get("refs") or []):
        if not isinstance(ref, dict):
            continue
        rid = str(ref.get("id") or "")
        if not rid:
            warns.append(f"local_source.refs[{k}].id 缺失（正文/补丁锚点依赖它）")
        elif rid in seen_ids:
            warns.append(f"local_source.refs[{k}].id 「{rid}」重复")
        seen_ids.add(rid)
        if not str(ref.get("excerpt") or "").strip():
            warns.append(f"local_source.refs[{k}].excerpt 为空（源码摘录必须逐字真实非空）")
        excerpt_lines = len(str(ref.get("excerpt") or "").split("\n"))
        for n in ref.get("hl") or []:
            if not isinstance(n, int) or n < 1 or n > excerpt_lines:
                warns.append(
                    f"local_source.refs[{k}].hl 行号 {n} 越界（excerpt 共 {excerpt_lines} 行）；"
                    f"hl 必须是 excerpt 内 1-based 行号"
                )

    # 5) 三库无 confirmed 而 fixed_brief 宣称已有补丁
    diag = report.get("diagnosis_repair_result") or {}
    entries = []
    for key in ("online_result", "community_kernel_result", "internal_kernel_result"):
        entries.extend(x for x in (diag.get(key) or []) if isinstance(x, dict))
    has_confirmed = any(str(x.get("verdict") or "").lower() == "confirmed" for x in entries)
    fixed_brief = str(ss.get("fixed_brief") or "")
    if not has_confirmed and ("已有对应补丁" in fixed_brief or "已修复" in fixed_brief):
        warns.append(
            "三路检索均无 confirmed 补丁，但 fixed_brief 宣称「已有补丁」；"
            "应直写「上游无对应补丁，需自研适配或提供更多信息诊断」"
        )

    # 6) 原始崩溃日志关键行注释（有 raw_crash_log 应有 raw_crash_log_ann；注释要讲清函数职责/中断现场/数值来由）
    cfi = report.get("crash_feature_info") or {}
    if isinstance(cfi, dict) and str(cfi.get("raw_crash_log") or "").strip():
        rla = cfi.get("raw_crash_log_ann")
        if not isinstance(rla, dict) or not rla:
            warns.append(
                "crash_feature_info.raw_crash_log 存在但 raw_crash_log_ann 缺失/为空 —— "
                "应给关键行（BUG/故障地址/RIP/Call Trace/Code/panic 等 3~8 行）补 ◀ 行尾注释"
            )
        else:
            generic_labels = {
                "崩溃类型行", "崩溃类型/故障地址", "崩溃指令位置", "故障指令机器码",
                "调用栈帧", "调用栈：自崩溃点向上回溯", "停机/捕获信息",
            }
            for key, val in rla.items():
                text = str(val or "").strip()
                if len(text) < 8 or text in generic_labels:
                    warns.append(
                        f"crash_feature_info.raw_crash_log_ann[{key}] 注释过于简略或标签化（「{text[:24]}」）——"
                        f"应写清函数职责 / 中断现场 / 数值来由，让读者一眼看懂"
                    )

    return warns


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a crash report JSON.")
    parser.add_argument(
        "--report",
        required=True,
        type=Path,
        help="Path to the crash report JSON file (or '-' for stdin).",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="Path to the JSON schema file. Defaults to the bundled schema.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="If provided, write the validated report to this file.",
    )
    parser.add_argument(
        "--no-semantics",
        action="store_true",
        help="Skip semantic checks and only validate against JSON schema.",
    )
    args = parser.parse_args()

    # Resolve schema path
    if args.schema is None:
        script_dir = Path(__file__).resolve().parent
        schema_path = script_dir.parent / "schemas" / "crash-report-schema.json"
    else:
        schema_path = args.schema

    if not schema_path.exists():
        print(f"ERROR: schema file not found: {schema_path}", file=sys.stderr)
        return 1

    # Load report
    if str(args.report) == "-":
        try:
            report = json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            print(f"ERROR: invalid JSON from stdin: {exc}", file=sys.stderr)
            return 1
    else:
        if not args.report.exists():
            print(f"ERROR: report file not found: {args.report}", file=sys.stderr)
            return 1
        try:
            report = load_json(args.report)
        except json.JSONDecodeError as exc:
            print(f"ERROR: invalid JSON in report: {exc}", file=sys.stderr)
            return 1

    schema = load_json(schema_path)

    schema_errors = validate_schema(report, schema)
    semantic_errors: list[str] = []
    quality_warnings: list[str] = []
    if not args.no_semantics:
        semantic_errors = validate_semantics(report)
        quality_warnings = validate_quality(report)

    all_errors = schema_errors + semantic_errors

    if quality_warnings:
        print(f"{len(quality_warnings)} quality warning(s):", file=sys.stderr)
        for w in quality_warnings:
            print(f"  [WARN] {w}", file=sys.stderr)

    if all_errors:
        print("VALIDATION FAILED", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 2

    print("OK - report is valid")
    if args.output:
        write_json(args.output, report)
        print(f"Wrote validated report to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
