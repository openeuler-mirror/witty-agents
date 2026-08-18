#!/usr/bin/env python3
"""
parse-perf-log.py

Parse xlite / vLLM performance log files and emit a normalized JSON metrics report.
Usage:
    python3 parse-perf-log.py <perf.log> [-o metrics.json]

Extracted fields (best effort):
    wall_ms              total wall time per step / decode step
    tpot_ms_per_token    time per output token
    throughput_tok_s     tokens / second
    p50 / p99 latencies  if present
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


PATTERNS = {
    # Match lines like:  Wall time: 15.93 ms
    "wall_ms": [
        re.compile(r"[Ww]all(?:\s*\w+)?\s*[:=]?\s*(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>ms|s)?", re.I),
        re.compile(r"decode.*?(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>ms|s)", re.I),
    ],
    # Match TPOT like:  TPOT: 0.512 ms
    "tpot_ms_per_token": [
        re.compile(r"[Tt][Pp][Oo][Tt]\s*[:=]?\s*(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>ms|s)?", re.I),
        re.compile(r"time per output token\s*[:=]?\s*(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>ms|s)?", re.I),
    ],
    # Throughput like: throughput: 1234.5 tokens/s
    "throughput_tokens_per_s": [
        re.compile(r"[Tt]hroughput\s*[:=]?\s*(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>tok(?:en)?s?\s*/\s*s)?", re.I),
        re.compile(r"tok(?:en)?s?/s\s*[:=]?\s*(?P<val>\d+(?:\.\d+)?)", re.I),
    ],
    "latency_p50_ms": [
        re.compile(r"p50\s*[:=]?\s*(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>ms|s)?", re.I),
    ],
    "latency_p99_ms": [
        re.compile(r"p99\s*[:=]?\s*(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>ms|s)?", re.I),
    ],
}


def convert_to_ms(value: float, unit: Optional[str]) -> float:
    if not unit:
        return value
    unit = unit.lower()
    if "s" in unit and "ms" not in unit:
        return value * 1000.0
    return value


def parse_log(log_path: Path) -> dict:
    if not log_path.exists():
        raise FileNotFoundError(f"Log file not found: {log_path}")

    text = log_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    metrics = {
        "wall_ms": None,
        "tpot_ms_per_token": None,
        "throughput_tokens_per_s": None,
        "latency_p50_ms": None,
        "latency_p99_ms": None,
    }
    evidence = {k: None for k in metrics}

    for line in lines:
        for metric, patterns in PATTERNS.items():
            if metrics[metric] is not None:
                continue
            for pattern in patterns:
                m = pattern.search(line)
                if m:
                    val = float(m.group("val"))
                    unit = m.group("unit") if "unit" in m.groupdict() else None
                    if metric in ("wall_ms", "tpot_ms_per_token", "latency_p50_ms", "latency_p99_ms"):
                        val = convert_to_ms(val, unit)
                    metrics[metric] = val
                    evidence[metric] = line.strip()
                    break

    # Derive TPOT from wall_ms if only throughput is present: TPOT = 1000 / throughput
    if metrics["tpot_ms_per_token"] is None and metrics["throughput_tokens_per_s"]:
        metrics["tpot_ms_per_token"] = 1000.0 / metrics["throughput_tokens_per_s"]

    return {
        "source_log": str(log_path),
        "line_count": len(lines),
        "metrics": metrics,
        "evidence": evidence,
        "raw_snippets": [line.strip() for line in lines if any(kw in line.lower() for kw in [
            "wall", "tpot", "throughput", "latency", "time", "token/s", "ms"
        ])][:20],
    }


def main():
    parser = argparse.ArgumentParser(description="Parse xlite/vLLM performance log to metrics JSON")
    parser.add_argument("log", type=Path, help="Path to the performance log file")
    parser.add_argument("-o", "--output", type=Path, help="Output JSON path")
    args = parser.parse_args()

    report = parse_log(args.log)

    out_text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(out_text, encoding="utf-8")
        print(f"Metrics written to: {args.output}")
    else:
        print(out_text)


if __name__ == "__main__":
    main()
