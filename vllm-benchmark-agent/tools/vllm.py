#!/usr/bin/env python3
"""vLLM service lifecycle tool (Ascend).

The agent never creates containers. It only operates on an already-existing
container named in benchmark.yaml. Scope (enforced here):

    allowed  : docker inspect / docker start / docker exec / docker stop
    forbidden: docker run / docker rm   (no container create / delete)

`docker exec` serves TWO purposes:
    1. service startup -> launch a detached `vllm serve` inside the container
    2. benchmark       -> run `vllm bench serve` (see tools/benchmark.py)

Device semantics:
    benchmark.yaml `vllm.device` holds *physical* NPU ids (as shown by
    `npu-smi info`). Inside the container the visible devices are renumbered
    0..N-1 in ascending physical-id order, and ASCEND_RT_VISIBLE_DEVICES accepts
    those *logical* ids. `launch` performs this physical -> logical conversion.

Commands:
    vllm.py ensure --name <name> [--runtime docker] [--no-start] [--sudo]
    vllm.py devices --name <name> [--runtime docker] [--sudo]
    vllm.py probe --name <name> [--port 8000] [--model <path>] [--device 2,5]
                  [--runtime docker] [--sudo]
    vllm.py launch --name <name> --model <path> [--port 8000] [--device 2]
                   [--host 0.0.0.0] [--tensor-parallel-size 1]
                   [--max-model-len 32768] [--gpu-memory-utilization 0.9]
                   [--extra-arg ...] [--log-path <data-root>/runs/<run_id>/serve.log]
                   [--no-source-env] [--runtime docker] [--sudo]
    vllm.py health [--port 8000] [--retries N] [--wait S]
    vllm.py stop --name <name> [--runtime docker] [--sudo]
    vllm.py logs --name <name> [--tail 200] [--sudo]

All commands emit structured JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import time
import urllib.request

from common import ok, err, emit, run, to_int


def _docker_prefix(sudo, runtime="docker"):
    return ["sudo", runtime] if sudo else [runtime]


# --------------------------------------------------------------------------- #
# container ensure (docker inspect / docker start only)
# --------------------------------------------------------------------------- #
def build_ensure_commands(name, sudo=False, runtime="docker"):
    """Pure helper: the inspect + start commands used by `ensure`."""
    prefix = _docker_prefix(sudo, runtime)
    inspect_cmd = prefix + ["inspect", "-f", "{{.State.Running}}", name]
    start_cmd = prefix + ["start", name]
    return inspect_cmd, start_cmd


def ensure(name, sudo=False, runtime="docker", start_if_stopped=True):
    inspect_cmd, start_cmd = build_ensure_commands(name, sudo, runtime)
    rc, out, stderr = run(inspect_cmd, timeout=30)
    if rc != 0:
        return err(
            "container not found (agent is not allowed to create containers)",
            {
                "code": "container_not_found",
                "name": name,
                "cmd": inspect_cmd,
                "stderr": stderr.strip(),
                "hint": "请确认 benchmark.yaml 的 container.name 指向一个已存在的容器；"
                        "本 agent 不会执行 docker run。",
            },
        )
    running = out.strip().lower() == "true"
    if running:
        return ok({"name": name, "running": True, "action": "already_running",
                   "cmd": inspect_cmd})
    if not start_if_stopped:
        return err("container is not running",
                   {"code": "container_not_running", "name": name,
                    "action": "none", "cmd": inspect_cmd})
    rc2, out2, stderr2 = run(start_cmd, timeout=120)
    if rc2 != 0:
        return err("docker start failed",
                   {"name": name, "cmd": start_cmd, "rc": rc2,
                    "stderr": stderr2.strip()})
    container_id = out2.strip().splitlines()[-1].strip() if out2.strip() else None
    return ok({"name": name, "running": True, "action": "started",
               "container_id": container_id, "cmd": start_cmd})


# --------------------------------------------------------------------------- #
# device mapping: physical (npu-smi) -> logical (ASCEND_RT_VISIBLE_DEVICES)
# --------------------------------------------------------------------------- #
DAVINCI_RE = re.compile(r"/dev/davinci(\d+)")
PROC_ROW_RE = re.compile(r"^\|\s*(\d+)\s+\d+\s*\|")


def parse_davinci_ids(text):
    """Extract physical NPU ids from `ls /dev/davinci*` output.

    `/dev/davinci_manager` is ignored (no trailing digits). Result is
    numerically ascending.
    """
    ids = {int(m) for m in DAVINCI_RE.findall(text or "")}
    return sorted(ids)


def physical_to_logical(visible_physical, requested):
    """Map requested *physical* NPU ids to container *logical* ids.

    Returns (logical_list, missing_list, mapping).
    """
    mapping = {p: i for i, p in enumerate(visible_physical or [])}
    logical = [mapping[p] for p in requested if p in mapping]
    missing = [p for p in requested if p not in mapping]
    return logical, missing, mapping


def visible_physical_devices(name, sudo=False, runtime="docker"):
    """Container-visible physical NPU ids (from `ls /dev/davinci*`)."""
    cmd = _docker_prefix(sudo, runtime) + [
        "exec", name, "bash", "-lc", "ls -1 /dev/davinci* 2>/dev/null"]
    rc, out, stderr = run(cmd, timeout=30)
    if rc != 0:
        return None, err("failed to list container NPU devices",
                         {"name": name, "cmd": cmd, "stderr": stderr.strip()})
    return parse_davinci_ids(out), None


def _parse_busy_ids(text):
    """Physical NPU ids that own a process, parsed from `npu-smi info`."""
    lines = (text or "").splitlines()
    proc_start = None
    for i, line in enumerate(lines):
        if "Process id" in line or "Process name" in line:
            proc_start = i
            break
    if proc_start is None:
        return []
    busy = set()
    for line in lines[proc_start + 1:]:
        m = PROC_ROW_RE.match(line.strip())
        if m:
            busy.add(to_int(m.group(1)))
    return sorted(x for x in busy if x is not None)


def busy_physical_devices(name, sudo=False, runtime="docker"):
    cmd = _docker_prefix(sudo, runtime) + [
        "exec", name, "bash", "-lc", "npu-smi info 2>/dev/null"]
    rc, out, _ = run(cmd, timeout=60)
    if rc != 0:
        return []
    return _parse_busy_ids(out)


def _parse_proc_table(text):
    """Parse the `npu-smi info` process table into [(physical_npu, container_pid)]."""
    lines = (text or "").splitlines()
    proc_start = None
    for i, line in enumerate(lines):
        if "Process id" in line or "Process name" in line:
            proc_start = i
            break
    if proc_start is None:
        return []
    out = []
    for line in lines[proc_start + 1:]:
        if not line.strip().startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 7:
            continue
        first = parts[1].split()
        if not first or not first[0].isdigit():
            continue
        cpid = int(parts[5]) if parts[5].isdigit() else None
        out.append((int(first[0]), cpid))
    return out


def _parent_map(entries):
    """pid -> ppid map from [(pid, ppid, cmd)] entries."""
    return {pid: ppid for pid, ppid, _cmd in entries}


def _ancestor_pids(pid, parent_of):
    """All ancestors of `pid` (excluding itself), cycle-safe."""
    out = set()
    cur = parent_of.get(pid)
    while cur is not None and cur not in out:
        out.add(cur)
        cur = parent_of.get(cur)
    return out


def _descendant_pids(entries, root_pid):
    """`root_pid` plus every process reachable through the parent->child chain."""
    result = {root_pid}
    while True:
        expanded = result | {p for p, parent, _ in entries if parent in result}
        if expanded == result:
            return result
        result = expanded


def _group_roots(entries, roots):
    """Union `vllm serve` roots that belong to the same process tree.

    A launcher and the process it spawns/execs are the same logical service,
    not two competing services. Reporting such a transient pair as ambiguous
    would abort a run the agent itself just started.
    """
    parent_of = _parent_map(entries)
    groups = []
    for root in roots:
        pid = root[0]
        ancestors = _ancestor_pids(pid, parent_of)
        for group in groups:
            members = {r[0] for r in group}
            if members & ancestors or any(
                    pid in _ancestor_pids(r[0], parent_of) for r in group):
                group.append(root)
                break
        else:
            groups.append([root])
    return groups


def _top_root(entries, group):
    """The top-most (fewest ancestors) root of a process-tree group."""
    parent_of = _parent_map(entries)

    def depth(root_pid):
        return len(_ancestor_pids(root_pid, parent_of))

    return min(group, key=lambda r: depth(r[0]))


def _disambiguate_roots(groups, entries, smi, requested):
    """Pick the single service tree owning exactly `requested` NPUs, else None.

    Used only when several *independent* `vllm serve` roots share the port.
    Refusing to guess (returning None) keeps the safety property: a genuine
    foreign/duplicate service is still reported as identity_unknown.
    """
    wanted = {int(x) for x in (requested or [])}
    if not wanted or len(groups) <= 1:
        return None
    matched = []
    for group in groups:
        pid = _top_root(entries, group)[0]
        occupied = {npu for npu, cpid in _parse_proc_table(smi)
                    if cpid in _descendant_pids(entries, pid)}
        if occupied and occupied == wanted:
            matched.append(group)
    return matched[0] if len(matched) == 1 else None


def _ps_entries(name, sudo=False, runtime="docker"):
    """Parse `ps -ef` inside the container into [(pid, ppid, cmd)]."""
    cmd = _docker_prefix(sudo, runtime) + [
        "exec", name, "bash", "-lc", "ps -ef 2>/dev/null"]
    rc, out, _ = run(cmd, timeout=30)
    if rc != 0:
        return []
    entries = []
    for line in out.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        if not parts[1].isdigit() or not parts[2].isdigit():
            continue
        entries.append((int(parts[1]), int(parts[2]), parts[7]))
    return entries


def vllm_serve_pids(name, sudo=False, runtime="docker"):
    """Container PIDs of `vllm serve` roots (main process only)."""
    return [pid for pid, _ppid, cmd in _ps_entries(name, sudo, runtime)
            if "vllm serve" in cmd and "grep" not in cmd]


def vllm_process_pids(name, sudo=False, runtime="docker"):
    """PIDs of `vllm serve` roots plus all their descendants.

    The NPU is usually held by a child process (e.g. `VLLM::EngineCore`), and
    `npu-smi` reports that child's container PID, so the whole tree is needed.
    """
    entries = _ps_entries(name, sudo, runtime)
    roots = [pid for pid, _ppid, cmd in entries
             if "vllm serve" in cmd and "grep" not in cmd]
    children = {}
    for pid, ppid, _cmd in entries:
        children.setdefault(ppid, set()).add(pid)
    result = set(roots)
    stack = list(roots)
    while stack:
        parent = stack.pop()
        for child in children.get(parent, ()):  # noqa: WPS526
            if child not in result:
                result.add(child)
                stack.append(child)
    return sorted(result)


def vllm_physical_devices(name, sudo=False, runtime="docker"):
    """Physical NPUs that host a `vllm serve` process (npu-smi process table)."""
    cmd = _docker_prefix(sudo, runtime) + [
        "exec", name, "bash", "-lc", "npu-smi info 2>/dev/null"]
    rc, out, _ = run(cmd, timeout=60)
    procs = _parse_proc_table(out) if rc == 0 else []
    pids = set(vllm_process_pids(name, sudo, runtime))
    return sorted({npu for npu, cpid in procs
                   if cpid is not None and cpid in pids})


def devices(name, sudo=False, runtime="docker"):
    vis, verr = visible_physical_devices(name, sudo, runtime)
    if verr:
        return verr
    mapping = {p: i for i, p in enumerate(vis)}
    return ok({"name": name, "visible_physical": vis,
               "logical_map": {str(k): v for k, v in mapping.items()}})


# --------------------------------------------------------------------------- #
# health / model identity
# --------------------------------------------------------------------------- #
def _http_get(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 - surface any network error
        return None, str(e)


def endpoint_get(name, path, port=8000, host="127.0.0.1", sudo=False, runtime="docker"):
    """Use the same container network namespace as the benchmark client."""
    host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    url = "http://%s:%d%s" % (host, port, path)
    if not name:
        return _http_get(url)
    code = ("import urllib.request; r=urllib.request.urlopen(%r,timeout=10); "
            "print(r.status); print(r.read().decode())") % url
    rc, out, stderr = run(_docker_prefix(sudo, runtime) +
                          ["exec", name, "python3", "-c", code], timeout=15)
    if rc:
        return None, stderr
    status, _, body = out.partition("\n")
    return to_int(status), body


def check_health(port=8000, name=None, host="127.0.0.1", sudo=False, runtime="docker"):
    status, _ = endpoint_get(name, "/health", port, host, sudo, runtime)
    models = None
    if status == 200:
        mstatus, body = endpoint_get(name, "/v1/models", port, host, sudo, runtime)
        if mstatus == 200:
            try:
                models = json.loads(body)
            except ValueError:
                pass
    return {"healthy": status == 200, "status": status, "models": models}


def health(port=8000, retries=1, wait=0, **kwargs):
    res = {}
    for i in range(max(1, retries)):
        res = check_health(port, **kwargs)
        if res["healthy"]:
            return ok(res)
        if i + 1 < retries:
            time.sleep(wait)
    return err("vLLM not healthy", res)


def model_ids(models):
    if not isinstance(models, dict):
        return []
    data = models.get("data")
    if not isinstance(data, list):
        return []
    return [d.get("id") for d in data if isinstance(d, dict)]


def model_matches(models, model):
    """True/False, or None when no model was requested to compare.

    A checkpoint may be exposed under an alias (``--served-model-name``): the
    `/v1/models` id then differs from the configured path, but its `root` still
    points at that checkpoint. Match id, root and parent so an aliased service
    is recognised as the requested model rather than a foreign one.
    """
    if not model:
        return None
    data = models.get("data") if isinstance(models, dict) else None
    if not isinstance(data, list) or not data:
        return False
    target = model.rstrip("/")
    for entry in data:
        if not isinstance(entry, dict):
            continue
        for field in ("id", "root", "parent"):
            value = entry.get(field)
            if isinstance(value, str) and value and value.rstrip("/") == target:
                return True
    return False


# --------------------------------------------------------------------------- #
# probe: is a vLLM service already running on the requested physical NPUs?
# --------------------------------------------------------------------------- #
SHELL_NAMES = ("bash", "sh", "dash", "zsh", "ksh")
# Shell control operators that terminate a launcher script's argument region.
_SHELL_OPERATORS = {">", ">>", "<", "<<", "1>", "1>>", "2>", "2>>",
                    "&>", "&>>", "|", "||", "&&", ";", "&"}


def _is_shell_operator(token):
    """True for shell redirections / control operators, never option values."""
    if token in _SHELL_OPERATORS:
        return True
    return token.startswith(">") or token.startswith("<")


def _options_from_tokens(tokens):
    """Build a flag -> value map from argv tokens.

    A structured value (begins with ``{`` or ``[``) is rejoined up to the next
    flag, so both exact `/proc` argv and re-split `ps args=` tokens (where the
    shell quoting is lost and a JSON value arrives as several fragments) map to
    the same option value.
    """
    options = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("-"):
            key, sep, value = token.partition("=")
            if sep:
                options[key] = value
            elif i + 1 >= len(tokens) or tokens[i + 1].startswith("--"):
                options[key] = True
            elif tokens[i + 1][:1] in ("{", "["):
                j = i + 1
                parts = []
                while (j < len(tokens) and not tokens[j].startswith("--")
                       and not _is_shell_operator(tokens[j])):
                    parts.append(tokens[j])
                    j += 1
                options[key] = " ".join(parts)
                i = j
                continue
            else:
                options[key] = tokens[i + 1]
        i += 1
    return options


def _argv_from_cmdline(argv):
    """Normalize exact `/proc/<pid>/cmdline` argv into service tokens.

    The launcher may still be a shell (``bash -lc '<script>'``) before it
    `exec`s the server; there the real argv is the script, so split it with
    shell rules (the script keeps JSON values single-quoted, so they survive).
    Otherwise the argv is already exact and used verbatim.
    """
    shell = argv[0].rsplit("/", 1)[-1] if argv else ""
    if (len(argv) >= 3 and shell in SHELL_NAMES
            and argv[1] in ("-c", "-lc", "-cl", "-l")):
        try:
            return shlex.split(argv[-1])
        except ValueError:
            return argv
    return argv


def _proc_cmdline(name, pid, sudo=False, runtime="docker"):
    """Exact argv of a container process via /proc/<pid>/cmdline.

    Preferred over ``ps -o args=`` because `ps` joins argv with spaces and drops
    shell quoting, which corrupts JSON-valued options such as
    ``--speculative-config {"method": "..."}``. Returns None when unavailable,
    so callers can fall back to the `ps` command line.
    """
    prefix = _docker_prefix(sudo, runtime)
    cmd = prefix + ["exec", name, "bash", "-lc",
                    "cat /proc/%d/cmdline 2>/dev/null | tr '\\0' '\\n'" % int(pid)]
    rc, out, _ = run(cmd, timeout=15)
    if rc != 0 or not out:
        return None
    tokens = [line for line in out.split("\n") if line != ""]
    return tokens or None


def _argv_options(command):
    """Parse a space-joined command line (legacy `ps args=` form)."""
    tokens = shlex.split(command)
    return tokens, _options_from_tokens(tokens)


def _normalize_option_value(value):
    """Canonical form for comparing option values against a live process.

    The process command line is read back through `ps`, which drops quoting.
    Comparing after removing whitespace and quote characters therefore matches
    the value the agent launched while still catching real differences.
    """
    if isinstance(value, bool) or value is None:
        return value
    return re.sub(r"[\s\"']", "", str(value))


def probe(name, port=8000, model=None, physical_ids=None, sudo=False,
          runtime="docker", host="127.0.0.1", expected=None):
    requested = list(physical_ids or [])
    prefix = _docker_prefix(sudo, runtime)
    rc, out, stderr = run(build_ensure_commands(name, sudo, runtime)[0], timeout=30)
    if rc:
        return err("cannot inspect target container", {"code": "container_unavailable", "stderr": stderr})
    if out.strip().lower() != "true":
        return ok({"decision": "container_stopped", "container": name})
    visible, failure = visible_physical_devices(name, sudo, runtime)
    if failure:
        return failure
    logical, missing, mapping = physical_to_logical(visible, requested)
    data = {"container": name, "requested_physical": requested,
            "visible_physical": visible, "logical_devices": logical,
            "device_map": mapping, "missing_devices": missing}
    if missing:
        return ok(dict(data, decision="device_unavailable"))
    # An unreadable resource/process table is unknown, never equivalent to idle.
    rc, smi, stderr = run(prefix + ["exec", name, "bash", "-lc", "npu-smi info"], timeout=60)
    if rc or "Process" not in smi:
        return err("cannot determine NPU ownership", {"stderr": stderr})
    from ascend import parse_npu_smi
    inventory = parse_npu_smi(smi)
    unhealthy = [d["id"] for d in inventory["devices"] if d.get("health") != "OK"]
    if not inventory["count"] or any(x in unhealthy for x in requested):
        return ok(dict(data, decision="device_unhealthy", inventory=inventory))
    rc, ps, stderr = run(prefix + ["exec", name, "ps", "-eo", "pid=,ppid=,args="], timeout=30)
    if rc:
        return err("cannot inspect service processes", {"stderr": stderr})
    entries = []
    for line in ps.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            entries.append((int(fields[0]), int(fields[1]), fields[2]))
    roots = []
    for pid, _, command in entries:
        if "vllm serve" not in command:
            continue
        argv = _proc_cmdline(name, pid, sudo, runtime)
        if argv:
            tokens = _argv_from_cmdline(argv)
            options = _options_from_tokens(tokens)
        else:
            tokens, options = _argv_options(command)
        if str(options.get("--port", 8000)) == str(port):
            roots.append((pid, tokens, options))
    h = check_health(port, name=name, host=host, sudo=sudo, runtime=runtime)
    data.update(health=h, served_models=model_ids(h.get("models")))
    busy = _parse_busy_ids(smi)
    data["npu_busy_physical"] = busy
    data["root_pids"] = [pid for pid, _, _ in roots]
    data["root_count"] = len(roots)
    if roots:
        groups = _group_roots(entries, roots)
        if len(groups) > 1:
            chosen = _disambiguate_roots(groups, entries, smi, requested)
            if chosen is None:
                return ok(dict(
                    data, decision="identity_unknown",
                    root_groups=[[pid for pid, _, _ in g] for g in groups]))
            groups = [chosen]
        pid, tokens, options = _top_root(entries, groups[0])
        descendants = _descendant_pids(entries, pid)
        occupied = sorted({npu for npu, cpid in _parse_proc_table(smi) if cpid in descendants})
        data.update(service_pid=pid, vllm_physical_devices=occupied,
                    device_match=set(occupied) == set(requested), actual_options=options)
        serve_index = tokens.index("serve")
        actual_model = tokens[serve_index + 1] if serve_index + 1 < len(tokens) else None
        if model and actual_model and actual_model.rstrip("/") != model.rstrip("/"):
            return ok(dict(data, decision="model_mismatch"))
        mismatches = {}
        for key, flag in (("tensor_parallel_size", "--tensor-parallel-size"),
                          ("max_model_len", "--max-model-len"),
                          ("gpu_memory_utilization", "--gpu-memory-utilization")):
            wanted = (expected or {}).get(key)
            actual = options.get(flag, options.get("-tp") if key == "tensor_parallel_size" else None)
            if wanted is not None:
                try:
                    matches = float(actual) == float(wanted)
                except (TypeError, ValueError):
                    matches = False
                if not matches:
                    mismatches[key] = {"expected": wanted, "actual": actual}
        wanted_extra = _options_from_tokens(
            [str(x) for x in (expected or {}).get("extra_args", [])])
        for key, value in wanted_extra.items():
            if _normalize_option_value(options.get(key)) != _normalize_option_value(value):
                mismatches[key] = {"expected": value, "actual": options.get(key)}
        if mismatches:
            return ok(dict(data, decision="config_mismatch", mismatches=mismatches))
        if occupied and requested and set(occupied) != set(requested):
            # While the service is still starting, workers bind their NPUs at
            # slightly different times, so the process table can be partial and
            # look like a mismatch. Treat that as loading; only trust the check
            # once the endpoint is healthy.
            if h["healthy"]:
                return ok(dict(data, decision="device_mismatch"))
            return ok(dict(data, decision="loading"))
        if h["healthy"]:
            if model_matches(h.get("models"), model) is False:
                return ok(dict(data, decision="model_mismatch"))
            if requested and not occupied:
                return ok(dict(data, decision="identity_unknown"))
            return ok(dict(data, decision="already_running"))
        return ok(dict(data, decision="loading"))
    if h["healthy"]:
        return ok(dict(data, decision="identity_unknown"))
    if any(x in busy for x in (requested or visible)):
        return ok(dict(data, decision="device_busy"))
    # Verify the bind in the container, rather than inferring availability from HTTP.
    bind_host = "0.0.0.0" if host in ("127.0.0.1", "localhost") else host
    code = "import socket; s=socket.socket(); s.bind((%r,%d)); s.close()" % (bind_host, port)
    rc, _, stderr = run(prefix + ["exec", name, "python3", "-c", code], timeout=15)
    if rc:
        return ok(dict(data, decision="port_unavailable", evidence=stderr))
    if model and model.startswith("/"):
        rc, _, stderr = run(prefix + ["exec", name, "test", "-d", model], timeout=15)
        if rc:
            return ok(dict(data, decision="model_unavailable", evidence=stderr))
    return ok(dict(data, decision="need_start"))


# --------------------------------------------------------------------------- #
# launch a detached `vllm serve` via docker exec -d
# --------------------------------------------------------------------------- #
SOURCE_ENV = (
    "for f in /usr/local/Ascend/ascend-toolkit/set_env.sh "
    "/usr/local/Ascend/cann-*/share/info/ascendnpu-ir/bin/set_env.sh "
    "/usr/local/Ascend/nnal/atb/set_env.sh; do "
    '[ -f "$f" ] && . "$f" >/dev/null 2>&1; done'
)


def build_serve_command(params):
    """Pure helper: build the `vllm serve ...` argv from resolved params."""
    cmd = ["vllm", "serve", params["model"]]
    cmd += ["--host", str(params.get("host") or "0.0.0.0")]
    cmd += ["--port", str(params.get("port", 8000))]
    tp = params.get("tensor_parallel_size")
    if tp:
        cmd += ["--tensor-parallel-size", str(tp)]
    mml = params.get("max_model_len")
    if mml:
        cmd += ["--max-model-len", str(mml)]
    gmu = params.get("gpu_memory_utilization")
    if gmu is not None:
        cmd += ["--gpu-memory-utilization", str(gmu)]
    cmd += [str(a) for a in (params.get("extra_args") or [])]
    return cmd


def build_launch_command(name, serve_cmd, logical_devices=None, sudo=False,
                         runtime="docker", log_path=None, source_env=True):
    """Pure helper: `docker exec -d` a detached vllm serve. Never run/rm."""
    cmd = _docker_prefix(sudo, runtime) + ["exec", "-d"]
    if logical_devices:
        cmd += ["-e", "ASCEND_RT_VISIBLE_DEVICES=%s"
                % ",".join(str(d) for d in logical_devices)]
    cmd += [name, "bash", "-lc"]
    inner = []
    if source_env:
        inner.append(SOURCE_ENV)
    serve = "exec " + " ".join(shlex.quote(c) for c in serve_cmd)
    if log_path:
        serve += " > " + shlex.quote(log_path) + " 2>&1"
    inner.append(serve)
    cmd += ["; ".join(inner)]
    return cmd


def launch(name, serve_cmd, physical_ids=None, sudo=False, runtime="docker",
           log_path=None, source_env=True):
    """Start a detached `vllm serve`, binding the requested physical NPUs.

    Physical ids are converted to the container-internal logical ids expected by
    ASCEND_RT_VISIBLE_DEVICES.
    """
    physical_ids = list(physical_ids or [])
    logical = []
    visible = []
    if physical_ids:
        visible, verr = visible_physical_devices(name, sudo, runtime)
        if verr:
            return verr
        logical, missing, _ = physical_to_logical(visible, physical_ids)
        if missing:
            return err(
                "requested physical NPU(s) not visible in container",
                {"requested_physical": physical_ids, "visible_physical": visible,
                 "missing": missing,
                 "hint": "fix vllm.device in benchmark.yaml (physical ids, "
                         "as shown by npu-smi info)"})

    cmd = build_launch_command(name, serve_cmd, logical, sudo, runtime,
                               log_path, source_env)
    rc, out, stderr = run(cmd, timeout=60)
    if rc != 0:
        return err("failed to launch vllm serve via docker exec",
                   {"cmd": cmd, "rc": rc, "stderr": stderr.strip()})
    return ok({"name": name, "action": "launched",
               "physical_devices": physical_ids,
               "visible_physical": visible,
               "logical_devices": logical, "log_path": log_path,
               "command": cmd})


# --------------------------------------------------------------------------- #
# stop / logs
# --------------------------------------------------------------------------- #
def stop(name, sudo=False, runtime="docker"):
    """Stop the container. Never removes it (no `docker rm`)."""
    cmd = _docker_prefix(sudo, runtime) + ["stop", name]
    rc, _, stderr = run(cmd, timeout=120)
    if rc != 0:
        return err("docker stop failed",
                   {"name": name, "cmd": cmd, "rc": rc,
                    "stderr": stderr.strip()})
    return ok({"stopped": name, "rc": rc, "removed": False})


def logs(name, tail=200, sudo=False):
    cmd = _docker_prefix(sudo) + ["logs", "--tail", str(tail), name]
    rc, out, stderr = run(cmd, timeout=60)
    if rc != 0:
        return err("docker logs failed", {"stderr": stderr.strip()})
    return ok({"name": name, "tail": tail, "logs": out})


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _ids(raw):
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [x for x in raw.replace(" ", "").split(",") if x != ""]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = [raw]
    out = []
    for x in items:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def main():
    parser = argparse.ArgumentParser(description="vLLM lifecycle tool")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ensure")
    p.add_argument("--name", default="vllm-bench")
    p.add_argument("--runtime", default="docker")
    p.add_argument("--no-start", dest="no_start", action="store_true")
    p.add_argument("--sudo", action="store_true")

    p = sub.add_parser("devices")
    p.add_argument("--name", default="vllm-bench")
    p.add_argument("--runtime", default="docker")
    p.add_argument("--sudo", action="store_true")

    p = sub.add_parser("probe")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--expected", default=None)
    p.add_argument("--name", default="vllm-bench")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--model", default=None)
    p.add_argument("--device", default=None,
                   help="comma-separated physical NPU ids, e.g. 2,5")
    p.add_argument("--runtime", default="docker")
    p.add_argument("--sudo", action="store_true")

    p = sub.add_parser("launch")
    p.add_argument("--name", default="vllm-bench")
    p.add_argument("--model", required=True)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--device", default=None,
                   help="comma-separated physical NPU ids, e.g. 2")
    p.add_argument("--tensor-parallel-size", dest="tensor_parallel_size",
                   type=int, default=None)
    p.add_argument("--max-model-len", dest="max_model_len", type=int,
                   default=None)
    p.add_argument("--gpu-memory-utilization", dest="gpu_memory_utilization",
                   type=float, default=None)
    p.add_argument("--extra-arg", dest="extra_arg", action="append",
                   default=None)
    p.add_argument("--log-path", dest="log_path", default=None)
    p.add_argument("--no-source-env", dest="no_source_env", action="store_true")
    p.add_argument("--runtime", default="docker")
    p.add_argument("--sudo", action="store_true")

    p = sub.add_parser("health")
    p.add_argument("--name", default=None)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--runtime", default="docker")
    p.add_argument("--sudo", action="store_true")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--retries", type=int, default=1)
    p.add_argument("--wait", type=int, default=0)

    p = sub.add_parser("stop")
    p.add_argument("--name", default="vllm-bench")
    p.add_argument("--runtime", default="docker")
    p.add_argument("--sudo", action="store_true")

    p = sub.add_parser("logs")
    p.add_argument("--name", default="vllm-bench")
    p.add_argument("--tail", type=int, default=200)
    p.add_argument("--sudo", action="store_true")

    args = parser.parse_args()
    if args.cmd == "ensure":
        emit(ensure(args.name, sudo=args.sudo, runtime=args.runtime,
                    start_if_stopped=not args.no_start))
    elif args.cmd == "devices":
        emit(devices(args.name, sudo=args.sudo, runtime=args.runtime))
    elif args.cmd == "probe":
        emit(probe(args.name, port=args.port, model=args.model,
                   physical_ids=_ids(args.device), sudo=args.sudo,
                   runtime=args.runtime, host=args.host,
                   expected=json.loads(args.expected) if args.expected else None))
    elif args.cmd == "launch":
        params = {
            "model": args.model, "host": args.host, "port": args.port,
            "tensor_parallel_size": args.tensor_parallel_size,
            "max_model_len": args.max_model_len,
            "gpu_memory_utilization": args.gpu_memory_utilization,
            "extra_args": args.extra_arg or [],
        }
        emit(launch(args.name, build_serve_command(params),
                    physical_ids=_ids(args.device), sudo=args.sudo,
                    runtime=args.runtime, log_path=args.log_path,
                    source_env=not args.no_source_env))
    elif args.cmd == "health":
        emit(health(port=args.port, retries=args.retries, wait=args.wait, name=args.name,
                    host=args.host, runtime=args.runtime, sudo=args.sudo))
    elif args.cmd == "stop":
        emit(stop(args.name, sudo=args.sudo, runtime=args.runtime))
    elif args.cmd == "logs":
        emit(logs(args.name, tail=args.tail, sudo=args.sudo))
    else:
        emit(err("unknown command: %s" % args.cmd))


if __name__ == "__main__":
    main()
