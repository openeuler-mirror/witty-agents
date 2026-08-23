#!/usr/bin/env python3
"""Generate a user-facing core_report.json from a full DiagnoseReport.

Schema-driven field extraction: the field map lives entirely in
schemas/core-report-schema.json via x-source / x-default / x-transform
metadata on each property. To add/rename a field, edit the schema only —
this script reads the schema and extracts accordingly, no hardcoding.

x-source semantics:
  - "a.b.c"        : dot-path into the source report (string/array/int leaf)
  - "a"            : for object-typed fields, take source report's "a" object
                    but keep only the sub-fields declared in this schema's
                    properties (extra fields like `modules` are dropped)
x-default : value used when the x-source path is missing/None
x-transform: name of a special handler in TRANSFORMS (for non-trivial logic
             like match_info which merges internal/community results)

Usage:
    python3 generate_core_report.py --report report.json --output core_report.json
    python3 generate_core_report.py --report report.json --output core_report.json --validate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    return str(val)


def get_by_path(source: Any, path: str) -> Any:
    """Resolve a dot-path like 'crash_feature_info.bug_summary' against report."""
    cur: Any = source
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


# --------------------------------------------------------------------------- #
# Special transforms for fields that cannot be expressed by a plain x-source.
# Each takes the full source report and returns the field value.
# Registered by name (must match x-transform in schema).
# --------------------------------------------------------------------------- #

def _build_match_info(report: dict) -> dict:
    """Compact match summary: prefer internal, then community, else unmatched."""
    drr = report.get("diagnosis_repair_result") or {}
    internal = drr.get("internal_kernel_result") or []
    community = drr.get("community_kernel_result") or []

    case: dict | None = None
    if internal:
        case = internal[0]
    elif community:
        case = community[0]

    if not case:
        return {"matched": False, "knowledge_id": "", "source": "", "match_score": ""}

    return {
        "matched": True,
        "knowledge_id": _safe_str(case.get("knowledge_id")),
        "source": _safe_str(case.get("source")),
        "match_score": _safe_str(case.get("match_score")),
    }


TRANSFORMS: dict[str, Callable[[dict], Any]] = {
    "match_info": _build_match_info,
}


def extract_field(name: str, prop_schema: dict, report: dict) -> Any:
    """Extract one core-report field value driven by schema metadata."""
    # 1. Special transform wins over x-source.
    if "x-transform" in prop_schema:
        fn_name = prop_schema["x-transform"]
        fn = TRANSFORMS.get(fn_name)
        if fn is None:
            raise ValueError(f"unknown x-transform '{fn_name}' for field '{name}'")
        return fn(report)

    # 2. x-source required for non-transform fields.
    src = prop_schema.get("x-source")
    if src is None:
        raise ValueError(
            f"field '{name}' has neither x-source nor x-transform; "
            f"cannot extract (add one in schema)"
        )

    val = get_by_path(report, src)

    # 3. Object-typed: keep only sub-fields declared in schema properties.
    if prop_schema.get("type") == "object" and isinstance(val, dict):
        sub_props = prop_schema.get("properties", {})
        return {
            sub_name: _safe_subfield(val.get(sub_name), sub_schema)
            for sub_name, sub_schema in sub_props.items()
        }

    # 4. Missing -> x-default if provided.
    if val is None and "x-default" in prop_schema:
        return prop_schema["x-default"]

    # 5. Normalize None scalars to safe empties (avoid null in core report).
    if val is None:
        if prop_schema.get("type") == "array":
            return []
        if prop_schema.get("type") == "integer":
            return 0
        return ""

    return val


def _safe_subfield(val: Any, sub_schema: dict) -> Any:
    """Coerce a sub-field value to a safe empty for its declared type."""
    if val is not None:
        return val
    t = sub_schema.get("type")
    if t == "integer":
        return 0
    return ""


def build_core_report(report: dict, schema: dict) -> dict:
    """Walk schema.properties and extract each field from report."""
    props = schema.get("properties", {})
    core: dict[str, Any] = {}
    missing: list[str] = []
    for name, prop_schema in props.items():
        try:
            core[name] = extract_field(name, prop_schema, report)
        except ValueError as exc:
            missing.append(str(exc))
    if missing:
        print("WARNING: schema issues: " + "; ".join(missing), file=sys.stderr)
    return core


def validate_core_report(core_report: Any, schema_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        import jsonschema
    except ImportError as exc:
        return [f"jsonschema not installed: {exc}"]
    try:
        schema = load_json(schema_path)
        jsonschema.validate(instance=core_report, schema=schema)
    except jsonschema.exceptions.ValidationError as exc:
        errors.append(f"[schema] {exc.message} (path: {'/'.join(str(p) for p in exc.path)})")
    except Exception as exc:
        errors.append(f"[schema] {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a compact core_report.json from a full DiagnoseReport (schema-driven)."
    )
    parser.add_argument("--report", type=Path, required=True, help="Path to the full report.json.")
    parser.add_argument("--output", type=Path, required=True, help="Output path for core_report.json.")
    parser.add_argument("--validate", action="store_true", help="Validate the core report against the schema.")
    parser.add_argument("--schema", type=Path, default=None, help="Path to core-report schema (default: bundled).")
    args = parser.parse_args()

    if not args.report.exists():
        print(f"ERROR: report file not found: {args.report}", file=sys.stderr)
        return 1

    if args.schema is None:
        script_dir = Path(__file__).resolve().parent
        schema_path = script_dir.parent / "schemas" / "core-report-schema.json"
    else:
        schema_path = args.schema

    if not schema_path.exists():
        print(f"ERROR: schema file not found: {schema_path}", file=sys.stderr)
        return 1

    schema = load_json(schema_path)
    report = load_json(args.report)
    core_report = build_core_report(report, schema)

    write_json(args.output, core_report)
    print(f"Wrote core report to {args.output}")

    full_size = len(json.dumps(report, ensure_ascii=False))
    core_size = len(json.dumps(core_report, ensure_ascii=False))
    pct = 100 * core_size / max(full_size, 1)
    print(f"Size: {full_size} -> {core_size} chars ({pct:.0f}%)")

    if args.validate:
        # Validate against the same schema (x-* keys are ignored by jsonschema).
        errors = validate_core_report(core_report, schema_path)
        if errors:
            print("VALIDATION FAILED", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 2
        print("OK - core report is valid")

    return 0


if __name__ == "__main__":
    sys.exit(main())
