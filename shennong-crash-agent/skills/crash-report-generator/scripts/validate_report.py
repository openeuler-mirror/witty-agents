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
    - 现场日志/反汇编/调用栈的 snippet 有 hl 应配 ann（行尾 ◀ 注释）
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

    # 1d) 现场日志/反汇编/调用栈的关键行注释（有 hl 应有 ann）
    ANN_REQUIRED_KINDS = ("现场日志", "反汇编", "调用栈")
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
