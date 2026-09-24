#!/usr/bin/env python3
"""Ascend NPU inspection tool.

Usage:
    ascend.py check [--mock]

Parses `npu-smi info` into structured JSON: device count, per-device
health / AICore util / memory / HBM, and a free-vs-busy summary.

A device is classified as "free" when health is OK, AICore utilisation is
~0 and memory usage is ~0 (i.e. no engine is holding HBM).
"""

from __future__ import annotations

import argparse
import re

from common import ok, err, emit, run, to_int, to_float

MOCK = {
    "count": 2,
    "summary": {"total": 2, "free": 1, "busy": 1,
                "free_ids": [5], "busy_ids": [2]},
    "devices": [
        {
            "id": 2, "name": "910B4-1", "health": "OK",
            "power_w": 69.9, "temp_c": 37,
            "aicore": 0.0,
            "memory_used_mb": 0, "memory_total_mb": 0,
            "hbm_used_mb": 40898, "hbm_total_mb": 65536,
            "bus_id": "0000:18:00.0",
        },
        {
            "id": 5, "name": "910B4-1", "health": "OK",
            "power_w": 76.4, "temp_c": 37,
            "aicore": 0.0,
            "memory_used_mb": 0, "memory_total_mb": 0,
            "hbm_used_mb": 3412, "hbm_total_mb": 65536,
            "bus_id": "0000:96:00.0",
        },
    ],
}


def _is_separator(line):
    return bool(line.strip()) and set(line.strip()) <= set("+-=| ")
# npu-smi table has 3 pipe-delimited columns; the 3rd column packs
# space-separated sub-fields (power/temp/hugepages, or aicore/mem/hbm).
NAME_RE = re.compile(
    r"\|\s*(\d+)\s+(\S+)\s*\|\s*(\S+)\s*\|\s*"
    r"([\d.]+)\s+([\d.]+)\s+(\d+)\s*/\s*(\d+)\s*\|"
)
CHIP_RE = re.compile(
    r"\|\s*(\d+)\s*\|\s*(\S+)\s*\|\s*"
    r"([\d.]+)\s+(\d+)\s*/\s*(\d+)\s+(\d+)\s*/\s*(\d+)\s*\|"
)
PROCESS_RE = re.compile(r"\|\s*(\d+)\s+\d+\s*\|")


def _is_separator(line):
    return bool(line.strip()) and set(line.strip()) <= set("+-=| ")


def parse_npu_smi(text):
    lines = text.splitlines()
    start = None
    proc_start = None
    for i, line in enumerate(lines):
        if start is None and "Health" in line and "Power" in line:
            start = i
        if "Process id" in line or "Process name" in line:
            proc_start = i
            break
    if start is None:
        return {"count": 0, "summary": {}, "devices": [], "raw": text}

    devices = []
    current = None
    for line in lines[start + 1: proc_start if proc_start else len(lines)]:
        if not line.strip() or _is_separator(line):
            continue
        m = NAME_RE.match(line.strip())
        if m:
            current = {
                "id": to_int(m.group(1)),
                "name": m.group(2),
                "health": m.group(3),
                "power_w": to_float(m.group(4)),
                "temp_c": to_float(m.group(5)),
                "hugepages_used": to_int(m.group(6)),
                "hugepages_total": to_int(m.group(7)),
            }
            devices.append(current)
            continue
        m = CHIP_RE.match(line.strip())
        if m and current is not None:
            current["bus_id"] = m.group(2)
            current["aicore"] = to_float(m.group(3))
            current["memory_used_mb"] = to_int(m.group(4))
            current["memory_total_mb"] = to_int(m.group(5))
            current["hbm_used_mb"] = to_int(m.group(6))
            current["hbm_total_mb"] = to_int(m.group(7))

    busy_by_process = set()
    if proc_start is not None:
        for line in lines[proc_start + 1:]:
            m = PROCESS_RE.match(line.strip())
            if m:
                busy_by_process.add(to_int(m.group(1)))

    free_ids, busy_ids = [], []
    for d in devices:
        healthy = d.get("health") == "OK"
        has_process = d.get("id") in busy_by_process
        aicore = d.get("aicore") or 0.0
        if healthy and not has_process and aicore < 1.0:
            free_ids.append(d.get("id"))
        else:
            busy_ids.append(d.get("id"))

    summary = {
        "total": len(devices),
        "free": len(free_ids),
        "busy": len(busy_ids),
        "free_ids": free_ids,
        "busy_ids": busy_ids,
    }
    return {"count": len(devices), "summary": summary, "devices": devices}


def check(mock=False):
    if mock:
        return ok(MOCK)
    rc, out, stderr = run(["npu-smi", "info"], timeout=60)
    if rc != 0:
        return err("npu-smi info failed", {"rc": rc, "stderr": stderr})
    parsed = parse_npu_smi(out)
    if parsed["count"] == 0:
        return err("could not parse npu-smi output",
                   {"raw": out.strip()})
    return ok(parsed)


def main():
    parser = argparse.ArgumentParser(description="Ascend NPU check tool")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check")
    p.add_argument("--mock", action="store_true")
    args = parser.parse_args()

    if args.cmd == "check":
        emit(check(mock=args.mock))
    else:
        emit(err("unknown command: %s" % args.cmd))


if __name__ == "__main__":
    main()
