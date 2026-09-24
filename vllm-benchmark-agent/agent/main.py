#!/usr/bin/env python3
"""Deterministic benchmark runner.

run freezes YAML + explicit overrides and advances to ANALYZE without normal
confirmation gates. Only blocked requirements enter WAIT_USER_DECISION;
resume applies the user's exception decision and continues the saved run.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import uuid
import json
import os
import signal
import shutil
import subprocess
import sys
import threading
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(PROJECT_ROOT, "tools")
# All mutable run data lives outside the source tree, under the user's home:
#   <DATA_ROOT>/state/   state.json, current_run
#   <DATA_ROOT>/runs/<run_id>/   state.json, progress.json, tasks.json,
#                                run.log, serve.log, cancel, results/,
#                                execution.lock (per-run command lock)
#   <DATA_ROOT>/locks/   npu_<physical_id>.lock (per-NPU ownership)
#   <DATA_ROOT>/reports/   report_<run_id>.json
# Runs are independent; the only mutual exclusion is per-NPU device locks.
# Override with VLLM_BENCHMARK_DATA_DIR.
DATA_ROOT = os.environ.get(
    "VLLM_BENCHMARK_DATA_DIR", os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "witty-agents", "vllm-benchmark")
)
STATE_DIR = os.path.join(DATA_ROOT, "state")
STATE_PATH = os.path.join(STATE_DIR, "state.json")
DEFAULT_CONFIG = os.environ.get("VLLM_BENCHMARK_CONFIG", os.path.join(os.getcwd(), "benchmark.yaml"))
RUNS_DIR = os.path.join(DATA_ROOT, "runs")
CURRENT_RUN_PATH = os.path.join(STATE_DIR, "current_run")
LOCKS_DIR = os.path.join(DATA_ROOT, "locks")
# Mirrored into the project tree so external observers (TUI plugins)
# can locate the active run without knowing DATA_ROOT.
UI_POINTER_PATH = os.path.join(os.getcwd(), ".vllm-benchmark", "current.json")
# Also mirror under the user's home. opencode may be started from any directory
# (its project "worktree" can be the home dir or "/"), so a project-local
# pointer alone is not always discoverable by a TUI plugin.
UI_POINTER_HOME = os.path.join(os.path.expanduser("~"), ".vllm-benchmark", "current.json")
UI_POINTER_PATHS = (UI_POINTER_PATH, UI_POINTER_HOME)

sys.path.insert(0, PROJECT_ROOT)

from tools.common import ok, err, emit, run, now_iso, append_log, write_json_atomic, read_json  # noqa: E402
from tools import lock as device_lock  # noqa: E402
from agent.workflow import Workflow  # noqa: E402
from agent.prompt import render  # noqa: E402


def _wf():
    return Workflow(os.path.join(_run_dir(), "state.json") if _current_run_id() else STATE_PATH)


# Set by the CLI entrypoint when `--run-id` selects a non-default run, so every
# helper (state, run dir, tasks, cancel marker) resolves to that run.
_ACTIVE_RUN_OVERRIDE = None


def _current_run_id():
    if _ACTIVE_RUN_OVERRIDE:
        return _ACTIVE_RUN_OVERRIDE
    try:
        with open(CURRENT_RUN_PATH, "r") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _run_dir(run_id=None):
    return os.path.join(RUNS_DIR, run_id or _current_run_id() or "default")


def _progress_path(run_id=None):
    return os.path.join(_run_dir(run_id), "progress.json")


def _tasks_path(run_id=None):
    return os.path.join(_run_dir(run_id), "tasks.json")


TASKS = (
    ("config", "读取并校验配置"),
    ("environment", "环境检查"),
    ("container", "确保 Docker 容器运行"),
    ("service", "探测 / 复用 vLLM 服务"),
    ("launch", "启动 vLLM 服务"),
    ("health", "等待 vLLM 健康检查"),
    ("benchmark", "Benchmark"),
    ("metrics", "收集并校验指标"),
    ("analysis", "生成分析报告"),
    ("cleanup", "关闭服务"),
)


def _read_tasks(run_id=None):
    return read_json(_tasks_path(run_id), {}) or {}


def _write_tasks(tasks):
    tasks["run_id"] = _current_run_id()
    tasks["updated_at"] = now_iso()
    tasks["updated_ts"] = time.time()
    write_json_atomic(_tasks_path(), tasks)


def _tag(value):
    """Make a numeric level safe to embed in a task id."""
    return str(value).replace(".", "_").replace("-", "m")


def _round_specs(bench):
    """Resolve the ordered benchmark rounds from the frozen config.

    `benchmark.request_rates` (a controlled QPS sweep) takes precedence over
    `benchmark.concurrency`. Every spec carries the axis it was swept on so the
    report and plots can label the x-axis correctly.
    """
    bench = bench or {}
    rates = bench.get("request_rates")
    if rates:
        return [
            {"id": "benchmark.q%s" % _tag(rate), "label": "QPS %s" % rate,
             "axis": "request_rate", "value": rate,
             "concurrency": bench.get("max_concurrency"),
             "request_rate": rate}
            for rate in rates
        ]
    return [
        {"id": "benchmark.c%s" % _tag(level), "label": "并发 %s" % level,
         "axis": "concurrency", "value": level, "concurrency": level,
         "request_rate": bench.get("request_rate")}
        for level in (bench.get("concurrency") or [])
    ]


def _init_tasks(config=None):
    rounds = _round_specs((config or {}).get("benchmark"))
    tasks = {
        "tasks": [{"id": task_id, "label": label, "status": "pending"}
                  for task_id, label in TASKS],
        "benchmark_rounds": [
            {"id": spec["id"], "concurrency": spec["value"],
             "request_rate": spec["request_rate"], "axis": spec["axis"],
             "label": spec["label"], "status": "pending"}
            for spec in rounds
        ],
    }
    _write_tasks(tasks)
    return tasks


def _update_task(task_id, status=None, **fields):
    tasks = _read_tasks() or _init_tasks()
    candidates = tasks.get("tasks", []) + tasks.get("benchmark_rounds", [])
    for task in candidates:
        if task.get("id") == task_id:
            if status is not None:
                task["status"] = status
            task.update(fields)
            task["updated_at"] = now_iso()
            _write_tasks(tasks)
            return


def _mark_blocked(reason):
    tasks = _read_tasks()
    if not tasks:
        return
    for task in tasks.get("tasks", []) + tasks.get("benchmark_rounds", []):
        if task.get("status") == "running":
            task.update(status="blocked", reason=reason, updated_at=now_iso())
    _write_tasks(tasks)


def _task_icon(status):
    return {"completed": "✓", "running": "→", "blocked": "!",
            "failed": "✗", "cancelled": "-", "skipped": "-"}.get(status, " ")


def render_tasks(tasks):
    """Render a stable, human-readable snapshot without terminal control codes."""
    if not tasks:
        return "没有活动任务。"
    lines = ["vLLM benchmark  run=%s" % (tasks.get("run_id") or "unknown")]
    for task in tasks.get("tasks", []):
        suffix = ""
        if task.get("elapsed_sec") is not None:
            suffix += "  已运行 %ss" % int(task["elapsed_sec"])
        if task.get("attempt"):
            suffix += "  尝试 %s/%s" % (task["attempt"], task.get("total_attempts", "?"))
        if task.get("reason"):
            suffix += "  %s" % task["reason"]
        lines.append("[%s] %s%s" % (_task_icon(task.get("status")), task["label"], suffix))
        if task["id"] == "benchmark":
            for round_ in tasks.get("benchmark_rounds", []):
                detail = ""
                if round_.get("elapsed_sec") is not None:
                    detail += "  已运行 %ss" % int(round_["elapsed_sec"])
                if round_.get("running") is not None or round_.get("waiting") is not None:
                    detail += "  running=%s waiting=%s" % (round_.get("running", "?"), round_.get("waiting", "?"))
                lines.append("    [%s] %s%s" % (_task_icon(round_.get("status")), round_["label"], detail))
    return "\n".join(lines)


class _TaskRenderer:
    """Live stderr renderer; JSON results continue to use stdout."""
    def __init__(self, enabled):
        self.enabled = enabled
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        if not self.enabled:
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        last = None
        while not self.stop.wait(0.5):
            snapshot = render_tasks(_read_tasks())
            if snapshot == last:
                continue
            if sys.stderr.isatty():
                sys.stderr.write("\x1b[2J\x1b[H" + snapshot + "\n")
            else:
                sys.stderr.write("[progress]\n" + snapshot + "\n")
            sys.stderr.flush()
            last = snapshot

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        if self.enabled:
            sys.stderr.write(render_tasks(_read_tasks()) + "\n")
            sys.stderr.flush()


def _log_path(run_id=None):
    return os.path.join(_run_dir(run_id), "run.log")


def _ensure_data_root():
    """Create the complete external data layout before any run writes state."""
    for directory in (DATA_ROOT, STATE_DIR, RUNS_DIR, LOCKS_DIR,
                      os.path.join(DATA_ROOT, "reports")):
        os.makedirs(directory, mode=0o700, exist_ok=True)


def _merge_move(source, destination):
    """Move a legacy data directory without overwriting existing destination files."""
    if not os.path.exists(source):
        return []
    os.makedirs(destination, mode=0o700, exist_ok=True)
    moved = []
    for name in os.listdir(source):
        origin = os.path.join(source, name)
        target = os.path.join(destination, name)
        if os.path.exists(target):
            target = os.path.join(destination, "%s.legacy-%s" % (name, int(time.time())))
        shutil.move(origin, target)
        moved.append(target)
    os.rmdir(source)
    return moved


def cmd_migrate_data(args):
    """Move data generated by older versions out of the source tree."""
    _ensure_data_root()
    moved = []
    legacy_state = os.path.join(PROJECT_ROOT, ".benchmark")
    moved += _merge_move(os.path.join(legacy_state, "runs"), RUNS_DIR)
    moved += _merge_move(os.path.join(legacy_state, "results"), os.path.join(DATA_ROOT, "legacy-results"))
    moved += _merge_move(legacy_state, STATE_DIR)
    moved += _merge_move(os.path.join(PROJECT_ROOT, "reports"), os.path.join(DATA_ROOT, "reports"))
    return ok({"data_root": DATA_ROOT, "moved": moved})


def _read_progress(run_id=None):
    return read_json(_progress_path(run_id), {}) or {}


def _write_ui_pointer():
    """Best-effort mirror of the active run's file locations into the project.

    The runner keeps all mutable data under DATA_ROOT, which is outside the
    source tree.  A TUI observer only knows the project worktree, so we drop a
    tiny pointer file next to the config.  Never raises: a failed mirror must
    not affect the benchmark.
    """
    run_id = _current_run_id()
    if not run_id:
        return
    # Never mirror a sandboxed/test data root into the real project tree: the
    # pointer must describe the run under DATA_ROOT, nothing else.
    try:
        run_dir = os.path.abspath(_run_dir(run_id))
        data_root = os.path.abspath(DATA_ROOT)
        if os.path.commonpath([run_dir, data_root]) != data_root:
            return
    except ValueError:
        return
    payload = {
        "data_root": DATA_ROOT,
        "run_id": run_id,
        "progress": _progress_path(run_id),
        "tasks": _tasks_path(run_id),
        "updated_at": now_iso(),
    }
    for path in UI_POINTER_PATHS:
        try:
            write_json_atomic(path, payload)
        except OSError:
            pass


def _write_progress(**fields):
    try:
        data = _read_progress()
        data.update(fields)
        data["run_id"] = _current_run_id()
        data["updated_at"] = now_iso()
        data["updated_ts"] = time.time()
        write_json_atomic(_progress_path(), data)
    except OSError:
        pass
    _write_ui_pointer()


def _append_log(text):
    append_log(_log_path(), text)


def _start_new_run():
    run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    os.makedirs(_run_dir(run_id), exist_ok=True)
    with open(CURRENT_RUN_PATH + ".tmp", "w") as f:
        f.write(run_id)
    os.replace(CURRENT_RUN_PATH + ".tmp", CURRENT_RUN_PATH)
    _write_progress(run_id=run_id, state="IDLE", stage="init",
                    substage="run_created", started_at=now_iso())
    return run_id


def _create_run():
    """Create a brand-new run id without touching any previous run."""
    _ensure_data_root()
    run_id = _start_new_run()
    wf = _wf()
    wf.reset()
    wf.set_meta(run_id=run_id)
    _init_tasks()
    _set_cancel_path()
    return ok({"state": wf.current(), "run_id": run_id})


def _run_state(run_id):
    data = read_json(os.path.join(RUNS_DIR, run_id, "state.json"), {}) or {}
    return data.get("state")


def _device_ids(cfg):
    return [int(x) for x in ((cfg or {}).get("vllm", {}) or {}).get("device") or []]


def _lock_is_active(meta, probe_data, current_run):
    """A lock is active while its run is unfinished OR its service holds the card.

    The second clause is the important one: a finished run deliberately keeps
    its vLLM service resident, so run state alone would wrongly free the NPU.
    """
    other = meta.get("run_id")
    if not other or other == current_run:
        return False
    state = _run_state(other)
    if state is None:
        # The owning run directory is gone: the lock is orphaned, not active.
        return False
    if state not in ("DONE", "FAILED", "CANCELLED"):
        return True
    busy = {int(x) for x in (probe_data or {}).get("npu_busy_physical") or []}
    owned = {int(x) for x in (meta.get("devices") or [])}
    if not (busy & owned):
        return False
    # A terminal run may leave an already-loaded service holding the card. When
    # the newcomer's probe confirms a matching service (same port/model/config)
    # on exactly the requested devices, the lock is a safe handoff candidate.
    probe = probe_data or {}
    if (probe.get("decision") in ("already_running", "loading")
            and probe.get("device_match")):
        return False
    return True


def _acquire_devices(wf, probe_data):
    """Claim the run's NPUs. Returns (acquired, holders)."""
    cfg = wf.meta.get("config") or {}
    run_id = _current_run_id()
    devices = _device_ids(cfg)
    previous = device_lock.snapshot(LOCKS_DIR, devices)
    details = {"port": (cfg.get("vllm", {}) or {}).get("port"),
               "container": (cfg.get("container", {}) or {}).get("name")}
    ok_, holders, acquired = device_lock.try_acquire(
        LOCKS_DIR, devices, run_id, pid=os.getpid(),
        is_active=lambda meta: _lock_is_active(meta, probe_data, run_id),
        details=details)
    if ok_:
        wf.set_meta(device_locks=acquired)
        handoff = [{"device": d, "from_run": m.get("run_id"),
                    "from_pid": m.get("pid")}
                   for d, m in (previous or {}).items()
                   if m and m.get("run_id") != run_id]
        if handoff:
            wf.set_meta(device_handoff=handoff)
            _append_log("[locks] took over %s from terminal run(s)\n" % handoff)
    return bool(ok_), holders


