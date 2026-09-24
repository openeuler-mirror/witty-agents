#!/usr/bin/env python3
"""Online-serving performance analysis + static dashboard.

Usage:
    perf.py render --report <report_<run_id>.json> [--png vllm_performance.png]
                   [--analysis analysis.json] [--slo ttft:500,tpot:30]

`render` turns one aggregated benchmark report (all rounds) into:

    * an `analysis` object: normalized per-round rows, SLO pass/fail, a simple
      saturation heuristic and a bottleneck classification;
    * an optional static 8-panel PNG (`vllm_performance.png`).

The data layer (analysis) has no third-party dependency.  Plotting needs
matplotlib and is best-effort: if it is missing the analysis is still produced
and `plot_error` explains what to install.

Design notes / caveats (validated against vLLM 0.23 `/metrics`):
  * `TTFT breakdown` is mean-based. The server exposes `request_queue_time` and
    `request_prefill_time` but no arrival->queue gap, and client TTFT also
    includes frontend/network overhead. Means are additive (the identity holds
    per request); percentiles are NOT additive, so only means are stacked.
  * `goodput` is vLLM's per-request `request_goodput` when `--goodput` was
    passed; otherwise the SLO-passing output throughput is used as a fallback.
  * Accelerator metrics come from `npu-smi` (Ascend), not nvidia-smi/pynvml.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import ok, err, emit, read_text  # noqa: E402


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _first(row, *keys):
    for key in keys:
        value = row.get(key)
        if _num(value):
            return float(value)
    return None


def _axis_label(axis):
    return "Request rate (req/s)" if axis == "request_rate" else "Concurrency"


_SLO_ALIASES = {"ttft": "ttft_ms", "tpot": "tpot_ms", "e2el": "e2el_ms",
                "ttft_ms": "ttft_ms", "tpot_ms": "tpot_ms", "e2el_ms": "e2el_ms"}


def _parse_slo(value):
    """Parse ``--slo`` pairs, accepting both short and long keys.

    The help documents ``ttft:500,tpot:30`` but the analysis reads
    ``ttft_ms``/``tpot_ms``, so normalize short names instead of silently
    ignoring the override.
    """
    slo = {}
    for pair in (value or "").split(","):
        if not pair.strip():
            continue
        key, _, raw = pair.partition(":")
        key = _SLO_ALIASES.get(key.strip())
        if key is None:
            continue
        try:
            slo[key] = float(raw)
        except ValueError:
            continue
    return slo


def _round_row(run, report, slo):
    bench = (run.get("metrics") or {}).get("bench") or {}
    queue = (run.get("metrics") or {}).get("queue") or {}
    axis = run.get("axis") or report.get("axis") or "concurrency"
    value = run.get("value")
    if value is None:  # backward compatible with reports keyed only by concurrency
        value = run.get("concurrency")
    # ASCII tick label: the human-readable (possibly CJK) task label is kept
    # out of the figure so no CJK font is required.
    label = ("q=%s" % value) if axis == "request_rate" else ("c=%s" % value)

    ttft_mean = _first(bench, "mean_ttft_ms")
    queue_ms = _first(queue, "mean_queue_time_ms")
    prefill_ms = _first(queue, "mean_prefill_ms")
    other_ms = None
    if ttft_mean is not None:
        other_ms = max(ttft_mean - (queue_ms or 0.0) - (prefill_ms or 0.0), 0.0)

    checks = []
    if slo.get("ttft_ms"):
        checks.append(_first(bench, "p99_ttft_ms", "mean_ttft_ms") is not None
                      and _first(bench, "p99_ttft_ms", "mean_ttft_ms") <= slo["ttft_ms"])
    if slo.get("tpot_ms"):
        checks.append(_first(bench, "p99_tpot_ms", "mean_tpot_ms") is not None
                      and _first(bench, "p99_tpot_ms", "mean_tpot_ms") <= slo["tpot_ms"])
    if slo.get("e2el_ms"):
        checks.append(_first(bench, "p99_e2el_ms", "mean_e2el_ms") is not None
                      and _first(bench, "p99_e2el_ms", "mean_e2el_ms") <= slo["e2el_ms"])
    slo_pass = all(checks) if checks else None

    output_tps = _first(bench, "output_throughput")
    request_goodput = _first(bench, "request_goodput")
    # Fallback SLO-goodput: the whole round's output throughput only counts when
    # every configured SLO is met at this level.
    slo_goodput = output_tps if (slo_pass and output_tps is not None) else (0.0 if slo_pass is False else None)

    return {
        "axis": axis, "value": value, "label": label,
        "concurrency": run.get("concurrency"), "request_rate": run.get("request_rate"),
        "request_throughput": _first(bench, "request_throughput"),
        "output_throughput": output_tps,
        "total_token_throughput": _first(bench, "total_token_throughput"),
        "request_goodput": request_goodput,
        "slo_goodput": slo_goodput,
        "slo_pass": slo_pass,
        "ttft_mean": ttft_mean,
        "ttft_p50": _first(bench, "p50_ttft_ms", "median_ttft_ms"),
        "ttft_p90": _first(bench, "p90_ttft_ms"),
        "ttft_p99": _first(bench, "p99_ttft_ms"),
        "tpot_mean": _first(bench, "mean_tpot_ms"),
        "tpot_p50": _first(bench, "p50_tpot_ms", "median_tpot_ms"),
        "tpot_p90": _first(bench, "p90_tpot_ms"),
        "tpot_p99": _first(bench, "p99_tpot_ms"),
        "itl_p99": _first(bench, "p99_itl_ms"),
        "e2e_mean": _first(bench, "mean_e2el_ms", "mean_e2e_latency_ms"),
        "e2e_p99": _first(bench, "p99_e2el_ms", "p99_e2e_latency_ms"),
        "queue_ms": queue_ms,
        "prefill_ms": prefill_ms,
        "decode_ms": _first(queue, "mean_decode_ms"),
        "inference_ms": _first(queue, "mean_inference_ms"),
        "other_ms": other_ms,
        "server_ttft_ms": _first(queue, "mean_ttft_ms"),
        "queue_p99_ms": _first(queue, "queue_p99_ms"),
        "prefill_p99_ms": _first(queue, "prefill_p99_ms"),
        "ttft_server_p99_ms": _first(queue, "ttft_p99_ms"),
        "running_avg": _first(queue, "avg_running"),
        "running_max": _first(queue, "max_running"),
        "waiting_avg": _first(queue, "avg_waiting"),
        "waiting_max": _first(queue, "max_waiting"),
        "waiting_p95": _first(queue, "p95_waiting"),
        "kv_cache_avg": _first(queue, "kv_cache_avg"),
        "kv_cache_max": _first(queue, "kv_cache_max"),
        "preemptions": _first(queue, "preemptions"),
        "prefix_cache_hit_rate": _first(queue, "prefix_cache_hit_rate"),
        "npu_util_avg": _first(queue, "npu_util_avg"),
        "npu_util_max": _first(queue, "npu_util_max"),
        "npu_mem_pct_avg": _first(queue, "npu_mem_pct_avg"),
        "npu_mem_pct_max": _first(queue, "npu_mem_pct_max"),
        "failed": _first(bench, "failed"),
    }


def _growth(new, old):
    if new is None or old is None or old == 0:
        return None
    return (new - old) / old


def _classify(prev, row):
    """Heuristic bottleneck label for one level, with evidence strings."""
    labels = []
    evidence = []

    waiting = row.get("waiting_avg") or row.get("waiting_max") or 0.0
    running = row.get("running_avg") or 0.0
    kv = row.get("kv_cache_max") or row.get("kv_cache_avg") or 0.0
    preempt = row.get("preemptions") or 0.0
    npu = row.get("npu_util_avg")
    queue_ms = row.get("queue_ms")
    prefill_ms = row.get("prefill_ms")
    tpot_p99 = row.get("tpot_p99")
    ttft_p99 = row.get("ttft_p99")
    out_tps = row.get("output_throughput")

    prev_tpot = prev.get("tpot_p99") if prev else None
    prev_ttft = prev.get("ttft_p99") if prev else None
    prev_out = prev.get("output_throughput") if prev else None

    tpot_growth = _growth(tpot_p99, prev_tpot)
    ttft_growth = _growth(ttft_p99, prev_ttft)
    out_growth = _growth(out_tps, prev_out)

    if kv >= 0.95 or preempt > 0:
        labels.append("kv_cache_pressure")
        evidence.append("kv_cache_max=%.3f preemptions=%s" % (kv, preempt))
    if waiting > 0 and (queue_ms or 0) > (prefill_ms or 0) * 0.5 and (ttft_growth or 0) > 0.2:
        labels.append("queue_scheduling")
        evidence.append("waiting=%.1f queue_ms=%s ttft_p99_growth=%s"
                        % (waiting, queue_ms, _pct(ttft_growth)))
    if (prefill_ms or 0) > (queue_ms or 0) * 3 and (prefill_ms or 0) > 50:
        labels.append("prefill")
        evidence.append("prefill_ms=%s queue_ms=%s" % (prefill_ms, queue_ms))
    if tpot_growth is not None and tpot_growth > 0.15:
        labels.append("decode_saturation")
        evidence.append("tpot_p99_growth=%s" % _pct(tpot_growth))
    if waiting > 0 and npu is not None and npu < 70:
        labels.append("scheduler_cpu_frontend")
        evidence.append("waiting=%.1f npu_util=%.1f%%" % (waiting, npu))
    if npu is not None and npu >= 90 and out_growth is not None and 0 <= out_growth < 0.1:
        labels.append("accelerator_compute")
        evidence.append("npu_util=%.1f%% output_growth=%s" % (npu, _pct(out_growth)))

    if not labels:
        labels.append("healthy" if running or not waiting else "underloaded")
        evidence.append("running_avg=%.1f waiting=%.1f" % (running, waiting))
    return labels, evidence


def _pct(value):
    return "n/a" if value is None else "%.1f%%" % (value * 100.0)


def _saturation(rows):
    """First level where throughput plateaus while TTFT p99 jumps.

    Falls back to a throughput-only plateau when latency has not yet jumped
    >50%: host/scheduler-bound services flatten throughput before TTFT
    explodes, so a <5% gain is reported as near-saturation rather than missed.
    """
    plateau = None
    for prev, row in zip(rows, rows[1:]):
        out_growth = _growth(row.get("output_throughput"), prev.get("output_throughput"))
        ttft_growth = _growth(row.get("ttft_p99"), prev.get("ttft_p99"))
        if out_growth is None:
            continue
        if out_growth < 0.1 and ttft_growth is not None and ttft_growth > 0.5:
            return {
                "detected": True, "at": row["value"], "label": row["label"],
                "kind": "latency",
                "throughput_growth": round(out_growth, 4),
                "ttft_p99_growth": round(ttft_growth, 4),
                "reason": "throughput growth < 10%% while TTFT P99 grew %s" % _pct(ttft_growth),
            }
        if plateau is None and out_growth < 0.05:
            plateau = {
                "at": row["value"], "label": row["label"],
                "throughput_growth": round(out_growth, 4),
                "ttft_p99_growth": None if ttft_growth is None else round(ttft_growth, 4),
            }
    if plateau is not None:
        return {
            "detected": False, "near_saturation": True,
            "at": plateau["at"], "label": plateau["label"],
            "kind": "throughput_plateau",
            "throughput_growth": plateau["throughput_growth"],
            "ttft_p99_growth": plateau["ttft_p99_growth"],
            "reason": ("throughput plateaus (<5%% gain at %s) without a >50%% "
                       "TTFT P99 jump" % plateau["label"]),
        }
    return {"detected": False, "near_saturation": False,
            "reason": "no level showed <10% throughput gain with >50% TTFT P99 growth"}


def analyze(report, slo_override=None):
    cfg = report.get("config") or {}
    slo = dict(cfg.get("slo") or {})
    slo.update(slo_override or {})
    runs = report.get("runs") or []
    rows = [_round_row(run, report, slo) for run in runs]
    rows.sort(key=lambda r: (r["value"] is None, r["value"] if r["value"] is not None else 0))

    for i, row in enumerate(rows):
        prev = rows[i - 1] if i else None
        row["bottleneck"], row["evidence"] = _classify(prev, row)

    max_out = max((r for r in rows if r.get("output_throughput")),
                  key=lambda r: r["output_throughput"], default=None)
    max_goodput = None
    for r in rows:
        value = r.get("request_goodput")
        if _num(value) and (max_goodput is None or value > max_goodput["value"]):
            max_goodput = {"value": value, "label": r["label"]}

    slo_defined = bool(slo.get("ttft_ms") or slo.get("tpot_ms") or slo.get("e2el_ms"))
    passing = [r for r in rows if r.get("slo_pass") is True]
    slo_goodput = max((r.get("slo_goodput") or 0.0 for r in passing), default=None)

    analysis = {
        "axis": report.get("axis") or "concurrency",
        "axis_label": _axis_label(report.get("axis") or "concurrency"),
        "slo": slo, "slo_defined": slo_defined,
        "rows": rows,
        "summary": {
            "max_output_throughput": None if not max_out else {
                "value": max_out["output_throughput"], "label": max_out["label"]},
            "max_request_goodput": max_goodput,
            "max_slo_goodput": slo_goodput,
            "slo_passing_levels": [r["label"] for r in passing],
        },
        "saturation": _saturation(rows),
        "notes": list(report.get("notes") or []) + [
            "Bottleneck classification is a heuristic over aggregate metrics; "
            "it points at the next diagnostic step, it is not a proof.",
            "TTFT breakdown is mean-based and approximate (percentiles are not additive).",
            "Server queue/prefill/decode/e2e percentiles come from vLLM's coarse "
            "latency buckets (lowest boundary 0.3s): queue-time percentiles are "
            "unreliable for sub-second queues and should be read as the mean. "
            "TTFT buckets are fine-grained and reliable.",
        ],
    }
    return analysis


def render(report_path, png_path=None, analysis_path=None, slo_override=None):
    try:
        report = json.loads(read_text(report_path) or "null")
    except ValueError:
        report = None
    if not isinstance(report, dict) or not report.get("runs"):
        return err("analysis requires a report with runs", {"report": report_path})

    analysis = analyze(report, slo_override)
    if analysis_path:
        tmp = analysis_path + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(analysis, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, analysis_path)

    plot_path = None
    plot_error = None
    if png_path:
        try:
            plot_dashboard(analysis, report, png_path)
            plot_path = png_path
        except Exception as exc:  # noqa: BLE001 - plotting is optional
            plot_error = "%s: %s" % (type(exc).__name__, exc)

    return ok({"analysis": analysis, "plot_path": plot_path,
               "plot_error": plot_error,
               "analysis_output": analysis_path})


# --------------------------------------------------------------------------- #
# plotting (matplotlib is imported lazily so the data layer stays dependency free)
# --------------------------------------------------------------------------- #
def plot_dashboard(analysis, report, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    rows = analysis["rows"]
    x = [r["value"] for r in rows]
    axis_label = analysis["axis_label"]
    slo = analysis["slo"]

    def series(key):
        return [r.get(key) for r in rows]

    fig = plt.figure(figsize=(18, 14))
    gs = GridSpec(5, 2, figure=fig, height_ratios=[0.7, 1, 1, 1, 1],
                  hspace=0.55, wspace=0.22)

    # Header -------------------------------------------------------------- #
    ax0 = fig.add_subplot(gs[0, :])
    ax0.axis("off")
    cfg = report.get("config") or {}
    model = ((cfg.get("model") or {}).get("name")
             or (cfg.get("model") or {}).get("path") or "?")
    summary = analysis["summary"]
    max_out = summary["max_output_throughput"]
    goodput = summary["max_request_goodput"]
    sat = analysis["saturation"]
    lines = [
        "vLLM Online Performance   run=%s   model=%s" % (report.get("run_id"), model),
        "max output throughput: %s   |   max request goodput: %s   |   max SLO goodput: %s"
        % ("n/a" if not max_out else "%.1f tok/s @ %s" % (max_out["value"], max_out["label"]),
           "n/a" if not goodput else "%.3f req/s @ %s" % (goodput["value"], goodput["label"]),
           "n/a" if summary["max_slo_goodput"] is None else "%.1f tok/s" % summary["max_slo_goodput"]),
        "saturation: %s" % (
            "at %s (%s)" % (sat["label"], sat["reason"]) if sat.get("detected")
            else "near %s (%s)" % (sat["label"], sat["reason"])
            if sat.get("near_saturation") else "none detected"),
    ]
    if not analysis["slo_defined"]:
        lines.append("no SLO configured (set slo.ttft_ms / slo.tpot_ms for goodput + pass/fail)")
    ax0.text(0.01, 0.95, "\n".join(lines), va="top", ha="left", fontsize=11,
             family="monospace")

    def style(ax, title):
        ax.set_title(title, fontsize=11)
        ax.set_xlabel(axis_label)
        ax.grid(True, alpha=0.25)
        ax.set_xticks(x)
        ax.tick_params(labelsize=9)

    def positive(values):
        return [v if _num(v) else None for v in values]

    # 1. Throughput ------------------------------------------------------- #
    ax = fig.add_subplot(gs[1, 0])
    ax.plot(x, positive(series("request_throughput")), "o-", label="request (req/s)", color="#1f77b4")
    ax.set_ylabel("request throughput (req/s)")
    ax2 = ax.twinx()
    ax2.plot(x, positive(series("output_throughput")), "s--", label="output (tok/s)", color="#d62728")
    ax2.set_ylabel("output tokens/s")
    style(ax, "1. Throughput vs %s" % axis_label)
    _mark_saturation(ax, sat, x)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper left")

    # 2. Goodput ---------------------------------------------------------- #
    # request_goodput is in req/s while SLO goodput is in tok/s; sharing one
    # axis would flatten the former to zero, so use twin axes.
    ax = fig.add_subplot(gs[1, 1])
    ax.set_ylabel("request goodput (req/s)")
    ax2 = ax.twinx()
    ax2.set_ylabel("SLO output goodput (tok/s)")
    rq = positive(series("request_goodput"))
    if any(v is not None for v in rq):
        ax.plot(x, rq, "o-", label="vLLM request_goodput (req/s)",
                color="#2ca02c")
    else:
        ax.text(0.02, 0.9,
                "vLLM request_goodput n/a\n(bench ran without --goodput)",
                transform=ax.transAxes, fontsize=7, va="top",
                color="#555555")
    ax2.plot(x, positive(series("slo_goodput")), "s--",
             label="SLO output goodput (tok/s)", color="#ff7f0e")
    style(ax, "2. Goodput vs %s" % axis_label)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper left")
    _mark_saturation(ax, sat, x)

    # 3. TTFT ------------------------------------------------------------- #
    ax = fig.add_subplot(gs[2, 0])
    for key, color in (("ttft_p50", "#2ca02c"), ("ttft_p90", "#ff7f0e"), ("ttft_p99", "#d62728")):
        ax.plot(x, positive(series(key)), "o-", label=key.replace("ttft_", "TTFT ").upper(), color=color)
    if slo.get("ttft_ms"):
        ax.axhline(slo["ttft_ms"], color="black", ls=":", lw=1, label="SLO %.0f ms" % slo["ttft_ms"])
    style(ax, "3. TTFT P50/P90/P99")
    ax.set_ylabel("ms")
    ax.legend(fontsize=8)

    # 4. TPOT ------------------------------------------------------------- #
    ax = fig.add_subplot(gs[2, 1])
    for key, color in (("tpot_p50", "#2ca02c"), ("tpot_p90", "#ff7f0e"), ("tpot_p99", "#d62728")):
        ax.plot(x, positive(series(key)), "o-", label=key.replace("tpot_", "TPOT ").upper(), color=color)
    if slo.get("tpot_ms"):
        ax.axhline(slo["tpot_ms"], color="black", ls=":", lw=1, label="SLO %.0f ms" % slo["tpot_ms"])
    style(ax, "4. TPOT P50/P90/P99")
    ax.set_ylabel("ms")
    ax.legend(fontsize=8)

    # 5. TTFT breakdown (mean, stacked) ----------------------------------- #
    ax = fig.add_subplot(gs[3, 0])
    queue = positive(series("queue_ms"))
    prefill = positive(series("prefill_ms"))
    other = positive(series("other_ms"))
    base_q = [q or 0.0 for q in queue]
    base_p = [(q or 0.0) + (p or 0.0) for q, p in zip(queue, prefill)]
    ax.bar(x, [q or 0.0 for q in queue], width=0.5, label="queue", color="#1f77b4")
    ax.bar(x, [p or 0.0 for p in prefill], width=0.5, bottom=base_q, label="prefill", color="#ff7f0e")
    ax.bar(x, [o or 0.0 for o in other], width=0.5, bottom=base_p, label="other/residual", color="#7f7f7f")
    ax.plot(x, positive(series("ttft_mean")), "k.-", label="client mean TTFT")
    style(ax, "5. TTFT breakdown (mean; approximate)")
    ax.set_ylabel("ms")
    ax.legend(fontsize=8)

    # 6. Scheduler -------------------------------------------------------- #
    ax = fig.add_subplot(gs[3, 1])
    ax.plot(x, positive(series("running_avg")), "o-", label="running avg", color="#1f77b4")
    ax.plot(x, positive(series("running_max")), "s--", label="running max", color="#aec7e8")
    ax.plot(x, positive(series("waiting_avg")), "o-", label="waiting avg", color="#d62728")
    ax.plot(x, positive(series("waiting_max")), "s--", label="waiting max", color="#ff9896")
    style(ax, "6. Scheduler running / waiting")
    ax.set_ylabel("requests")
    ax.legend(fontsize=8)

    # 7. KV cache / preemption ------------------------------------------- #
    ax = fig.add_subplot(gs[4, 0])
    ax.plot(x, [None if v is None else v * 100.0 for v in positive(series("kv_cache_avg"))],
            "o-", label="KV usage avg", color="#9467bd")
    ax.plot(x, [None if v is None else v * 100.0 for v in positive(series("kv_cache_max"))],
            "s--", label="KV usage max", color="#c5b0d5")
    ax.set_ylabel("KV cache usage (%)")
    ax.set_ylim(0, 105)
    style(ax, "7. KV cache / preemption")
    ax3 = ax.twinx()
    ax3.bar(x, [v or 0.0 for v in positive(series("preemptions"))], width=0.3,
            alpha=0.4, color="#8c564b", label="preemptions")
    ax3.set_ylabel("preemptions (delta)")
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax3.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper left")

    # 8. Accelerator (NPU) ------------------------------------------------ #
    ax = fig.add_subplot(gs[4, 1])
    util = positive(series("npu_util_avg"))
    mem = positive(series("npu_mem_pct_avg"))
    if any(v is not None for v in util) or any(v is not None for v in mem):
        ax.plot(x, util, "o-", label="AICore util avg", color="#17becf")
        ax.plot(x, mem, "s--", label="HBM usage avg", color="#e377c2")
        ax.legend(fontsize=8)
        style(ax, "8. Accelerator util / memory (npu-smi)")
        ax.set_ylabel("%")
        ax.set_ylim(0, 105)
    else:
        style(ax, "8. Accelerator util / memory (npu-smi)")
        ax.text(0.5, 0.5, "no NPU samples collected", ha="center", va="center",
                transform=ax.transAxes, color="gray")

    fig.suptitle("vLLM Online Performance Dashboard", fontsize=15, y=0.995)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def _mark_saturation(ax, sat, x):
    if sat.get("at") not in x:
        return
    if sat.get("detected"):
        ax.axvline(sat["at"], color="red", ls="--", lw=1, alpha=0.7)
    elif sat.get("near_saturation"):
        ax.axvline(sat["at"], color="darkorange", ls=":", lw=1, alpha=0.7)


def main():
    parser = argparse.ArgumentParser(description="vLLM performance analysis")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("render")
    p.add_argument("--report", required=True)
    p.add_argument("--png", default=None)
    p.add_argument("--analysis", default=None)
    p.add_argument("--slo", default=None,
                   help="comma-separated KEY:VALUE ms, e.g. ttft:500,tpot:30")

    p = sub.add_parser("analyze")
    p.add_argument("--report", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--slo", default=None)

    args = parser.parse_args()
    slo = _parse_slo(args.slo)
    if args.cmd == "render":
        emit(render(args.report, args.png, args.analysis, slo))
    elif args.cmd == "analyze":
        report = json.loads(read_text(args.report) or "null")
        if not isinstance(report, dict) or not report.get("runs"):
            emit(err("analysis requires a report with runs", {"report": args.report}))
        analysis = analyze(report, slo)
        if args.out:
            with open(args.out, "w") as handle:
                json.dump(analysis, handle, ensure_ascii=False, indent=2)
        emit(ok(analysis))
    else:
        emit(err("unknown command: %s" % args.cmd))


if __name__ == "__main__":
    main()
