#!/usr/bin/env python3
"""Extract a simplified execution timeline from an opencode session.

Runs `opencode export <sessionID>` and produces a compact JSON that the
report-generating LLM can consume to build an honest workflow_trace — no
more "LLM writes the trace from memory".

Usage:
    python3 extract_workflow.py                       # auto-detect session for cwd
    python3 extract_workflow.py --session ses_xxx     # explicit session ID
    python3 extract_workflow.py --cwd /path/to/dir    # match session for given dir
    python3 extract_workflow.py --output timeline.json

Output JSON schema (simplified for LLM consumption):
{
  "session_id": "...",
  "title": "...",
  "directory": "...",
  "agent": "...",
  "model": "...",
  "start_time": "ISO8601",
  "turns": [
    {
      "turn": 1,
      "role": "user"|"assistant",
      "text": "...",                    # user query or assistant say-text (truncated)
      "thought": "...",                 # reasoning excerpt (assistant only, truncated)
      "start_time": "ISO8601",
      "end_time": "ISO8601",
      "tools": [
        {
          "tool_name": "bash",
          "title": "wc -l log.txt",    # command or short title
          "input_summary": { ... },    # truncated/summarized input
          "output_preview": "...",     # first N chars of output
          "output_truncated": true,
          "status": "completed"|"failed",
          "exit_code": 0,
          "duration_ms": 123,
          "start_time": "ISO8601"
        }
      ]
    }
  ]
}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# --- Truncation knobs -----------------------------------------------------

MAX_TEXT_LEN = 800          # assistant say-text / user message
MAX_THOUGHT_LEN = 600       # reasoning excerpt per turn
MAX_TOOL_OUTPUT = 1200      # tool output preview chars
MAX_TOOL_INPUT_STR = 300    # string-valued input params (commands, file paths)

# Chinese-friendly timezone (UTC+8) for output timestamps
CST = timezone(timedelta(hours=8))


def ms_to_iso(ms: int | float | None, tz: timezone = CST) -> str | None:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=tz).isoformat(timespec="seconds")
    except (OSError, ValueError, OverflowError):
        return None


def truncate(s: str, limit: int) -> str:
    if not isinstance(s, str):
        s = str(s)
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n... (truncated, {len(s) - limit} more chars)"


def summarize_input(tool_name: str, inp: Any) -> Any:
    """Return a JSON-safe summary of tool input, truncating long strings."""
    if inp is None:
        return None
    if isinstance(inp, str):
        return truncate(inp, MAX_TOOL_INPUT_STR)
    if isinstance(inp, (int, float, bool)):
        return inp
    if isinstance(inp, list):
        return [summarize_input(tool_name, v) for v in inp[:10]]
    if isinstance(inp, dict):
        out: dict[str, Any] = {}
        for k, v in inp.items():
            if isinstance(v, str):
                out[k] = truncate(v, MAX_TOOL_INPUT_STR)
            else:
                out[k] = summarize_input(tool_name, v)
        return out
    return str(inp)[:MAX_TOOL_INPUT_STR]


def extract_tool_title(tool_name: str, state: dict[str, Any]) -> str:
    """Best-effort human-readable title for a tool call."""
    # Some tools carry an explicit title
    title = state.get("title") or ""
    if title and isinstance(title, str) and title.strip():
        return title.strip()

    inp = state.get("input", {}) or {}
    if tool_name == "bash":
        cmd = inp.get("command", "") if isinstance(inp, dict) else ""
        if isinstance(cmd, str):
            return cmd.strip().split("\n")[0][:200]
    if tool_name in ("read", "write", "edit", "delete"):
        fp = inp.get("file_path") or inp.get("filePath") or ""
        return f"{tool_name}: {fp}" if fp else tool_name
    if tool_name == "glob":
        pat = inp.get("pattern", "") if isinstance(inp, dict) else ""
        return f"glob: {pat}" if pat else tool_name
    if tool_name == "grep":
        pat = inp.get("pattern", "") if isinstance(inp, dict) else ""
        return f"grep: {pat}" if pat else tool_name
    if tool_name == "browser_use":
        desc = inp.get("description", "") if isinstance(inp, dict) else ""
        return f"browser: {desc}" if desc else tool_name
    if tool_name == "skill":
        # skill call input usually has a skill name
        if isinstance(inp, dict):
            name = inp.get("name") or inp.get("skill_name") or inp.get("skill") or ""
            if name:
                return f"skill: {name}"
    if tool_name.startswith("crash-feature-matcher_"):
        return tool_name.replace("crash-feature-matcher_", "matcher.")
    if tool_name.startswith("witty_log_detection_"):
        return tool_name.replace("witty_log_detection_", "log-detect.")
    return tool_name


def run_export(session_id: str) -> dict[str, Any]:
    """Run `opencode export` and return parsed JSON."""
    import tempfile
    # Write to a temp file to avoid subprocess pipe encoding issues with large outputs
    with tempfile.NamedTemporaryFile(prefix="opencode-export-", suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with open(tmp_path, "wb") as out_f:
            proc = subprocess.run(
                ["opencode", "export", session_id],
                stdout=out_f,
                stderr=subprocess.PIPE,
                timeout=60,
            )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
            raise RuntimeError(f"opencode export failed (exit {proc.returncode}): {err[:500]}")
        raw = tmp_path.read_text(encoding="utf-8", errors="replace")
    finally:
        tmp_path.unlink(missing_ok=True)

    # opencode prints "Exporting session: <id>\n" before the JSON body
    nl = raw.find("\n{")
    if nl >= 0:
        raw = raw[nl + 1:]
    elif raw.startswith("Exporting"):
        idx = raw.find("{")
        if idx > 0:
            raw = raw[idx:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Failed to parse opencode export JSON: {exc}\n"
            f"First 200 chars: {raw[:200]}"
        ) from exc


def detect_session(cwd: str) -> str:
    """Find the most recently updated session for the given working directory."""
    import tempfile
    with tempfile.NamedTemporaryFile(prefix="opencode-sessions-", suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with open(tmp_path, "wb") as out_f:
            proc = subprocess.run(
                ["opencode", "session", "list", "--format", "json", "-n", "20"],
                stdout=out_f,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
            raise RuntimeError(f"opencode session list failed: {err[:500]}")
        sessions = json.loads(tmp_path.read_text(encoding="utf-8", errors="replace"))
    finally:
        tmp_path.unlink(missing_ok=True)
    # Resolve cwd to absolute
    cwd_abs = str(Path(cwd).resolve())
    # Filter sessions that match this directory, pick most recently updated
    matches = [s for s in sessions if s.get("directory") == cwd_abs]
    if not matches:
        # Fallback: most recent session overall
        matches = sessions
    if not matches:
        raise RuntimeError(f"No opencode sessions found (cwd={cwd_abs})")
    matches.sort(key=lambda s: s.get("updated", 0), reverse=True)
    return matches[0]["id"]


def build_timeline(exported: dict[str, Any]) -> dict[str, Any]:
    """Convert raw opencode export into a compact, LLM-friendly timeline."""
    info = exported.get("info", {})
    messages = exported.get("messages", []) or []

    turns: list[dict[str, Any]] = []
    turn_idx = 0

    for msg in messages:
        minfo = msg.get("info", {}) or {}
        role = minfo.get("role", "?")
        parts = msg.get("parts", []) or []
        msg_time = minfo.get("time", {}) or {}
        msg_start_ms = msg_time.get("created")
        msg_end_ms = msg_time.get("completed") or msg_time.get("created")

        # Split parts by type
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_parts: list[dict[str, Any]] = []

        for p in parts:
            ptype = p.get("type", "")
            if ptype == "text":
                t = p.get("text", "")
                if t:
                    text_parts.append(t)
            elif ptype == "reasoning":
                t = p.get("text", "")
                if t:
                    reasoning_parts.append(t)
            elif ptype == "tool":
                tool_parts.append(p)
            # step-start, step-finish, patch are skipped for LLM brevity

        # Build tools list
        tools_out: list[dict[str, Any]] = []
        for tp in tool_parts:
            tool_name = tp.get("tool", "unknown")
            state = tp.get("state", {}) or {}
            inp = state.get("input")
            out = state.get("output", "") or ""
            meta = state.get("metadata", {}) or {}
            t_time = tp.get("time", {}) or {}
            t_start = t_time.get("start")
            t_end = t_time.get("end")
            duration_ms = None
            if t_start and t_end:
                duration_ms = t_end - t_start

            out_str = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
            out_truncated = len(out_str) > MAX_TOOL_OUTPUT
            out_preview = truncate(out_str, MAX_TOOL_OUTPUT)

            tools_out.append({
                "tool_name": tool_name,
                "title": extract_tool_title(tool_name, state),
                "input_summary": summarize_input(tool_name, inp),
                "output_preview": out_preview,
                "output_truncated": out_truncated,
                "status": state.get("status", "unknown"),
                "exit_code": meta.get("exit") if isinstance(meta, dict) else None,
                "duration_ms": duration_ms,
                "start_time": ms_to_iso(t_start),
            })

        # Combine text and reasoning
        combined_text = "\n".join(text_parts).strip()
        combined_thought = "\n".join(reasoning_parts).strip()

        turn: dict[str, Any] = {
            "turn": turn_idx + 1,
            "role": role,
            "text": truncate(combined_text, MAX_TEXT_LEN) if combined_text else None,
            "thought": truncate(combined_thought, MAX_THOUGHT_LEN) if combined_thought else None,
            "start_time": ms_to_iso(msg_start_ms),
            "end_time": ms_to_iso(msg_end_ms),
            "tools": tools_out if tools_out else None,
        }
        # Prune None fields for readability
        turn = {k: v for k, v in turn.items() if v is not None}
        turns.append(turn)
        turn_idx += 1

    session_start = ms_to_iso(info.get("time", {}).get("created")) if isinstance(info.get("time"), dict) else None

    return {
        "session_id": info.get("id"),
        "title": info.get("title"),
        "directory": info.get("directory"),
        "agent": info.get("agent"),
        "model": (info.get("model") or {}).get("id") if isinstance(info.get("model"), dict) else None,
        "start_time": session_start,
        "turn_count": len(turns),
        "turns": turns,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract a simplified execution timeline from an opencode session."
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="Session ID to export. If omitted, auto-detects the latest session for --cwd.",
    )
    parser.add_argument(
        "--cwd",
        type=str,
        default=os.getcwd(),
        help="Working directory to match sessions against (default: current directory).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write output to this file instead of stdout.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="Pretty-print JSON output (default).",
    )
    args = parser.parse_args()

    try:
        session_id = args.session or detect_session(args.cwd)
        exported = run_export(session_id)
        timeline = build_timeline(exported)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    out_str = json.dumps(timeline, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        args.output.write_text(out_str, encoding="utf-8")
        print(f"Wrote timeline ({timeline['turn_count']} turns) to {args.output}", file=sys.stderr)
    else:
        print(out_str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