def _wait_for_resource(wf, holders, probe_data):
    issue = {"reason": "device_busy", "holders": holders,
             "requested": _device_ids(wf.meta.get("config") or {}),
             "evidence": probe_data, "resume_state": "PROBE_SERVICE"}
    wf.set_meta(issue=issue)
    _update_task("service", "blocked", reason="device_busy")
    wf.transition("waiting_resource")
    _write_progress(state=wf.current(), stage="waiting_resource", issue=issue)
    return ok({"state": wf.current(), "needs_user_decision": True, "issue": issue,
               "llm_prompt": render("WAIT_USER_DECISION", issue=issue)})


def _wait_for_device(wf, probe_data):
    issue = {"reason": "device_unhealthy", "evidence": probe_data,
             "resume_state": "PROBE_SERVICE"}
    wf.set_meta(issue=issue)
    _update_task("service", "blocked", reason="device_unhealthy")
    wf.transition("waiting_device")
    _write_progress(state=wf.current(), stage="waiting_device", issue=issue)
    return ok({"state": wf.current(), "needs_user_decision": True, "issue": issue,
               "llm_prompt": render("WAIT_USER_DECISION", issue=issue)})


def call_tool(script, args, timeout=3600, log_path=None, progress=None):
    """Run a tools/*.py CLI and parse its JSON stdout."""
    cmd = [sys.executable, os.path.join(TOOLS_DIR, script)] + args
    if progress:
        _write_progress(**progress)
    rc, out, stderr = run(cmd, timeout=timeout, log_path=log_path)
    if progress is not None:
        _write_progress(rc=rc)
    try:
        payload = json.loads(out)
    except (ValueError, TypeError):
        return {"ok": False, "error": "tool returned invalid JSON",
                "detail": {"rc": rc, "stdout": out[-2000:], "stderr": stderr[-2000:]}}
    if not isinstance(payload, dict) or "ok" not in payload:
        return err("invalid tool payload", {"rc": rc})
    if rc != 0 and payload.get("ok"):
        return err("tool exited unsuccessfully", {"rc": rc, "payload": payload})
    return payload


