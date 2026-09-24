#!/usr/bin/env python3
"""Benchmark configuration loader.

The YAML config file (default: <project root>/benchmark.yaml) is the single
source of truth for the benchmark. Every field is optional; missing fields fall
back to DEFAULTS so callers always receive a complete, normalized config.

Usage:
    config.py path                          print the default config path
    config.py show [--config PATH]          print the resolved config as JSON
    config.py get KEY [KEY ...] [--config PATH]
                                            print resolved value(s) by dotted key
"""

from __future__ import annotations

import argparse
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:  # run as a script (tools/ on sys.path)
    from common import ok, err, emit  # noqa: E402
except ImportError:  # imported as a package (tools.config)
    from tools.common import ok, err, emit  # noqa: E402


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.environ.get("VLLM_BENCHMARK_CONFIG", os.path.join(os.getcwd(), "benchmark.yaml"))

DEFAULTS = {
    "model": {"name": None, "path": None},
    "container": {"name": "vllm-bench", "image": None, "runtime": "docker"},
    "vllm": {
        "host": "0.0.0.0",
        "port": 8000,
        # physical NPU ids as shown by `npu-smi info` (docker renumbers them
        # to logical 0..N-1 inside the container, in this order)
        "device": [],
        "tensor_parallel_size": 1,
        "max_model_len": None,
        "gpu_memory_utilization": 0.9,
        # Optional OpenAI model id the server advertises via
        # `--served-model-name`. When set, probe identity checks and client
        # requests use it, while the tokenizer still uses model.path.
        "served_model_name": None,
        "extra_args": [],
    },
    "benchmark": {
        # concurrency sweep axis (default). Each entry runs `requests` requests
        # with --max-concurrency set to the entry.
        "concurrency": [1],
        # optional single request rate (req/s) applied to every concurrency
        # round; null means send as fast as possible (request_rate=inf).
        "request_rate": None,
        # optional QPS sweep axis. When set it takes precedence over
        # `concurrency`: each entry runs with --request-rate=<entry> and
        # optionally --max-concurrency=<max_concurrency>.
        "request_rates": None,
        "max_concurrency": None,
        "input_tokens": 1024,
        "output_tokens": 128,
        "requests": 1000,
        # percentiles requested from `vllm bench serve` (50/90/99 by default).
        "metric_percentiles": [50, 90, 99],
    },
    # Service-level objectives used for goodput / SLO-passing analysis. All
    # optional; values are milliseconds. When any is set it is also forwarded
    # to `vllm bench serve --goodput`.
    "slo": {"ttft_ms": None, "tpot_ms": None, "e2el_ms": None},
    "metrics": {
        "collect": ["ttft", "tpot", "latency", "throughput", "goodput",
                    "request_timeline", "queue_time", "server", "gpu"],
        "interval": 1.0,
    },
    # Relative output paths are resolved against the data directory
    # (VLLM_BENCHMARK_DATA_DIR), not the source tree.
    "report": {"output": "./reports"},
    # Post-run cleanup. When stop_service is true the agent stops the service
    # it launched once the run completes; a reused service is left running.
    "cleanup": {"stop_service": True},
}


def _deep_merge(base, override):
    """Recursively merge `override` onto a copy of `base`."""
    if not isinstance(override, dict):
        return override
    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _load_yaml(path):
    try:
        import yaml
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError("PyYAML is required to read %s" % path) from e
    with open(path, "r") as f:
        loaded = yaml.safe_load(f)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("config root must be a mapping, got %s"
                         % type(loaded).__name__)
    return loaded


