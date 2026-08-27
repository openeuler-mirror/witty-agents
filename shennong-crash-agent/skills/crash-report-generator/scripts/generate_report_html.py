#!/usr/bin/env python3
"""Generate a standalone crash-report HTML from report.json.

Reads the bundled HTML template and inlines the report JSON payload so the
result is a single self-contained HTML file (openable via file://, no local
HTTP server required).

Usage:
    python3 generate_report_html.py \
        --report report.json --output crash-report.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Placeholder token must match the template: const EMBED_FULL = /*__FULL_DATA__*/null;
FULL_TOKEN = "/*__FULL_DATA__*/null"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def dumps_js(data) -> str:
    """Serialize to JSON and escape so it's safe to inline inside <script>."""
    s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Prevent "</script>" / "<!--" from closing the script tag early.
    return s.replace("</", "<\\/").replace("<!", "<\\!")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a standalone crash-report HTML from report.json."
    )
    parser.add_argument("--report", type=Path, default=Path("report.json"),
                        help="Path to the full report.json.")
    parser.add_argument("--output", type=Path, default=Path("crash-report.html"),
                        help="Output standalone HTML path.")
    parser.add_argument("--template", type=Path, default=None,
                        help="Path to the HTML template (default: bundled template).")
    args = parser.parse_args()

    template_path = args.template
    if template_path is None:
        script_dir = Path(__file__).resolve().parent
        template_path = script_dir.parent / "templates" / "crash-report-viewer.html"

    if not template_path.exists():
        print(f"ERROR: template not found: {template_path}", file=sys.stderr)
        return 1
    if not args.report.exists():
        print(f"ERROR: report not found: {args.report}", file=sys.stderr)
        return 1

    template = template_path.read_text(encoding="utf-8")
    report = load_json(args.report)

    html = template.replace(FULL_TOKEN, "/*__FULL_DATA__*/" + dumps_js(report))

    args.output.write_text(html, encoding="utf-8")
    print(f"Wrote standalone report to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())