def _load_config(path, validate=True):
    """Load benchmark.yaml via tools/config.py. Returns (cfg, error)."""
    payload = call_tool("config.py", ["show", "--config", path] +
                        ([] if validate else ["--unvalidated"]), timeout=30)
    if not payload.get("ok"):
        return None, payload
    return payload["data"]["config"], None


def _parse_ids(raw):
    """Parse NPU ids from a list or comma string into list[int]."""
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [x for x in raw.replace(" ", "").split(",") if x != ""]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = [raw]
    out = []
    for item in items:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _model_ref(cfg):
    model = (cfg or {}).get("model", {}) or {}
    return model.get("path") or model.get("name")


def _resolve_client_model(cfg, service):
    """Model id to send in client requests.

    Usually the configured path is served verbatim. When the service exposes
    the checkpoint under an alias (``--served-model-name``), the OpenAI API
    only accepts that alias, so use the id the service actually advertises.
    """
    explicit = ((cfg or {}).get("vllm", {}) or {}).get("served_model_name")
    if explicit:
        return explicit
    model = _model_ref(cfg)
    served = [s for s in ((service or {}).get("served_models") or []) if s]
    if not served:
        return model
    target = (model or "").rstrip("/")
    if any(s.rstrip("/") == target for s in served):
        return model
    return served[0]


def _emit(payload):
    emit(payload)


def cmd_init(args):
    """Always create a fresh run; a previous run is never reset or waited on."""
    return _create_run()


def _block(wf, reason, evidence=None, resume=None):
    resume = resume or wf.current()
    if wf.current() != "WAIT_USER_DECISION":
        wf.transition("block")
    issue = {"reason": reason, "evidence": evidence, "resume_state": resume}
    wf.set_meta(issue=issue)
    _mark_blocked(reason)
    _write_progress(state=wf.current(), stage="blocked", issue=issue)
    return {"ok": False, "error": reason, "detail": issue,
            "state": wf.current(), "needs_user_decision": True,
            "llm_prompt": render("WAIT_USER_DECISION", issue=issue)}


def _config_for_run(wf, args):
    from tools.config import normalize
    cfg = copy.deepcopy(wf.meta.get("config"))
    if cfg is None:
        cfg, failure = _load_config(getattr(args, "config", None) or DEFAULT_CONFIG, validate=False)
        if failure:
            return None, failure
    overrides = {
        "name": ("container", "name"), "container": ("container", "name"),
        "runtime": ("container", "runtime"), "model": ("model", "path"),
        "host": ("vllm", "host"), "port": ("vllm", "port"),
        "tensor_parallel_size": ("vllm", "tensor_parallel_size"),
        "max_model_len": ("vllm", "max_model_len"),
        "gpu_memory_utilization": ("vllm", "gpu_memory_utilization"),
        "extra_arg": ("vllm", "extra_args"), "num_prompts": ("benchmark", "requests"),
        "input_len": ("benchmark", "input_tokens"), "output_len": ("benchmark", "output_tokens"),
        "request_rate": ("benchmark", "request_rate"), "scrape_interval": ("metrics", "interval"),
    }
    previous = copy.deepcopy(cfg)
    runtime_options = copy.deepcopy(wf.meta.get("runtime_options", {}))
    for key in ("tokenizer", "local", "visible_devices", "timeout", "scrape_seconds", "health_retries", "health_wait"):
        value = getattr(args, key, None)
        if value is not None:
            runtime_options[key] = value
        elif key in runtime_options:
            setattr(args, key, runtime_options[key])
    for key in ("timeout", "scrape_seconds", "health_retries", "health_wait"):
        value = runtime_options.get(key)
        if value is not None and (type(value) is not int or value < (0 if key == "health_wait" else 1)):
            return None, err("invalid execution option", {"option": key, "value": value})
    wf.set_meta(runtime_options=runtime_options)
    for attr, (section, key) in overrides.items():
        value = getattr(args, attr, None)
        if value is not None:
            cfg[section][key] = value
    try:
        if getattr(args, "device", None) is not None:
            cfg["vllm"]["device"] = [int(x) for x in args.device.split(",")]
        if getattr(args, "max_concurrency", None) is not None:
            cfg["benchmark"]["concurrency"] = [int(x) for x in args.max_concurrency.split(",")]
        if getattr(args, "select", None) is not None:
            cfg["metrics"]["collect"] = args.select.split(",")
        normalize(cfg)
    except (ValueError, TypeError) as exc:
        return None, err("invalid configuration", {"reason": str(exc)})
    changes = wf.meta.get("config_changes", [])
    if previous != cfg:
        changes.append({"at": now_iso(), "before": previous, "after": copy.deepcopy(cfg)})
    wf.set_meta(config=cfg, config_changes=changes,
                sudo=bool(getattr(args, "sudo", False) or wf.meta.get("sudo")))
    tasks = _read_tasks()
    if not tasks or not tasks.get("benchmark_rounds"):
        _init_tasks(cfg)
    _update_task("config", "completed", detail="配置已冻结")
    if hasattr(args, "sudo"):
        args.sudo = wf.meta["sudo"]
    return cfg, None


def cmd_status(args):
    wf = _wf()
    progress = _read_progress()
    stale = None
    ts = progress.get("updated_ts")
    if ts:
        stale = (time.time() - ts) > 120
    return ok({"state": wf.current(),
               "type": wf.state_type(),
               "allowed": wf.allowed_events(),
               "run_id": _current_run_id(),
               "progress": progress,
               "tasks": _read_tasks(),
               "stale": stale})


def cmd_progress(args):
    """Show where the current run is (state + progress.json + run.log tail)."""
    wf = _wf()
    log_tail = ""
    try:
        with open(_log_path(), "r") as f:
            log_tail = "".join(f.readlines()[-30:])
    except OSError:
        pass
    return ok({
        "state": wf.current(),
        "allowed": wf.allowed_events(),
        "run_id": _current_run_id(),
        "run_dir": _run_dir(),
        "progress": _read_progress(),
        "tasks": _read_tasks(),
        "rendered": render_tasks(_read_tasks()),
        "log_tail": log_tail,
    })


