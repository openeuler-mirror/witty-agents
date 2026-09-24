"""Shared helpers for vLLM benchmark tools.

Every tool is a CLI that emits a single JSON object to stdout and exits
0 on success / non-zero on failure:

    {"ok": true, "data": {...}}
    {"ok": false, "error": "...", "detail": {...}}

Keeping output as structured JSON (instead of raw logs) minimises the tokens
the LLM has to consume.
"""

from __future__ import annotations

import json
import os
import subprocess
import signal
import sys
import time


def ok(data=None):
    return {"ok": True, "data": data if data is not None else {}}


def err(message, detail=None):
    out = {"ok": False, "error": message}
    if detail is not None:
        out["detail"] = detail
    return out


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False, default=str))
    sys.exit(0 if payload.get("ok") else 1)


def append_log(path, text):
    if not path:
        return
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "a") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
    except OSError:
        pass


def write_json_atomic(path, obj):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def run(cmd, timeout=120, check=False, env=None, log_path=None):
    """Run a command (list form). Returns (rc, stdout, stderr).

    `env` optionally overrides the child process environment.
    `log_path` optionally appends command + stdout + stderr to a log file.
    """
    if isinstance(cmd, str):
        cmd = cmd.split()
    proc = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env, start_new_session=True)
        deadline = time.monotonic() + timeout
        while True:
            cancel = os.environ.get("BENCHMARK_CANCEL_PATH")
            if cancel and os.path.exists(cancel):
                raise KeyboardInterrupt("benchmark cancelled")
            try:
                out, stderr = proc.communicate(timeout=min(0.5, max(0.01, deadline - time.monotonic())))
                rc = proc.returncode
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise
    except subprocess.TimeoutExpired:
        rc, out, stderr = -1, "", "command timed out after %ds" % timeout
    except FileNotFoundError as e:
        rc, out, stderr = -1, "", "command not found: %s" % e
    finally:
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
    if log_path:
        append_log(log_path, "[%s] $ %s\n%s\n%s" % (
            now_iso(), " ".join(str(c) for c in cmd), out, stderr))
    return rc, out, stderr


def read_text(path, default=""):
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return default


def to_int(value):
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def to_float(value):
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def duration_sec(start):
    return round(time.time() - start, 3)
