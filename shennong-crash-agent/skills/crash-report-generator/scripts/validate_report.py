#!/usr/bin/env python3
"""Validate a Shennong crash diagnosis report against the canonical JSON schema.

Usage:
    python3 validate_report.py --report report.json [--schema schema.json]
    python3 validate_report.py --report report.json --output validated.json

Exit codes:
    0 - report is valid
    1 - schema error or report missing
    2 - report validation failed
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
    """Additional checks that go beyond the JSON schema."""
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
    if not args.no_semantics:
        semantic_errors = validate_semantics(report)

    all_errors = schema_errors + semantic_errors

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