def cmd_watch(args):
    """Read-only task display for a run executing in another terminal."""
    while True:
        snapshot = render_tasks(_read_tasks(args.run_id))
        if sys.stdout.isatty() and not args.no_clear:
            sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.write(snapshot + "\n")
        sys.stdout.flush()
        if args.once:
            return ok({"run_id": args.run_id or _current_run_id(), "tasks": _read_tasks(args.run_id)})
        time.sleep(args.interval)


def cmd_config(args):
    """Print the resolved benchmark configuration (no state transition)."""
    cfg, cfg_err = _load_config(args.config)
    if cfg_err:
        return err("failed to load config",
                   {"config": args.config, "error": cfg_err})
    return ok({"config": cfg, "path": os.path.abspath(args.config)})


def cmd_env_check(args):
    wf = _wf()
    if wf.current() not in ("IDLE", "ENV_CHECK"):
        return err("invalid state for env-check", {"state": wf.current()})
    cfg, failure = _config_for_run(wf, args)
    if failure:
        return _block(wf, "configuration_invalid", failure, "IDLE")
    if wf.current() == "IDLE":
        wf.transition("start")
    _update_task("environment", "running")
    results = {}
    for script in ("environment", "ascend", "docker"):
        argv = ["check"] + (["--mock"] if args.mock else [])
        if script == "docker":
            argv += ["--runtime", cfg["container"]["runtime"]]
            if args.sudo:
                argv += ["--sudo"]
        result = call_tool(script + ".py", argv, timeout=180, log_path=_log_path())
        results[script] = result
        if not result.get("ok"):
            wf.set_meta(environment=results)
            return _block(wf, "environment_unavailable", results, "ENV_CHECK")
    wf.set_meta(environment=results)
    wf.transition("done")
    _update_task("environment", "completed")
    _write_progress(state=wf.current(), stage="environment", substage="done")
    return ok({"state": wf.current(), "environment": results, "config": cfg,
               "next": "start", "needs_user_decision": False,
               "message": "环境检查完成，自动探测并按配置启动或复用服务。"})


def _launch_params(args, cfg):
    """Resolve launch params: explicit CLI flags override benchmark.yaml."""
    c_vllm = cfg.get("vllm", {}) or {}
    c_cont = cfg.get("container", {}) or {}

    def _pick(attr, cfg_val):
        val = getattr(args, attr, None)
        return cfg_val if val is None else val

    physical = _parse_ids(getattr(args, "device", None)) \
        if getattr(args, "device", None) is not None \
        else _parse_ids(c_vllm.get("device"))
    extra = getattr(args, "extra_arg", None)
    if not extra:
        extra = c_vllm.get("extra_args") or []
    extra = [str(x) for x in extra]
    served = c_vllm.get("served_model_name")
    if served and not any(x == "--served-model-name"
                          or x.startswith("--served-model-name=")
                          for x in extra):
        extra = extra + ["--served-model-name", served]
    return {
        "container": args.name or c_cont.get("name"),
        "runtime": args.runtime or c_cont.get("runtime") or "docker",
        "model": getattr(args, "model", None) or _model_ref(cfg),
        "host": getattr(args, "host", None) or c_vllm.get("host") or "0.0.0.0",
        "port": args.port if args.port is not None else c_vllm.get("port", 8000),
        "physical": physical,
        "tensor_parallel_size": _pick("tensor_parallel_size",
                                      c_vllm.get("tensor_parallel_size")),
        "max_model_len": _pick("max_model_len", c_vllm.get("max_model_len")),
        "gpu_memory_utilization": _pick("gpu_memory_utilization",
                                        c_vllm.get("gpu_memory_utilization")),
        "extra_args": extra,
    }


def _run_probe(name, runtime, params, args):
    argv = ["probe", "--name", name, "--runtime", runtime,
            "--port", str(params["port"]), "--host", params["host"],
            "--expected", json.dumps(params)]
    if params.get("model"):
        argv += ["--model", params["model"]]
    if params.get("physical"):
        argv += ["--device", ",".join(map(str, params["physical"]))]
    if args.sudo:
        argv += ["--sudo"]
    return call_tool("vllm.py", argv, timeout=240, log_path=_log_path())


# Probe decisions that only mean "not ready yet": safe to retry during the
# post-launch window instead of blocking immediately.
_TRANSIENT_PROBE_DECISIONS = ("loading", "need_start", "identity_unknown")

# identity_unknown can also mean a genuine foreign service on our port, so it
# is retried only a bounded number of consecutive times before blocking with
# the captured evidence.
DEFAULT_IDENTITY_GRACE = 3


def _identity_grace(args):
    value = getattr(args, "identity_grace", None)
    return DEFAULT_IDENTITY_GRACE if value is None else max(1, value)


def _wait_health(wf, port, args):
    cfg = wf.meta["config"]
    params = _launch_params(build_parser().parse_args(["start"]), cfg)
    retries = max(1, args.health_retries or 30)
    grace = _identity_grace(args)
    last = None
    ambiguous = 0
    _update_task("health", "running", attempt=0, total_attempts=retries)
    for i in range(retries):
        _check_cancel()
        last = _run_probe(params["container"], params["runtime"], params, args)
        data = last.get("data") or {}
        decision = data.get("decision")
        if last.get("ok") and decision == "already_running":
            wf.set_meta(service=last["data"])
            wf.transition("ok")
            _update_task("health", "completed", attempt=i + 1, total_attempts=retries)
            return ok({"state": wf.current(), "next": "bench", "service": last["data"]})
        ambiguous = ambiguous + 1 if decision == "identity_unknown" else 0
        if last.get("ok") and decision == "identity_unknown" and ambiguous >= grace:
            # Persistent ambiguity: a real duplicate/foreign service. Block with
            # evidence (root_pids/root_groups) instead of guessing.
            return _block(wf, "identity_unknown", last, "PROBE_SERVICE")
        if last.get("ok") and decision not in _TRANSIENT_PROBE_DECISIONS:
            return _block(wf, decision or "service_unknown", last, "PROBE_SERVICE")
        _write_progress(state=wf.current(), stage="health", attempt=i + 1,
                        total_attempts=retries, decision=decision,
                        identity_unknown_attempts=ambiguous)
        retrying = decision == "identity_unknown"
        _update_task("health", "running", attempt=i + 1, total_attempts=retries,
                     detail=("服务身份暂不明朗，重试 %d/%d" % (ambiguous, grace)
                             if retrying else None),
                     reason=("identity_unknown" if retrying else None))
        if i + 1 < retries:
            time.sleep(max(0, args.health_wait if args.health_wait is not None else 10))
    return _block(wf, "service_health_timeout", last, "PROBE_SERVICE")


def _handle_probe_decision(wf, name, runtime, params, probe, args):
    if not probe.get("ok"):
        return _block(wf, "service_probe_failed", probe, "PROBE_SERVICE")
    data = probe.get("data") or {}
    decision = data.get("decision")
    _update_task("service", "running")
    if decision == "device_unhealthy":
        return _wait_for_device(wf, data)
    if decision in ("need_start", "already_running", "loading"):
        _acquired, holders = _acquire_devices(wf, data)
        if holders:
            return _wait_for_resource(wf, holders, data)
    if decision == "container_stopped":
        if getattr(args, "skip_start", False):
            return _block(wf, "container_stopped", data, "PROBE_SERVICE")
        _update_task("container", "running")
        started = call_tool("vllm.py", ["ensure", "--name", name, "--runtime", runtime] +
                            (["--sudo"] if args.sudo else []), timeout=180, log_path=_log_path())
        if not started.get("ok"):
            return _block(wf, "container_start_failed", started, "PROBE_SERVICE")
        wf.set_meta(container_started=True)
        _update_task("container", "completed", detail="已启动")
        probe = _run_probe(name, runtime, params, args)
        if (probe.get("data") or {}).get("decision") == "container_stopped":
            return _block(wf, "container_will_not_stay_running", probe, "PROBE_SERVICE")
        return _handle_probe_decision(wf, name, runtime, params, probe, args)
    if decision in ("already_running", "loading"):
        wf.set_meta(service=data)
        _update_task("container", "completed", detail="已运行")
        _update_task("service", "completed", detail="已复用" if decision == "already_running" else "服务加载中")
        wf.transition("already_running")
        return _wait_health(wf, params["port"], args)
    if decision == "need_start" and not getattr(args, "skip_start", False):
        _update_task("container", "completed", detail="已运行")
        _update_task("service", "completed", detail="未发现匹配服务")
        wf.transition("need_start")
        return _start_service(wf, name, runtime, params, args)
    return _block(wf, decision or "service_unknown", data, "PROBE_SERVICE")


