#!/usr/bin/env python3
"""Combine per-section JSON files into a full DiagnoseReport.

Usage:
    python3 combine_report.py --sections-dir ./report_sections --output report.json
    python3 combine_report.py \
        --report-id host-20240712-20240713 \
        --parse-log-range vmcore,vmcore-dmesg \
        --host-base-info host_base_info.json \
        --crash-feature-info crash_feature_info.json \
        --root-cause-analysis root_cause_analysis.json \
        --diagnosis-repair-result diagnosis_repair_result.json \
        --workflow-trace workflow_trace.json \
        --output report.json

The script will validate the assembled report against the canonical JSON schema
if `--validate` is provided (requires jsonschema).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_report(
    report_id: str | None,
    parse_log_range: list[str],
    host_base_info: dict,
    crash_feature_info: dict,
    root_cause_analysis: dict,
    diagnosis_repair_result: dict,
    workflow_trace: dict,
) -> dict:
    if report_id is None:
        report_id = f"unknown-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    return {
        "report_id": report_id,
        "parse_log_range": parse_log_range,
        "host_base_info": host_base_info,
        "crash_feature_info": crash_feature_info,
        "root_cause_analysis": root_cause_analysis,
        "diagnosis_repair_result": diagnosis_repair_result,
        "workflow_trace": workflow_trace,
    }


def validate_report(report: Any, schema_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        import jsonschema
    except ImportError as exc:
        return [f"jsonschema not installed: {exc}"]

    try:
        schema = load_json(schema_path)
        jsonschema.validate(instance=report, schema=schema)
    except jsonschema.exceptions.ValidationError as exc:
        errors.append(f"[schema] {exc.message} (path: {'/'.join(str(p) for p in exc.path)})")
    except Exception as exc:
        errors.append(f"[schema] {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Combine report sections into a full DiagnoseReport.")
    parser.add_argument("--sections-dir", type=Path, help="Directory containing section JSON files.")
    parser.add_argument("--output", type=Path, required=True, help="Output path for the full report.")
    parser.add_argument("--validate", action="store_true", help="Validate the assembled report against the schema.")
    parser.add_argument("--schema", type=Path, default=None, help="Path to JSON schema (default: bundled schema).")

    # Individual section options (override sections-dir)
    parser.add_argument("--report-id", type=str, default=None)
    parser.add_argument("--parse-log-range", type=str, default="", help="Comma-separated log sources.")
    parser.add_argument("--host-base-info", type=Path, default=None)
    parser.add_argument("--crash-feature-info", type=Path, default=None)
    parser.add_argument("--root-cause-analysis", type=Path, default=None)
    parser.add_argument("--diagnosis-repair-result", type=Path, default=None)
    parser.add_argument("--workflow-trace", type=Path, default=None)

    args = parser.parse_args()

    # Resolve schema path
    if args.schema is None:
        script_dir = Path(__file__).resolve().parent
        schema_path = script_dir.parent / "schemas" / "crash-report-schema.json"
    else:
        schema_path = args.schema

    if args.sections_dir:
        sections_dir = args.sections_dir
        section_files = {
            "host_base_info": "host_base_info.json",
            "crash_feature_info": "crash_feature_info.json",
            "root_cause_analysis": "root_cause_analysis.json",
            "diagnosis_repair_result": "diagnosis_repair_result.json",
            "workflow_trace": "workflow_trace.json",
        }
        sections: dict[str, Any] = {}
        for key, filename in section_files.items():
            path = sections_dir / filename
            if not path.exists():
                print(f"ERROR: missing section file: {path}", file=sys.stderr)
                return 1
            sections[key] = load_json(path)

        report_id_path = sections_dir / "report_id.txt"
        report_id = args.report_id
        if report_id is None and report_id_path.exists():
            report_id = report_id_path.read_text().strip()

        parse_log_range_path = sections_dir / "parse_log_range.json"
        parse_log_range: list[str] = []
        if parse_log_range_path.exists():
            parse_log_range = load_json(parse_log_range_path)
        elif args.parse_log_range:
            parse_log_range = [s.strip() for s in args.parse_log_range.split(",") if s.strip()]

        report = build_report(
            report_id,
            parse_log_range,
            sections["host_base_info"],
            sections["crash_feature_info"],
            sections["root_cause_analysis"],
            sections["diagnosis_repair_result"],
            sections["workflow_trace"],
        )
    else:
        # Use individual section files
        if not all([
            args.host_base_info,
            args.crash_feature_info,
            args.root_cause_analysis,
            args.diagnosis_repair_result,
            args.workflow_trace,
        ]):
            print("ERROR: must provide either --sections-dir or all individual section paths", file=sys.stderr)
            return 1

        parse_log_range = [s.strip() for s in args.parse_log_range.split(",") if s.strip()]
        report = build_report(
            args.report_id,
            parse_log_range,
            load_json(args.host_base_info),
            load_json(args.crash_feature_info),
            load_json(args.root_cause_analysis),
            load_json(args.diagnosis_repair_result),
            load_json(args.workflow_trace),
        )

    write_json(args.output, report)
    print(f"Wrote combined report to {args.output}")

    if args.validate:
        if not schema_path.exists():
            print(f"ERROR: schema file not found: {schema_path}", file=sys.stderr)
            return 1
        errors = validate_report(report, schema_path)
        if errors:
            print("VALIDATION FAILED", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 2
        print("OK - combined report is valid")

    return 0


if __name__ == "__main__":
    sys.exit(main())
