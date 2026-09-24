#!/usr/bin/env python3
"""Metrics collection tool.

Usage:
    metrics.py scrape --url http://127.0.0.1:8000/metrics
                      [--seconds 60] [--interval 1] --out <file>
                      [--npu-devices 5,6] [--model <model>] [--container NAME]
    metrics.py collect --bench <bench_result.json>
                       --queue <queue_timeseries.json> [--out <file>]
                       [--select ttft,tpot,latency,throughput,goodput,
                                 request_timeline,queue_time,server,gpu]

`scrape` polls the vLLM Prometheus `/metrics` endpoint and records a compact
time series of queue / scheduling / KV-cache metrics.  When `--npu-devices` is
given it also samples `npu-smi info` on the host each interval so accelerator
utilisation / HBM usage can be correlated with each benchmark round.

`collect` merges the `vllm bench serve` result JSON with the queue time series
into a single metrics report (TTFT / TPOT / latency / throughput / goodput /
queue / server breakdown / accelerator).  `--select` restricts the report to the
requested metric groups.

Metric names follow vLLM 0.23 (`/metrics`); histogram buckets are kept for the
timing histograms so server-side percentiles can be derived without a Prometheus
server.

Caveats validated against vLLM 0.23:
  * `time-per-output-token` is `vllm:request_time_per_output_token_seconds`
    (there is no `vllm:time_per_output_token_seconds`), and
    `vllm:num_requests_swapped` no longer exists.
  * `vllm:request_queue_time_seconds` etc. use coarse buckets whose lowest
    boundary is 0.3s; bucket-derived queue percentiles are unreliable for
    sub-second queues.  `vllm:time_to_first_token_seconds` buckets are
    fine-grained and reliable.  Means are always exact.
"""

from __future__ import annotations

import argparse
import re
import math
import signal
import threading
import json
import os
import time
import urllib.request

from common import ok, err, emit, read_text, to_float, now_iso, run

# Gauges aggregated by sum across engines (total pending work).
GAUGE_SUM = [
    "vllm:num_requests_running",
    "vllm:num_requests_waiting",
]

# Gauges aggregated by max across engines (per-engine pressure).
GAUGE_MAX = [
    "vllm:kv_cache_usage_perc",  # 1.0 == 100% KV-cache usage
]

# Monotonic counters; a per-round report uses last-minus-first.
COUNTERS = [
    "vllm:num_preemptions_total",
    "vllm:prefix_cache_queries_total",
    "vllm:prefix_cache_hits_total",
]

# Histograms exposed as _sum/_count (means) and, where listed below, _bucket
# (percentiles).  Note the vLLM 0.23 names: time-per-output-token is
# `request_time_per_output_token_seconds`, not `time_per_output_token_seconds`.
HISTOGRAMS = [
    "vllm:request_queue_time_seconds",
    "vllm:request_prefill_time_seconds",
    "vllm:request_decode_time_seconds",
    "vllm:request_inference_time_seconds",
    "vllm:time_to_first_token_seconds",
    "vllm:request_time_per_output_token_seconds",
    "vllm:e2e_request_latency_seconds",
    "vllm:inter_token_latency_seconds",
]

# Only these keep raw buckets: enough to give server-side queue / prefill /
# decode / TTFT percentiles for the TTFT-breakdown panel.
BUCKET_HISTOGRAMS = [
    "vllm:request_queue_time_seconds",
    "vllm:request_prefill_time_seconds",
    "vllm:request_decode_time_seconds",
    "vllm:time_to_first_token_seconds",
]

_SCALAR_NAMES = set(GAUGE_SUM) | set(GAUGE_MAX) | set(COUNTERS) | {
    h + suffix for h in HISTOGRAMS for suffix in ("_sum", "_count")}