def cmd_start(args):
    wf = _wf()
    if wf.current() not in ("REPORT", "PROBE_SERVICE", "HEALTH"):
        return err("invalid state for start", {"state": wf.current()})
    cfg, failure = _config_for_run(wf, args)
    if failure:
        return _block(wf, "configuration_invalid", failure, "PROBE_SERVICE")
    params = _launch_params(args, cfg)
    if wf.current() == "REPORT":
        wf.transition("continue")
    _update_task("container", "running")
    _update_task("service", "running")
    if wf.current() == "HEALTH":
        return _wait_health(wf, params["port"], args)
    probe = _run_probe(params["container"], params["runtime"], params, args)
    return _handle_probe_decision(wf, params["container"], params["runtime"], params, probe, args)


def _build_launch_args(name, runtime, params, log_path, sudo=False):
    """Pure helper: build the `vllm.py launch` argv.

    `--extra-arg` values that themselves start with `--` (e.g.
    --trust-remote-code) MUST use the `--flag=value` form, otherwise argparse
    parses them as options and the launch fails with rc=2.
    """
    argv = ["launch", "--name", name, "--runtime", runtime,
            "--model", params["model"], "--port", str(params["port"]),
            "--host", params["host"], "--log-path", log_path]
    if params.get("physical"):
        argv += ["--device", ",".join(str(x) for x in params["physical"])]
    if params.get("tensor_parallel_size"):
        argv += ["--tensor-parallel-size", str(params["tensor_parallel_size"])]
    if params.get("max_model_len"):
        argv += ["--max-model-len", str(params["max_model_len"])]
    if params.get("gpu_memory_utilization") is not None:
        argv += ["--gpu-memory-utilization",
                 str(params["gpu_memory_utilization"])]
    for a in (params.get("extra_args") or []):
        argv += ["--extra-arg=%s" % str(a)]
    if sudo:
        argv += ["--sudo"]
    return argv


def _start_service(wf, name, runtime, params, args):
    log_path = os.path.join(_run_dir(), "serve.log")
    _update_task("launch", "running")
    launched = call_tool("vllm.py", _build_launch_args(name, runtime, params, log_path, args.sudo),
                         timeout=120, log_path=_log_path())
    if not launched.get("ok"):
        return _block(wf, "service_launch_failed", launched, "PROBE_SERVICE")
    wf.set_meta(service_started=True, launch=launched["data"], serve_log=log_path)
    _update_task("launch", "completed")
    wf.transition("done")
    return _wait_health(wf, params["port"], args)


def cmd_confirm_start(args):
    # Compatibility alias: only an explicit exception decision may use this command.
    return cmd_resume(args)


def _check_cancel():
    path = os.path.join(_run_dir(), "cancel")
    if os.path.exists(path):
        raise KeyboardInterrupt("cancelled")


def _finish_scrape(proc):
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=25)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


class _RoundMonitor:
    """Expose safe live data while vLLM bench is running.

    vLLM versions do not all expose completed-request counters.  We therefore
    show elapsed time and scheduler queue state, and only add a request count
    when a reliable counter is present in the metrics sample.
    """
    def __init__(self, task_id, queue_path):
        self.task_id = task_id
        self.queue_path = queue_path
        self.started = time.monotonic()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        while not self.stop.wait(0.5):
            samples = read_json(self.queue_path, []) or []
            latest = samples[-1] if samples else {}
            _update_task(
                self.task_id, "running", elapsed_sec=round(time.monotonic() - self.started, 1),
                running=latest.get("vllm:num_requests_running"),
                waiting=latest.get("vllm:num_requests_waiting"),
            )

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)


def _render_analysis(report, out_dir, report_path):
    """Best-effort static dashboard + analysis; never invalidates the run.

    A missing matplotlib or a plotting bug must not fail an otherwise complete
    benchmark. The analysis (data layer) is still produced and attached to the
    report; the plot error is recorded for the operator.
    """
    run_id = report.get("run_id")
    png_path = os.path.join(out_dir, "vllm_performance_%s.png" % run_id)
    analysis_path = os.path.join(out_dir, "analysis_%s.json" % run_id)
    try:
        result = call_tool("perf.py", ["render", "--report", report_path,
                                       "--png", png_path, "--analysis", analysis_path],
                           timeout=240, log_path=_log_path())
    except Exception as exc:  # noqa: BLE001 - analysis must never break a run
        result = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    if result.get("ok"):
        data = result.get("data") or {}
        report["analysis"] = data.get("analysis")
        report["analysis_output"] = analysis_path
        if data.get("plot_path"):
            report["plot_output"] = data["plot_path"]
        if data.get("plot_error"):
            report["plot_error"] = data["plot_error"]
    else:
        report["analysis_error"] = result.get("error") or "analysis_failed"
        _append_log("[perf] analysis/plot failed: %s\n" % report["analysis_error"])
    try:
        write_json_atomic(report_path, report)
    except OSError as exc:
        report["analysis_error"] = "report_rewrite_failed: %s" % exc


