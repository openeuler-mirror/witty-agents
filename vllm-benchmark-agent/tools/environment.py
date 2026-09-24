#!/usr/bin/env python3
"""System environment check tool.

Usage:
    environment.py check [--mock]

Emits structured JSON describing the host (openEuler) system.
"""

from __future__ import annotations

import argparse
import sys

from common import ok, err, emit, run, read_text, to_int

MOCK = {
    "os": {"name": "openEuler", "version": "24.03 (LTS-SP3)"},
    "kernel": "6.6.0-xxx",
    "arch": "aarch64",
    "cpu": {"cores": 192, "model": "Kunpeng-920"},
    "memory": {"total_mb": 1048576, "available_mb": 900000},
    "disk": {"mount": "/", "total_gb": 2000, "used_gb": 500},
}


def _os_release():
    raw = read_text("/etc/os-release")
    if not raw:
        raw = read_text("/etc/openEuler-release")
    name = version = None
    for line in raw.splitlines():
        if line.startswith("NAME="):
            name = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("VERSION="):
            version = line.split("=", 1)[1].strip().strip('"')
    if name is None and raw:
        name = raw.strip().splitlines()[0]
    return {"name": name, "version": version}


def _cpu():
    rc, out, _ = run(["nproc"], timeout=10)
    cores = to_int(out.strip()) if rc == 0 else None
    model = None
    rc2, out2, _ = run(["lscpu"], timeout=10)
    if rc2 == 0:
        for line in out2.splitlines():
            if "Model name" in line:
                model = line.split(":", 1)[1].strip()
                break
    return {"cores": cores, "model": model}


def _memory():
    rc, out, _ = run(["free", "-b"], timeout=10)
    if rc != 0:
        return {}
    lines = out.splitlines()
    if len(lines) < 2:
        return {}
    parts = lines[1].split()
    #              total       used        free        shared  buff/cache available
    total = to_int(parts[1]) if len(parts) > 1 else None
    avail = to_int(parts[6]) if len(parts) > 6 else None
    return {
        "total_mb": total // 1024 // 1024 if total else None,
        "available_mb": avail // 1024 // 1024 if avail else None,
    }


def _disk():
    rc, out, _ = run(["df", "-B1G", "/"], timeout=10)
    if rc != 0:
        return {}
    lines = out.splitlines()
    if len(lines) < 2:
        return {}
    parts = lines[1].split()
    return {
        "mount": parts[5] if len(parts) > 5 else "/",
        "total_gb": to_int(parts[1]),
        "used_gb": to_int(parts[2]),
    }


def check(mock=False):
    if mock:
        return ok(MOCK)
    rc, kern, _ = run(["uname", "-r"], timeout=10)
    rc2, arch, _ = run(["uname", "-m"], timeout=10)
    data = {
        "os": _os_release(),
        "kernel": kern.strip() if rc == 0 else None,
        "arch": arch.strip() if rc2 == 0 else None,
        "cpu": _cpu(),
        "memory": _memory(),
        "disk": _disk(),
    }
    return ok(data)


def main():
    parser = argparse.ArgumentParser(description="Environment check tool")
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