# Metric groups selectable via `--select` (mirrors benchmark.yaml metrics.collect)
BENCH_GROUPS = {
    "ttft": ["mean_ttft_ms", "median_ttft_ms", "p50_ttft_ms", "p90_ttft_ms",
             "p99_ttft_ms"],
    "tpot": ["mean_tpot_ms", "median_tpot_ms", "p50_tpot_ms", "p90_tpot_ms",
             "p99_tpot_ms", "mean_itl_ms", "median_itl_ms",
             "p50_itl_ms", "p90_itl_ms", "p99_itl_ms"],
    "latency": ["mean_e2e_latency_ms", "median_e2e_latency_ms",
                "p50_e2e_latency_ms", "p90_e2e_latency_ms",
                "p99_e2e_latency_ms",
                "mean_e2el_ms", "median_e2el_ms",
                "p50_e2el_ms", "p90_e2el_ms", "p99_e2el_ms"],
    "throughput": ["output_throughput", "request_throughput",
                   "total_token_throughput", "max_output_tokens_per_s",
                   "max_concurrent_requests"],
    "goodput": ["request_goodput"],
}
BENCH_BASE = ["elapsed_time", "duration", "num_prompts", "completed", "failed",
              "request_rate"]

QUEUE_GROUPS = {
    "ttft": ["mean_ttft_ms"],
    "request_timeline": ["timeline"],
    "queue_time": ["mean_queue_time_ms", "queue_p50_ms", "queue_p90_ms",
                   "queue_p99_ms"],
    "server": ["mean_prefill_ms", "mean_decode_ms", "mean_inference_ms",
               "prefill_p50_ms", "prefill_p90_ms", "prefill_p99_ms",
               "ttft_p50_ms", "ttft_p90_ms", "ttft_p99_ms",
               "mean_tpot_ms", "mean_e2e_ms",
               "kv_cache_avg", "kv_cache_max", "preemptions",
               "prefix_cache_hit_rate"],
    "gpu": ["npu_util_avg", "npu_util_max",
            "npu_mem_pct_avg", "npu_mem_pct_max"],
}
QUEUE_BASE = ["samples", "avg_waiting", "max_waiting", "p95_waiting",
              "avg_running", "max_running", "p95_running"]

# Groups whose absence is reported but never blocks a run.
OPTIONAL_GROUPS = {"goodput", "gpu"}


def _allowed(select, groups, base):
    """Return the set of allowed keys, or None to allow everything."""
    if not select:
        return None
    allowed = set(base)
    for name in select:
        allowed.update(groups.get(name, []))
    return allowed


