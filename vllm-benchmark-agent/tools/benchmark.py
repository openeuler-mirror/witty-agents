#!/usr/bin/env python3
"""vLLM benchmark execution tool (wraps `vllm bench serve`).

Usage:
    benchmark.py run --model <model> [--container vllm-bench] [--host 127.0.0.1]
                     [--port 8000] [--num-prompts 1000] [--request-rate 10]
                     [--max-concurrency 16] [--input-len 1024] [--output-len 128]
                     [--runtime docker] [--local] [--sudo]

By default the benchmark client runs inside the vLLM container via
`docker exec` (the vLLM Python package lives there). Pass `--local` to run
`vllm bench serve` directly on the host instead.

The result JSON produced by `--save-result` is parsed and returned, together
with the tail of the human-readable summary table.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import time
import uuid
import signal

from common import ok, err, emit, run, now_iso, duration_sec


def _docker_prefix(sudo, runtime="docker"):
    return ["sudo", runtime] if sudo else [runtime]


def build_bench_command(params, result_path):
    cmd = ["vllm", "bench", "serve"]
    cmd += ["--backend", "vllm"]
    cmd += ["--model", params["model"]]
    if params.get("tokenizer"):
        cmd += ["--tokenizer", params["tokenizer"]]
    cmd += ["--host", params.get("host", "127.0.0.1")]
    cmd += ["--port", str(params.get("port", 8000))]
    cmd += ["--num-prompts", str(params.get("num_prompts", 1000))]
    if params.get("request_rate") is not None:
        cmd += ["--request-rate", str(params["request_rate"])]
    if params.get("max_concurrency") is not None:
        cmd += ["--max-concurrency", str(params["max_concurrency"])]
    cmd += ["--dataset-name", params.get("dataset_name", "random")]
    cmd += ["--random-input-len", str(params.get("input_len", 1024))]
    cmd += ["--random-output-len", str(params.get("output_len", 128))]
    # vLLM generation defaults percentile metrics to "ttft,tpot,itl";
    # end-to-end latency (e2el) must be requested explicitly or it is
    # absent from the saved result JSON.
    cmd += ["--percentile-metrics", "ttft,tpot,itl,e2el"]
    cmd += ["--metric-percentiles", params.get("metric_percentiles", "50,90,99")]
    # goodput SLOs, e.g. ["ttft:500", "tpot:30"] (milliseconds). `--goodput`
    # takes nargs='+', so all pairs go in a single occurrence or argparse
    # overwrites earlier ones. `request_goodput` stays null without it.
    goodput = params.get("goodput") or []
    if goodput:
        cmd += ["--goodput"] + [str(slo) for slo in goodput]
    cmd += ["--save-result", "--result-dir", os.path.dirname(result_path),
            "--result-filename", os.path.basename(result_path)]
    return cmd


def build_exec_command(params, bench_cmd):
    """Pure helper: wrap `bench_cmd` in `docker exec` for the bench session.

    ASCEND_RT_VISIBLE_DEVICES (logical ids) only applies to this exec session;
    it does not change the already-running vLLM server.
    """
    exec_cmd = _docker_prefix(params.get("sudo", False),
                              params.get("runtime", "docker")) + ["exec"]
    visible = params.get("visible_devices")
    if visible:
        exec_cmd += ["-e", "ASCEND_RT_VISIBLE_DEVICES=%s" % visible]
    exec_cmd += [params.get("container", "vllm-bench"), "bash", "-lc",
                 " ".join(shlex.quote(c) for c in bench_cmd)]
    return exec_cmd


def _read_result(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def run_bench(params):
    start = time.time()
    result_dir = params.get("result_dir", "/tmp/vllm-benchmark")
    os.makedirs(result_dir, exist_ok=True)
    tag = uuid.uuid4().hex
    host_path = os.path.join(result_dir, "bench_%s.json" % tag)
    remote_path = "/tmp/vllm_bench_%s.json" % tag
    pid_path = "/tmp/vllm_bench_%s.pid" % tag
    local = params.get("local", False)
    command = build_bench_command(params, host_path if local else remote_path)
    timeout = params.get("timeout", 3600)
    prefix = _docker_prefix(params.get("sudo", False), params.get("runtime", "docker"))
    container = params.get("container", "vllm-bench")
    used = command
    try:
        if not local:
            # An in-container process group permits cleanup even when docker exec disconnects.
            used = build_exec_command(params, command)
            inner = " ".join(shlex.quote(c) for c in command)
            used[-1] = "setsid timeout --signal=TERM --kill-after=5s %ss %s & p=$!; echo $p > %s; wait $p" % (timeout, inner, shlex.quote(pid_path))
        env = None
        if local and params.get("visible_devices"):
            env = dict(os.environ, ASCEND_RT_VISIBLE_DEVICES=params["visible_devices"])
        rc, out, stderr = run(used, timeout=timeout + 10, env=env)
        if rc:
            return err("vllm bench failed", {"rc": rc, "stderr_tail": stderr[-4000:],
                                            "stdout_tail": out[-2000:], "command": used})
        if not local:
            cp_rc, _, cp_err = run(prefix + ["cp", container + ":" + remote_path, host_path], timeout=60)
            if cp_rc:
                return err("cannot copy benchmark result", {"stderr": cp_err})
        result = _read_result(host_path)
        if not isinstance(result, dict):
            return err("benchmark produced no valid result", {"result_path": host_path})
        if result.get("failed", 0) or result.get("completed", params["num_prompts"]) != params["num_prompts"]:
            return err("benchmark did not complete all requests", {"result": result, "result_path": host_path})
        return ok({"elapsed_sec": duration_sec(start), "result": result,
                   "result_path": host_path, "command": used, "finished_at": now_iso(),
                   "summary_table": "\n".join(out.splitlines()[-40:])})
    finally:
        if not local:
            # Disable the inherited cancellation marker for the cleanup command only.
            cleanup_env = dict(os.environ)
            cleanup_env.pop("BENCHMARK_CANCEL_PATH", None)
            cleanup = ('if [ -f {p} ]; then read p < {p}; '
                       'case "$p" in *[!0-9]*|"") exit 1;; esac; '
                       'kill -TERM -- -"$p" 2>/dev/null || true; '
                       'sleep 1; kill -KILL -- -"$p" 2>/dev/null || true; fi').format(p=shlex.quote(pid_path))
            # run() checks the parent's marker; temporarily remove it during cleanup.
            marker = os.environ.pop("BENCHMARK_CANCEL_PATH", None)
            try:
                run(prefix + ["exec", container, "bash", "-lc", cleanup], timeout=15, env=cleanup_env)
            finally:
                if marker:
                    os.environ["BENCHMARK_CANCEL_PATH"] = marker


def main():
    parser = argparse.ArgumentParser(description="vLLM benchmark tool")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--model", required=True)
    p.add_argument("--tokenizer", default=None)
    p.add_argument("--container", default="vllm-bench")
    p.add_argument("--runtime", default="docker")
    p.add_argument("--visible-devices", dest="visible_devices", default=None,
                   help="ASCEND_RT_VISIBLE_DEVICES for the exec/local session")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--num-prompts", dest="num_prompts", type=int, default=1000)
    p.add_argument("--request-rate", dest="request_rate", type=float, default=None)
    p.add_argument("--max-concurrency", dest="max_concurrency",
                   type=int, default=None)
    p.add_argument("--dataset-name", dest="dataset_name", default="random")
    p.add_argument("--input-len", dest="input_len", type=int, default=1024)
    p.add_argument("--output-len", dest="output_len", type=int, default=128)
    p.add_argument("--metric-percentiles", dest="metric_percentiles",
                   default="50,90,99",
                   help="comma-separated percentiles reported by vllm bench")
    p.add_argument("--goodput", action="append", default=None,
                   help="SLO pair KEY:VALUE in ms, e.g. ttft:500 (repeatable)")
    p.add_argument("--result-dir", dest="result_dir", default="/tmp/vllm-benchmark")
    p.add_argument("--timeout", type=int, default=3600)
    p.add_argument("--local", action="store_true")
    p.add_argument("--sudo", action="store_true")
    args = parser.parse_args()
    def interrupted(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)

    if args.cmd == "run":
        emit(run_bench(vars(args)))
    else:
        emit(err("unknown command: %s" % args.cmd))


if __name__ == "__main__":
    main()