def cmd_bench(args):
    wf = _wf()
    if wf.current() not in ("BENCHMARK", "COLLECT"):
        return err("invalid state for bench", {"state": wf.current()})
    previous = copy.deepcopy(wf.meta.get("config"))
    old_options = copy.deepcopy(wf.meta.get("runtime_options", {}))
    cfg, failure = _config_for_run(wf, args)
    if failure:
        return _block(wf, "configuration_invalid", failure, "BENCHMARK")
    # A changed experiment must not silently reuse rounds from another configuration.
    if previous != cfg or any(old_options.get(k) != wf.meta.get("runtime_options", {}).get(k) for k in ("tokenizer", "local", "visible_devices")):
        wf.set_meta(completed_runs=[], pending_round=None)
        wf.transition("recheck")
        return _drive(args)
    c = cfg["container"]
    v = cfg["vllm"]
    b = cfg["benchmark"]
    m = cfg["metrics"]
    model = _resolve_client_model(cfg, wf.meta.get("service"))
    # When requests use a served alias (`--served-model-name`), the tokenizer
    # cannot be resolved from that alias and must come from the local path.
    tokenizer = args.tokenizer or (_model_ref(cfg) if model != _model_ref(cfg) else None)
    host = "127.0.0.1" if v["host"] in ("0.0.0.0", "::", "") else v["host"]
    args.timeout = args.timeout or 3600
    args.scrape_seconds = args.scrape_seconds or 3600
    rounds = _round_specs(b)
    results_dir = os.path.join(_run_dir(), "results")
    os.makedirs(results_dir, exist_ok=True)
    out_dir = cfg["report"]["output"]
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(DATA_ROOT, out_dir)
    try:
        os.makedirs(out_dir, exist_ok=True)
        import tempfile
        with tempfile.TemporaryFile(dir=out_dir):
            pass
    except OSError as exc:
        return _block(wf, "report_directory_unavailable", {"error": str(exc)}, "BENCHMARK")
    # SLO -> `vllm bench serve --goodput` pairs (milliseconds).
    goodput = []
    for slo_key, metric in (("ttft_ms", "ttft"), ("tpot_ms", "tpot"), ("e2el_ms", "e2el")):
        value = (cfg.get("slo") or {}).get(slo_key)
        if value:
            goodput.append("%s:%s" % (metric, value))
    percentiles = ",".join(str(p) for p in (b.get("metric_percentiles") or [50, 90, 99]))
    npu_devices = [str(x) for x in (v.get("device") or [])] if "gpu" in m["collect"] else []
    runs = list(wf.meta.get("completed_runs") or [])
    _update_task("benchmark", "running", completed_rounds=len(runs), total_rounds=len(rounds))
    for idx, spec in enumerate(rounds):
        if idx < len(runs):
            continue
        _check_cancel()
        pending = wf.meta.get("pending_round")
        if not pending:
            tag = "%s_%s" % (_tag(spec["value"]), uuid.uuid4().hex[:8])
            queue_path = os.path.join(results_dir, "queue_" + tag + ".json")
            scrape_args = [sys.executable, os.path.join(TOOLS_DIR, "metrics.py"), "scrape",
                           "--url", "http://%s:%d/metrics" % (host, v["port"]),
                           "--seconds", str(max(args.scrape_seconds, args.timeout + 60)),
                           "--interval", str(m["interval"]), "--out", queue_path,
                           "--model", model, "--runtime", c["runtime"]]
            if npu_devices:
                scrape_args += ["--npu-devices", ",".join(npu_devices)]
            if not args.local:
                scrape_args += ["--container", c["name"]]
            if args.sudo:
                scrape_args += ["--sudo"]
            proc = subprocess.Popen(scrape_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            round_id = spec["id"]
            _update_task(round_id, "running", elapsed_sec=0, running=None, waiting=None, started_at=now_iso())
            monitor = _RoundMonitor(round_id, queue_path)
            monitor.start()
            try:
                need_queue = bool(set(m["collect"]) & {"queue_time", "request_timeline"})
                deadline = time.monotonic() + 35
                while need_queue:
                    _check_cancel()
                    samples = read_json(queue_path, [])
                    if samples and not samples[-1].get("error"):
                        break
                    if proc.poll() is not None or time.monotonic() >= deadline:
                        return _block(wf, "metrics_baseline_unavailable", {"queue_path": queue_path}, "BENCHMARK")
                    time.sleep(0.2)
                argv = ["run", "--model", model, "--host", host, "--port", str(v["port"]),
                        "--num-prompts", str(b["requests"]),
                        "--input-len", str(b["input_tokens"]), "--output-len", str(b["output_tokens"]),
                        "--metric-percentiles", percentiles,
                        "--result-dir", results_dir, "--runtime", c["runtime"], "--timeout", str(args.timeout)]
                if spec["concurrency"] is not None:
                    argv += ["--max-concurrency", str(spec["concurrency"])]
                if spec["request_rate"] is not None:
                    argv += ["--request-rate", str(spec["request_rate"])]
                for slo in goodput:
                    argv += ["--goodput", slo]
                if args.visible_devices:
                    argv += ["--visible-devices", args.visible_devices]
                if tokenizer:
                    argv += ["--tokenizer", tokenizer]
                if args.local:
                    argv += ["--local"]
                else:
                    argv += ["--container", c["name"]]
                if args.sudo:
                    argv += ["--sudo"]
                _write_progress(state=wf.current(), stage="benchmark", level=spec["value"],
                                axis=spec["axis"], completed_levels=len(runs))
                result = call_tool("benchmark.py", argv, timeout=args.timeout + 120, log_path=_log_path())
            finally:
                monitor.close()
                _finish_scrape(proc)
            if not result.get("ok"):
                _update_task(round_id, "failed", reason="benchmark_failed")
                return _block(wf, "benchmark_failed", result, "BENCHMARK")
            pending = {"axis": spec["axis"], "value": spec["value"],
                       "concurrency": spec["concurrency"], "request_rate": spec["request_rate"],
                       "bench_result_path": result["data"]["result_path"],
                       "queue_path": queue_path, "report_path": os.path.join(results_dir, "report_" + tag + ".json")}
            wf.set_meta(pending_round=pending)
            _update_task(round_id, "completed")
            _update_task("benchmark", "running", completed_rounds=len(runs) + 1, total_rounds=len(rounds))
        _update_task("metrics", "running", detail="校验 %s 指标" % pending["value"])
        collected = call_tool("metrics.py", ["collect", "--bench", pending["bench_result_path"],
                              "--queue", pending["queue_path"], "--out", pending["report_path"],
                              "--select", ",".join(m["collect"])], timeout=60, log_path=_log_path())
        if not collected.get("ok"):
            if wf.meta.get("accept_partial_round") == len(runs):
                collected = {"ok": True, "data": collected.get("detail") or {"quality": {"complete": False}}}
                wf.set_meta(accept_partial_round=None)
            else:
                return _block(wf, "metrics_incomplete", collected, "BENCHMARK")
        runs.append(dict(pending, metrics=collected["data"]))
        wf.set_meta(completed_runs=runs, pending_round=None)
        _update_task("metrics", "completed")
    if wf.current() == "BENCHMARK":
        wf.transition("done")
    _update_task("benchmark", "completed", completed_rounds=len(runs), total_rounds=len(rounds))
    _update_task("analysis", "running")
    report = {"run_id": _current_run_id(), "config": cfg,
              "environment": wf.meta.get("environment"), "service": wf.meta.get("service"),
              "launch": wf.meta.get("launch"), "config_changes": wf.meta.get("config_changes", []),
              "axis": (rounds[0]["axis"] if rounds else "concurrency"),
              "rounds": [{"id": s["id"], "axis": s["axis"], "value": s["value"],
                          "concurrency": s["concurrency"], "request_rate": s["request_rate"]}
                         for s in rounds],
              "levels": [s["value"] for s in rounds], "runs": runs,
              "runtime_options": wf.meta.get("runtime_options"),
              "quality": {"complete": all(r["metrics"].get("quality", {}).get("complete", False) for r in runs)},
              "notes": ["request_timeline is a service-level queue timeline, not per-request tracing",
                        "TTFT breakdown is mean-based and approximate: client TTFT minus server queue/prefill includes network/frontend and the unexposed arrival->queue gap"]}
    path = os.path.join(out_dir, "report_%s.json" % _current_run_id())
    try:
        write_json_atomic(path, report)
    except OSError as exc:
        return _block(wf, "report_write_failed", {"error": str(exc), "report": report}, "COLLECT")
    _render_analysis(report, out_dir, path)
    wf.set_meta(report_output=path)
    wf.transition("done")
    _update_task("analysis", "completed", detail=path)
    _write_progress(state=wf.current(), stage="analyze", report_output=path,
                    plot_output=report.get("plot_output"))
    return ok({"state": wf.current(), "report_output": path,
               "plot_output": report.get("plot_output"), "metrics": report,
               "llm_prompt": render("ANALYZE", metrics=report), "next": "done"})


def cmd_done(args):
    wf = _wf()
    if wf.current() != "ANALYZE":
        return err("invalid state for done", {"state": wf.current()})
    _update_task("analysis", "completed")
    wf.transition("done")
    cfg = wf.meta.get("config") or {}
    cleanup = bool((cfg.get("cleanup") or {}).get("stop_service", True))
    started = bool(wf.meta.get("service_started"))
    stopped = False
    if not cleanup:
        _update_task("cleanup", "skipped", detail="cleanup.stop_service=false")
        _write_progress(state=wf.current(), stage="cleanup",
                        substage="skipped", reason="disabled")
    elif not started:
        _update_task("cleanup", "skipped", detail="复用服务，保留运行")
        _write_progress(state=wf.current(), stage="cleanup",
                        substage="skipped", reason="reused_service")
    else:
        _update_task("cleanup", "running")
        result = _stop_service(wf, cfg)
        if result.get("ok"):
            stopped = True
            _update_task("cleanup", "completed", detail="服务已关闭")
            _write_progress(state=wf.current(), stage="cleanup", substage="done")
        else:
            _update_task("cleanup", "failed", reason="service_stop_failed")
            _write_progress(state=wf.current(), stage="cleanup",
                            substage="failed", error=result.get("error"))
            _append_log("[cleanup] stop failed: %s\n" % (result.get("error")))
    wf.transition("done")
    _write_progress(state=wf.current(), stage="done", service_stopped=stopped)
    return ok({"state": wf.current(), "report_output": wf.meta.get("report_output"),
               "service_stopped": stopped})


def cmd_cancel(args):
    wf = _wf()
    if wf.current() in ("DONE", "CANCELLED"):
        return ok({"state": wf.current()})
    release = bool(getattr(args, "release_locks", False))
    if release or not wf.meta.get("service"):
        released = device_lock.release(
            LOCKS_DIR, _device_ids(wf.meta.get("config") or {}),
            _current_run_id())
        if release:
            wf.set_meta(device_locks=[], released_locks=released)
    wf.transition("cancel")
    tasks = _read_tasks()
    for task in tasks.get("tasks", []) + tasks.get("benchmark_rounds", []):
        if task.get("status") in ("pending", "running", "blocked"):
            task["status"] = "cancelled"
    _write_tasks(tasks)
    return ok({"state": wf.current()})


def _stop_service(wf, cfg=None, name=None, runtime=None, sudo=False):
    """Stop the target container and release its device locks.

    Shared by the explicit `stop` command and the post-run `done` cleanup.
    """
    cfg = cfg or wf.meta.get("config")
    if not cfg:
        cfg, failure = _load_config(DEFAULT_CONFIG)
        if failure:
            return failure
    result = call_tool("vllm.py", ["stop", "--name", name or cfg["container"]["name"],
                       "--runtime", runtime or cfg["container"]["runtime"]] +
                       (["--sudo"] if sudo or wf.meta.get("sudo") else []), timeout=150)
    if result.get("ok"):
        released = device_lock.release_all(LOCKS_DIR, _device_ids(cfg))
        wf.set_meta(device_locks=[], released_locks=released)
    return result


def cmd_stop(args):
    # An explicit stop command is separate from normal benchmark cleanup.
    return _stop_service(_wf(), name=args.name, runtime=args.runtime, sudo=args.sudo)


def _stage_args(command, args):
    result = build_parser().parse_args([command])
    for key, value in vars(args).items():
        if key != "cmd" and hasattr(result, key) and value is not None:
            setattr(result, key, value)
    # Overrides have already been saved; don't keep reapplying them at every stage.
    for key in ("name", "container", "model", "port", "host", "runtime", "device", "extra_arg",
                "tensor_parallel_size", "max_model_len", "gpu_memory_utilization", "num_prompts",
                "input_len", "output_len", "request_rate", "max_concurrency", "scrape_interval", "select"):
        if hasattr(result, key):
            setattr(result, key, None)
    return result


def _drive(args):
    while True:
        _check_cancel()
        state = _wf().current()
        if state in ("IDLE", "ENV_CHECK"):
            result = cmd_env_check(_stage_args("env-check", args))
        elif state in ("REPORT", "PROBE_SERVICE", "HEALTH"):
            result = cmd_start(_stage_args("start", args))
        elif state in ("BENCHMARK", "COLLECT"):
            return cmd_bench(_stage_args("bench", args))
        else:
            return err("cannot continue from state", {"state": state})
        if not result.get("ok"):
            return result
        if _wf().current() in ("WAITING_RESOURCE", "WAITING_DEVICE",
                               "WAIT_USER_DECISION"):
            return result


def cmd_run(args):
    """Create a new run regardless of any other run's state.

    Runs are independent; mutual exclusion is delegated to per-NPU device locks
    acquired at probe time, not to a global "active run" concept.
    """
    _ensure_data_root()
    created = _create_run()
    if not created.get("ok"):
        return created
    wf = _wf()
    cfg, failure = _config_for_run(wf, args)
    if failure:
        return _block(wf, "configuration_invalid", failure, "IDLE")
    _set_cancel_path()
    lock_path = os.path.join(_run_dir(), "execution.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _drive(args)


def cmd_resume(args):
    wf = _wf()
    if wf.current() not in ("WAIT_USER_DECISION", "WAITING_RESOURCE",
                            "WAITING_DEVICE"):
        return err("resume requires a blocked or resource-waiting run",
                   {"state": wf.current()})
    issue = wf.meta.get("issue") or {}
    before = copy.deepcopy(wf.meta.get("config"))
    old_options = copy.deepcopy(wf.meta.get("runtime_options", {}))
    if getattr(args, "reload_config", False):
        cfg, failure = _load_config(args.config or (before or {}).get("_config_path") or DEFAULT_CONFIG, validate=False)
        if failure:
            return _block(wf, "configuration_invalid", failure, issue.get("resume_state", "IDLE"))
        wf.set_meta(config=cfg)
    cfg, failure = _config_for_run(wf, args)
    if failure:
        return _block(wf, "configuration_invalid", failure, issue.get("resume_state", "IDLE"))
    changed = before != cfg or any(old_options.get(k) != wf.meta.get("runtime_options", {}).get(k) for k in ("tokenizer", "local", "visible_devices"))
    if getattr(args, "reload_config", False) and before != cfg:
        changes = wf.meta.get("config_changes", [])
        changes.append({"at": now_iso(), "source": "reload", "before": before, "after": copy.deepcopy(cfg)})
        wf.set_meta(config_changes=changes)
    target = issue.get("resume_state", "PROBE_SERVICE")
    if changed:
        wf.set_meta(completed_runs=[], pending_round=None)
        target = "IDLE" if target in ("IDLE", "ENV_CHECK") else "PROBE_SERVICE"
    if getattr(args, "accept_partial", False):
        if issue.get("reason") != "metrics_incomplete" or not wf.meta.get("pending_round"):
            return err("accept-partial requires a saved round with incomplete metrics")
        wf.set_meta(accept_partial_round=len(wf.meta.get("completed_runs") or []))
    if getattr(args, "retry_round", False):
        wf.set_meta(pending_round=None)
    if getattr(args, "modify", False):
        return ok({"state": wf.current(), "config": cfg, "next": "resume"})
    transition = wf.transition("resume_" + target.lower())
    if not transition.get("ok"):
        return transition
    wf.set_meta(issue=None)
    return _drive(args)


def _set_cancel_path():
    os.environ["BENCHMARK_CANCEL_PATH"] = os.path.join(_run_dir(), "cancel")


def build_parser():
    p = argparse.ArgumentParser(description="vLLM Benchmark Agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")
    status_p = sub.add_parser("status")
    status_p.add_argument("--run-id", dest="run_id", default=None)
    progress_p = sub.add_parser("progress")
    progress_p.add_argument("--run-id", dest="run_id", default=None)
    watch = sub.add_parser("watch", help="实时显示当前运行的任务清单")
    watch.add_argument("--run-id", default=None)
    watch.add_argument("--interval", type=float, default=1.0)
    watch.add_argument("--once", action="store_true")
    watch.add_argument("--no-clear", action="store_true")

    c = sub.add_parser("config")
    c.add_argument("--config", default=DEFAULT_CONFIG)

    q = sub.add_parser("env-check")
    q.add_argument("--image", default=None)
    q.add_argument("--config", default=DEFAULT_CONFIG)
    q.add_argument("--sudo", action="store_true")
    q.add_argument("--mock", action="store_true")

    s = sub.add_parser("start")
    s.add_argument("--name", default=None)
    s.add_argument("--runtime", default=None)
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--host", default=None)
    s.add_argument("--model", default=None)
    s.add_argument("--device", default=None,
                   help="override physical NPU ids, e.g. 2 or 2,5")
    s.add_argument("--tensor-parallel-size", dest="tensor_parallel_size",
                   type=int, default=None)
    s.add_argument("--max-model-len", dest="max_model_len", type=int,
                   default=None)
    s.add_argument("--gpu-memory-utilization", dest="gpu_memory_utilization",
                   type=float, default=None)
    s.add_argument("--extra-arg", dest="extra_arg", action="append",
                   default=None)
    s.add_argument("--config", default=None)
    s.add_argument("--skip-start", dest="skip_start", action="store_true",
                   help="do not start vLLM; only probe and wait if already running")
    s.add_argument("--health-retries", dest="health_retries", type=int, default=None)
    s.add_argument("--health-wait", dest="health_wait", type=int, default=None)
    s.add_argument("--sudo", action="store_true")

    cs = sub.add_parser("confirm-start")
    cs.add_argument("--name", default=None)
    cs.add_argument("--runtime", default=None)
    cs.add_argument("--port", type=int, default=None)
    cs.add_argument("--host", default=None)
    cs.add_argument("--model", default=None)
    cs.add_argument("--device", default=None,
                    help="override physical NPU ids, e.g. 2 or 2,5")
    cs.add_argument("--tensor-parallel-size", dest="tensor_parallel_size",
                    type=int, default=None)
    cs.add_argument("--max-model-len", dest="max_model_len", type=int,
                    default=None)
    cs.add_argument("--gpu-memory-utilization", dest="gpu_memory_utilization",
                    type=float, default=None)
    cs.add_argument("--extra-arg", dest="extra_arg", action="append",
                    default=None)
    cs.add_argument("--modify", action="store_true",
                    help="save exception overrides without resuming")
    cs.add_argument("--config", default=None)
    cs.add_argument("--health-retries", dest="health_retries", type=int, default=None)
    cs.add_argument("--health-wait", dest="health_wait", type=int, default=None)
    cs.add_argument("--sudo", action="store_true")

    b = sub.add_parser("bench")
    b.add_argument("--model", default=None)
    b.add_argument("--tokenizer", default=None)
    b.add_argument("--container", default=None)
    b.add_argument("--runtime", default=None)
    b.add_argument("--host", default=None)
    b.add_argument("--port", type=int, default=None)
    b.add_argument("--num-prompts", dest="num_prompts", type=int, default=None)
    b.add_argument("--request-rate", dest="request_rate", type=float, default=None)
    b.add_argument("--max-concurrency", dest="max_concurrency", default=None,
                   help="comma-separated concurrency levels; overrides config")
    b.add_argument("--input-len", dest="input_len", type=int, default=None)
    b.add_argument("--output-len", dest="output_len", type=int, default=None)
    b.add_argument("--select", default=None,
                   help="comma-separated metric groups to collect")
    b.add_argument("--visible-devices", dest="visible_devices", default=None,
                   help="override ASCEND_RT_VISIBLE_DEVICES for the bench session")
    b.add_argument("--scrape-seconds", dest="scrape_seconds", type=int, default=None)
    b.add_argument("--scrape-interval", dest="scrape_interval", type=float,
                   default=None)
    b.add_argument("--timeout", type=int, default=None)
    b.add_argument("--config", default=None)
    b.add_argument("--local", action="store_true", default=None)
    b.add_argument("--sudo", action="store_true")

    for command in ("done", "cancel"):
        run_p = sub.add_parser(command)
        run_p.add_argument("--run-id", dest="run_id", default=None)
        if command == "cancel":
            run_p.add_argument(
                "--release-locks", dest="release_locks", action="store_true",
                help="release this run's NPU locks but keep the service running")
    sub.add_parser("migrate-data",
                   help="把旧版代码树内的 .benchmark/ 与 reports/ 数据迁出到数据目录")

    st = sub.add_parser("stop")
    st.add_argument("--name", default=None)
    st.add_argument("--runtime", default=None)
    st.add_argument("--sudo", action="store_true")

    for command in ("run", "resume"):
        combined = sub.add_parser(command)
        seen = {"help"}
        for source in (s, b, q):
            for action in source._actions:
                if action.dest in seen:
                    continue
                seen.add(action.dest)
                combined._add_action(copy.copy(action))
        if command == "resume":
            combined.add_argument("--run-id", dest="run_id", default=None)
            combined.add_argument("--reload-config", action="store_true")
            combined.add_argument("--retry-round", action="store_true",
                                  help="explicitly rerun the incomplete round after a metrics failure")
            combined.add_argument("--accept-partial", action="store_true",
                                  help="accept missing metrics for this saved round only")
        combined.add_argument("--progress", choices=("auto", "none"), default="auto",
                              help="显示实时任务面板（默认 auto；最终 JSON 始终写入 stdout）")
    return p


def _execute(args, handler):
    """Run one command with renderer + signal/cancel/error handling."""
    _set_cancel_path()
    def interrupted(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    renderer = _TaskRenderer(args.cmd in ("run", "resume")
                             and getattr(args, "progress", "none") != "none")
    renderer.start()
    try:
        payload = handler(args)
    except KeyboardInterrupt:
        payload = cmd_cancel(args)
    except Exception as exc:
        wf = _wf()
        target = {"START_SERVICE": "PROBE_SERVICE", "REPORT": "PROBE_SERVICE"}.get(wf.current(), wf.current())
        payload = _block(wf, "execution_error", {"type": type(exc).__name__, "message": str(exc)}, target)
    finally:
        renderer.close()
        os.environ.pop("BENCHMARK_CANCEL_PATH", None)
    return payload


def main():
    global _ACTIVE_RUN_OVERRIDE
    args = build_parser().parse_args()
    selected = getattr(args, "run_id", None)
    if selected:
        _ACTIVE_RUN_OVERRIDE = selected
    handlers = {
        "init": cmd_init,
        "status": cmd_status,
        "progress": cmd_progress,
        "watch": cmd_watch,
        "config": cmd_config,
        "env-check": cmd_env_check,
        "start": cmd_start,
        "confirm-start": cmd_confirm_start,
        "bench": cmd_bench,
        "done": cmd_done,
        "cancel": cmd_cancel,
        "stop": cmd_stop,
        "migrate-data": cmd_migrate_data,
    }
    handlers.update(run=cmd_run, resume=cmd_resume)
    os.makedirs(STATE_DIR, exist_ok=True)
    if args.cmd == "watch":
        if args.interval <= 0:
            _emit(err("watch interval must be positive"))
            return
        cmd_watch(args)
        return
    if args.cmd in ("status", "progress", "config"):
        _emit(handlers[args.cmd](args))
        return
    if args.cmd == "run":
        # `run` creates its own run id and locks that run internally, so a new
        # run never waits for, or blocks, an unrelated run.
        _emit(_execute(args, cmd_run))
        return
    run_id = _ACTIVE_RUN_OVERRIDE or _current_run_id() or "default"
    lock_path = os.path.join(RUNS_DIR, run_id, "execution.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if args.cmd == "cancel":
                path = os.path.join(RUNS_DIR, run_id, "cancel")
                with open(path, "w") as marker:
                    marker.write(now_iso())
                _emit(ok({"cancel_requested": True, "run_id": run_id}))
            else:
                _emit(err("another command is executing for run %s; use status or cancel" % run_id))
            return
        _emit(_execute(args, handlers[args.cmd]))


if __name__ == "__main__":
    main()