def _http_get(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None


def parse_prometheus(text, model=None):
    """Parse labelled samples and aggregate only the selected model's series.

    Gauges listed in GAUGE_SUM are summed across engines, GAUGE_MAX is the max,
    counters / histogram _sum/_count are summed, and configured `_bucket`
    series are kept as a nested {le: cumulative} mapping.
    """
    if not text:
        return {}
    out = {}
    sums = {}
    maxes = {}
    buckets = {}
    pattern = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+([^\s]+)')
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        name, labels, raw = match.groups()
        if labels and model:
            identity = re.search(r'model_name="((?:[^"\\]|\\.)*)"', labels)
            if identity and json.loads('"' + identity.group(1) + '"').rstrip("/") != model.rstrip("/"):
                continue
        value = to_float(raw)
        if value is None or not math.isfinite(value):
            continue
        if name.endswith("_bucket"):
            base = name[:-len("_bucket")]
            if base not in BUCKET_HISTOGRAMS:
                continue
            le = re.search(r'le="([^"]+)"', labels or "")
            if not le:
                continue
            bucket = buckets.setdefault(base, {})
            bucket[le.group(1)] = bucket.get(le.group(1), 0.0) + value
            continue
        if name in GAUGE_MAX:
            maxes[name] = value if name not in maxes else max(maxes[name], value)
        elif name in _SCALAR_NAMES:
            sums[name] = sums.get(name, 0.0) + value
    out.update(sums)
    out.update(maxes)
    for base, bucket in buckets.items():
        out[base + "_buckets"] = bucket
    return out


def _sample_npu(devices=None):
    """Sample `npu-smi info` once; returns {device_id: {...}} or None."""
    try:
        from ascend import parse_npu_smi
    except ImportError:
        return None
    rc, out, _stderr = run(["npu-smi", "info"], timeout=15)
    if rc != 0:
        return None
    try:
        inventory = parse_npu_smi(out)
    except Exception:  # noqa: BLE001
        return None
    wanted = set(devices) if devices else None
    result = {}
    for dev in inventory.get("devices", []):
        did = dev.get("id")
        if wanted is not None and did not in wanted:
            continue
        result[str(did)] = {
            "aicore": dev.get("aicore"),
            "hbm_used_mb": dev.get("hbm_used_mb"),
            "hbm_total_mb": dev.get("hbm_total_mb"),
            "temp_c": dev.get("temp_c"),
        }
    return result or None


def scrape(url, seconds, interval, out_path, container=None, runtime="docker",
           sudo=False, model=None, npu_devices=None):
    from urllib.parse import urlparse
    from vllm import endpoint_get
    stop = threading.Event()
    old = signal.signal(signal.SIGTERM, lambda *_: stop.set())
    samples = []
    end = time.monotonic() + seconds
    errors = 0

    def sample():
        nonlocal errors
        if container:
            parsed_url = urlparse(url)
            status, text = endpoint_get(container, parsed_url.path, parsed_url.port or 8000,
                                        parsed_url.hostname, sudo, runtime)
            if status != 200:
                text = None
        else:
            text = _http_get(url)
        parsed = parse_prometheus(text, model) if text is not None else {}
        if not parsed:
            errors += 1
        row = {"ts": now_iso(), **parsed,
               **({"error": "metrics_unavailable"} if not parsed else {})}
        if npu_devices is not None:
            npu = _sample_npu(npu_devices)
            if npu:
                row["npu"] = npu
        samples.append(row)
        _write_atomic(out_path, samples)

    try:
        sample()  # baseline written before the client starts
        while not stop.wait(interval) and time.monotonic() < end:
            sample()
        sample()  # final counters after the client exits
    finally:
        signal.signal(signal.SIGTERM, old)
    return ok({"samples": len(samples), "errors": errors, "path": out_path})


def _write_atomic(path, samples):
    """Write the sample list so the file is always a complete JSON array,
    even if the process is killed mid-scrape."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(samples, f, ensure_ascii=False)
    os.replace(tmp, path)


def _norm_bench(result, select=None):
    """Flatten the vllm bench saved-result JSON into a clean dict."""
    if not isinstance(result, dict):
        return result
    keys = [
        "elapsed_time", "duration", "num_prompts", "completed", "failed", "request_rate",
        "output_throughput", "request_throughput", "total_token_throughput",
        "max_output_tokens_per_s", "max_concurrent_requests", "request_goodput",
        "mean_ttft_ms", "median_ttft_ms", "p50_ttft_ms", "p90_ttft_ms", "p99_ttft_ms",
        "mean_tpot_ms", "median_tpot_ms", "p50_tpot_ms", "p90_tpot_ms", "p99_tpot_ms",
        "mean_itl_ms", "median_itl_ms", "p50_itl_ms", "p90_itl_ms", "p99_itl_ms",
        "mean_e2e_latency_ms", "median_e2e_latency_ms", "p50_e2e_latency_ms",
        "p90_e2e_latency_ms", "p99_e2e_latency_ms",
        "mean_e2el_ms", "median_e2el_ms", "p50_e2el_ms", "p90_e2el_ms", "p99_e2el_ms",
    ]
    allowed = _allowed(select, BENCH_GROUPS, BENCH_BASE)
    out = {}
    for k in keys:
        if k in result and (allowed is None or k in allowed):
            out[k] = result[k]
    return out


def _delta(samples, key):
    """Last-minus-first for cumulative counters (histogram sum/count)."""
    vals = [s.get(key) for s in samples if s.get(key) is not None]
    if len(vals) < 2:
        return None
    if any(b < a for a, b in zip(vals, vals[1:])):
        return None
    return vals[-1] - vals[0]


def _percentile(values, q):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    rank = (len(vals) - 1) * q
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return vals[lo]
    return vals[lo] + (vals[hi] - vals[lo]) * (rank - lo)


def _agg(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return {}
    return {"avg": round(sum(vals) / len(vals), 3),
            "max": round(max(vals), 3),
            "p95": round(_percentile(vals, 0.95), 3)}


def _hist_mean_ms(samples, base):
    total = _delta(samples, base + "_sum")
    count = _delta(samples, base + "_count")
    if total is None or not count:
        return None
    return round(total / count * 1000.0, 3)


def _bucket_delta(samples, base):
    key = base + "_buckets"
    series = [s.get(key) for s in samples if isinstance(s.get(key), dict)]
    if len(series) < 2:
        return None
    first, last = series[0], series[-1]
    les = set(first) & set(last)
    if not les:
        return None
    delta = {}
    for le in les:
        a, b = first[le], last[le]
        if b < a:  # counter reset
            return None
        delta[le] = b - a
    return delta


def _hist_quantile_ms(samples, base, q):
    """Prometheus-style linear interpolation over cumulative bucket deltas."""
    delta = _bucket_delta(samples, base)
    count = _delta(samples, base + "_count")
    if not delta or not count:
        return None

    def le_value(le):
        return math.inf if le in ("+Inf", "Inf") else float(le)

    buckets = sorted(delta.items(), key=lambda kv: le_value(kv[0]))
    rank = q * count
    prev_le = 0.0
    prev_count = 0.0
    for le, cumulative in buckets:
        upper = le_value(le)
        if cumulative >= rank:
            if math.isinf(upper):
                return None if not prev_le else round(prev_le * 1000.0, 3)
            span = cumulative - prev_count
            if span <= 0:
                return round(upper * 1000.0, 3)
            frac = (rank - prev_count) / span
            return round((prev_le + (upper - prev_le) * frac) * 1000.0, 3)
        prev_le, prev_count = upper, cumulative
    return None


def _npu_summary(samples):
    util, mem = [], []
    for s in samples:
        npu = s.get("npu") or {}
        if not isinstance(npu, dict):
            continue
        utils, mems = [], []
        for dev in npu.values():
            if not isinstance(dev, dict):
                continue
            if dev.get("aicore") is not None:
                utils.append(dev["aicore"])
            used, total = dev.get("hbm_used_mb"), dev.get("hbm_total_mb")
            if used is not None and total:
                mems.append(used / total * 100.0)
        if utils:
            util.append(sum(utils) / len(utils))
        if mems:
            mem.append(max(mems))
    out = {}
    if util:
        out.update(npu_util_avg=round(sum(util) / len(util), 3),
                   npu_util_max=round(max(util), 3))
    if mem:
        out.update(npu_mem_pct_avg=round(sum(mem) / len(mem), 3),
                   npu_mem_pct_max=round(max(mem), 3))
    return out


def analyze_queue(samples, select=None):
    waiting = [s.get("vllm:num_requests_waiting") for s in samples
               if s.get("vllm:num_requests_waiting") is not None]
    running = [s.get("vllm:num_requests_running") for s in samples
               if s.get("vllm:num_requests_running") is not None]
    kv = [s.get("vllm:kv_cache_usage_perc") for s in samples
          if s.get("vllm:kv_cache_usage_perc") is not None]

    timeline = [{"ts": s["ts"], "waiting": s.get("vllm:num_requests_waiting"),
                 "running": s.get("vllm:num_requests_running"),
                 "kv_cache_usage": s.get("vllm:kv_cache_usage_perc")}
                for s in samples]

    preemptions = _delta(samples, "vllm:num_preemptions_total")
    queries = _delta(samples, "vllm:prefix_cache_queries_total")
    hits = _delta(samples, "vllm:prefix_cache_hits_total")
    hit_rate = (hits / queries) if (hits is not None and queries) else None

    result = {
        "samples": len(samples),
        "avg_waiting": round(sum(waiting) / len(waiting), 3) if waiting else None,
        "max_waiting": max(waiting) if waiting else None,
        "p95_waiting": round(_percentile(waiting, 0.95), 3) if waiting else None,
        "avg_running": round(sum(running) / len(running), 3) if running else None,
        "max_running": max(running) if running else None,
        "p95_running": round(_percentile(running, 0.95), 3) if running else None,
        "kv_cache_avg": round(sum(kv) / len(kv), 4) if kv else None,
        "kv_cache_max": max(kv) if kv else None,
        "preemptions": preemptions,
        "prefix_cache_hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
        "mean_queue_time_ms": _hist_mean_ms(samples, "vllm:request_queue_time_seconds"),
        "mean_prefill_ms": _hist_mean_ms(samples, "vllm:request_prefill_time_seconds"),
        "mean_decode_ms": _hist_mean_ms(samples, "vllm:request_decode_time_seconds"),
        "mean_inference_ms": _hist_mean_ms(samples, "vllm:request_inference_time_seconds"),
        "mean_ttft_ms": _hist_mean_ms(samples, "vllm:time_to_first_token_seconds"),
        "mean_tpot_ms": _hist_mean_ms(samples, "vllm:request_time_per_output_token_seconds"),
        "mean_e2e_ms": _hist_mean_ms(samples, "vllm:e2e_request_latency_seconds"),
        "timeline": timeline,
    }
    for base, prefix in (("vllm:request_queue_time_seconds", "queue"),
                         ("vllm:request_prefill_time_seconds", "prefill"),
                         ("vllm:request_decode_time_seconds", "decode"),
                         ("vllm:time_to_first_token_seconds", "ttft")):
        for p in (50, 90, 99):
            value = _hist_quantile_ms(samples, base, p / 100.0)
            if value is not None:
                result["%s_p%d_ms" % (prefix, p)] = value
    result.update(_npu_summary(samples))

    allowed = _allowed(select, QUEUE_GROUPS, QUEUE_BASE)
    if allowed is not None:
        result = {k: v for k, v in result.items() if k in allowed}
    return result


def collect(bench_path, queue_path, out_path=None, select=None):
    try:
        bench = json.loads(read_text(bench_path) or "null")
    except ValueError:
        bench = None
    try:
        queue = json.loads(read_text(queue_path) or "[]")
    except ValueError:
        queue = []

    problems = []
    if not isinstance(bench, dict) or not bench:
        problems.append("benchmark result missing or invalid")
    if isinstance(bench, dict) and (bench.get("failed", 0) or bench.get("completed") == 0):
        problems.append("benchmark contains failed requests or no completed requests")
    groups = select or list(BENCH_GROUPS) + list(QUEUE_GROUPS)
    normalized = _norm_bench(bench, select) if isinstance(bench, dict) else {}
    for group in groups:
        if group in OPTIONAL_GROUPS:
            continue
        if group in BENCH_GROUPS and not any(isinstance(normalized.get(k), (float, int)) and math.isfinite(normalized[k]) for k in BENCH_GROUPS[group]):
            problems.append("missing benchmark group: " + group)
    if not isinstance(queue, list):
        queue = []
    queue = [x for x in queue if isinstance(x, dict) and "ts" in x]
    queue_summary = analyze_queue(queue, select) if queue else {}
    if "queue_time" in groups and queue_summary.get("mean_queue_time_ms") is None:
        problems.append("queue time requires valid baseline/final counter deltas")
    if "server" in groups and queue_summary.get("mean_prefill_ms") is None:
        problems.append("server prefill time requires valid histogram deltas")
    if "request_timeline" in groups and (len(queue) < 2 or any(x.get("vllm:num_requests_waiting") is None for x in queue)):
        problems.append("service queue timeline is incomplete")
    report = {
        "bench": _norm_bench(bench, select) if isinstance(bench, dict) else bench,
        "queue": analyze_queue(queue, select) if queue else {},
        "metrics_select": select or "all",
    }
    report["quality"] = {"complete": not problems, "problems": problems}
    if out_path:
        with open(out_path, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    return err("incomplete metrics", report) if problems else ok(report)


def _parse_select(value):
    if not value:
        return None
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in str(value).split(",") if x.strip()]


def _parse_ids(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value).replace(" ", "").split(",")
    out = []
    for item in items:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def main():
    parser = argparse.ArgumentParser(description="Metrics collection tool")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scrape")
    p.add_argument("--url", required=True)
    p.add_argument("--container", default=None)
    p.add_argument("--runtime", default="docker")
    p.add_argument("--sudo", action="store_true")
    p.add_argument("--model", default=None)
    p.add_argument("--npu-devices", dest="npu_devices", default=None,
                   help="comma-separated physical NPU ids to sample via npu-smi")
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--out", required=True)

    p = sub.add_parser("collect")
    p.add_argument("--bench", required=True)
    p.add_argument("--queue", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--select", default=None)

    args = parser.parse_args()
    if args.cmd == "scrape":
        emit(scrape(args.url, args.seconds, args.interval, args.out,
                    args.container, args.runtime, args.sudo, args.model,
                    _parse_ids(args.npu_devices)))
    elif args.cmd == "collect":
        emit(collect(args.bench, args.queue, args.out,
                     select=_parse_select(args.select)))
    else:
        emit(err("unknown command: %s" % args.cmd))


if __name__ == "__main__":
    main()