def _as_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int_list(value):
    """Coerce a list / comma string / scalar into a de-duplicated list[int]."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [x for x in value.replace(" ", "").split(",") if x != ""]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = [value]
    out = []
    for item in items:
        n = _as_int(item, None)
        if n is not None and n not in out:
            out.append(n)
    return out


def normalize(cfg):
    """Validate without silently replacing invalid user values.

    Missing sections/keys are filled from DEFAULTS so an older frozen config
    (e.g. from a run saved before the SLO/sweep options existed) can still be
    resumed; present-but-invalid values are never silently defaulted.
    """
    import math
    for section, defaults in DEFAULTS.items():
        current = cfg.get(section)
        if current is None:
            cfg[section] = copy.deepcopy(defaults)
        elif not isinstance(current, dict):
            raise ValueError(section + " must be a mapping")
        else:
            for key, value in defaults.items():
                current.setdefault(key, copy.deepcopy(value))

    def number(section, key, minimum=1, maximum=None, integer=True, optional=False):
        value = cfg[section].get(key)
        if value is None and optional:
            return
        try:
            n = float(value)
            if isinstance(value, bool) or not math.isfinite(n) or n < minimum:
                raise ValueError()
            if maximum is not None and n > maximum:
                raise ValueError()
            if integer and n != int(n):
                raise ValueError()
        except (ValueError, TypeError, OverflowError):
            raise ValueError("%s.%s has invalid value: %r" % (section, key, value))
        cfg[section][key] = int(n) if integer else n

    v = cfg["vllm"]
    devices = v.get("device") or []
    if not isinstance(devices, list) or any(type(x) is not int or x < 0 for x in devices):
        raise ValueError("vllm.device must be a list of physical NPU ids")
    if len(set(devices)) != len(devices):
        raise ValueError("vllm.device contains duplicates")
    v["device"] = devices
    if v.get("tensor_parallel_size") is None:
        v["tensor_parallel_size"] = len(devices) or 1
    number("vllm", "port", maximum=65535)
    number("vllm", "tensor_parallel_size")
    number("vllm", "max_model_len", optional=True)
    number("vllm", "gpu_memory_utilization", minimum=0.000001, maximum=1, integer=False)
    if devices and v["tensor_parallel_size"] != len(devices):
        raise ValueError("vllm.tensor_parallel_size must equal the selected device count")
    if not isinstance(v.get("host"), str) or not v["host"]:
        raise ValueError("vllm.host is required")
    if not isinstance(v.get("extra_args"), list):
        raise ValueError("vllm.extra_args must be an argv list")
    v["extra_args"] = [str(x) for x in v["extra_args"]]
    reserved = {"--model", "--host", "--port", "--tensor-parallel-size", "-tp",
                "--max-model-len", "--gpu-memory-utilization"}
    if any(x.split("=", 1)[0] in reserved for x in v["extra_args"]):
        raise ValueError("extra_args must not override dedicated vllm configuration fields")
    served = v.get("served_model_name")
    if served is not None:
        if not isinstance(served, str) or not served.strip():
            raise ValueError("vllm.served_model_name must be a non-empty string")
        v["served_model_name"] = served.strip()
        extra = v["extra_args"]
        for i, item in enumerate(extra):
            if item == "--served-model-name" and i + 1 < len(extra):
                if extra[i + 1] != v["served_model_name"]:
                    raise ValueError(
                        "vllm.served_model_name disagrees with "
                        "--served-model-name in extra_args")
            elif item.startswith("--served-model-name="):
                if item.split("=", 1)[1] != v["served_model_name"]:
                    raise ValueError(
                        "vllm.served_model_name disagrees with "
                        "--served-model-name in extra_args")
    for key in ("requests", "input_tokens", "output_tokens"):
        number("benchmark", key)
    number("benchmark", "request_rate", minimum=0.000001, integer=False, optional=True)
    levels = cfg["benchmark"].get("concurrency")
    if not isinstance(levels, list) or not levels or any(type(x) is not int or x < 1 for x in levels):
        raise ValueError("benchmark.concurrency must be a nonempty list of positive integers")
    if len(set(levels)) != len(levels):
        raise ValueError("benchmark.concurrency contains duplicates")
    rates = cfg["benchmark"].get("request_rates")
    if rates is not None:
        if not isinstance(rates, list) or not rates:
            raise ValueError("benchmark.request_rates must be a nonempty list of request rates")
        cleaned = []
        for rate in rates:
            try:
                n = float(rate)
            except (TypeError, ValueError):
                raise ValueError("benchmark.request_rates has invalid value: %r" % (rate,))
            if isinstance(rate, bool) or not math.isfinite(n) or n < 0.000001:
                raise ValueError("benchmark.request_rates has invalid value: %r" % (rate,))
            if n not in cleaned:
                cleaned.append(n)
        cfg["benchmark"]["request_rates"] = cleaned
    number("benchmark", "max_concurrency", optional=True)
    percentiles = cfg["benchmark"].get("metric_percentiles")
    if not isinstance(percentiles, list) or not percentiles or any(
            isinstance(p, bool) or not isinstance(p, (int, float))
            or not 0 < float(p) < 100 for p in percentiles):
        raise ValueError("benchmark.metric_percentiles must be numbers in (0, 100)")
    cfg["benchmark"]["metric_percentiles"] = sorted({float(p) for p in percentiles})
    slo = cfg.get("slo")
    if not isinstance(slo, dict):
        raise ValueError("slo must be a mapping")
    for key in DEFAULTS["slo"]:
        value = slo.get(key)
        if value is None:
            continue
        try:
            n = float(value)
            if isinstance(value, bool) or not math.isfinite(n) or n <= 0:
                raise ValueError()
        except (ValueError, TypeError, OverflowError):
            raise ValueError("slo.%s has invalid value: %r" % (key, value))
        slo[key] = n
    if v.get("max_model_len") and sum(cfg["benchmark"][k] for k in ("input_tokens", "output_tokens")) > v["max_model_len"]:
        raise ValueError("input_tokens + output_tokens exceeds vllm.max_model_len")
    number("metrics", "interval", minimum=0.000001, integer=False)
    collect = cfg["metrics"].get("collect")
    if not isinstance(collect, list) or not collect or any(x not in DEFAULTS["metrics"]["collect"] for x in collect):
        raise ValueError("metrics.collect contains unsupported groups or is empty")
    if cfg["container"].get("runtime") not in ("docker", "podman"):
        raise ValueError("container.runtime must be docker or podman")
    for section, key in (("container", "name"), ("report", "output")):
        if not isinstance(cfg[section].get(key), str) or not cfg[section][key]:
            raise ValueError(section + "." + key + " is required")
    if not isinstance(cfg["cleanup"].get("stop_service"), bool):
        raise ValueError("cleanup.stop_service must be a boolean")
    if not (cfg["model"].get("path") or cfg["model"].get("name")):
        raise ValueError("model.path or model.name is required")
    return cfg


def load(path=None, validate=True):
    """Load, merge with DEFAULTS and normalize the config."""
    path = path or DEFAULT_CONFIG_PATH
    exists = os.path.isfile(path)
    raw = _load_yaml(path)
    merged = _deep_merge(DEFAULTS, raw)
    if validate:
        normalize(merged)
    merged["_config_path"] = os.path.abspath(path)
    merged["_config_exists"] = exists
    return merged


def _get(cfg, dotted):
    cur = cfg
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def main():
    parser = argparse.ArgumentParser(description="Benchmark config loader")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("path")

    p = sub.add_parser("show")
    p.add_argument("--config", default=None)
    p.add_argument("--unvalidated", action="store_true", help=argparse.SUPPRESS)

    p = sub.add_parser("get")
    p.add_argument("keys", nargs="+")
    p.add_argument("--config", default=None)

    args = parser.parse_args()
    if args.cmd == "path":
        emit(ok({"path": DEFAULT_CONFIG_PATH}))
        return

    try:
        cfg = load(args.config, validate=not getattr(args, "unvalidated", False))
    except Exception as e:  # noqa: BLE001
        emit(err("failed to load config",
                 {"config": args.config or DEFAULT_CONFIG_PATH,
                  "detail": str(e)}))
        return

    if args.cmd == "show":
        emit(ok({"config": cfg}))
    elif args.cmd == "get":
        emit(ok({k: _get(cfg, k) for k in args.keys}))


if __name__ == "__main__":
    main()
