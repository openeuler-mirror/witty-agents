#!/usr/bin/env python3
"""Docker / container environment tool.

Usage:
    docker.py check [--image <name>] [--mock]

Checks the Docker daemon, presence of a vLLM image, existing containers, and
whether the Ascend Docker runtime is configured (needed to map NPU devices).
"""

from __future__ import annotations

import argparse

from common import ok, err, emit, run

MOCK = {
    "docker": {"server_version": "27.1.1"},
    "ascend_runtime": True,
    "image": {"name": "vllm-ascend:latest", "present": True},
    "containers": [
        {"name": "vllm-910b", "image": "vllm-ascend:latest",
         "status": "running", "ports": "8000/tcp"},
    ],
}


RUNTIME = "docker"

def _docker_prefix(sudo):
    return ["sudo", RUNTIME] if sudo else [RUNTIME]


def _docker_ok(sudo=False):
    rc, out, stderr = run(_docker_prefix(sudo) +
                          ["version", "--format", "{{.Server.Version}}"],
                          timeout=30)
    return rc == 0, out.strip(), stderr.strip()


def _image_present(image, sudo=False):
    if not image:
        return None
    rc, out, _ = run(_docker_prefix(sudo) +
                     ["images", "--format", "{{.Repository}}:{{.Tag}}"],
                     timeout=30)
    if rc != 0:
        return None
    names = {l.strip() for l in out.splitlines() if l.strip()}
    # also match when only repo is given (no tag)
    base = image.split(":")[0]
    return image in names or any(n.split(":")[0] == base for n in names)


def _containers(sudo=False):
    rc, out, _ = run(_docker_prefix(sudo) + ["ps", "-a",
                      "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"],
                     timeout=30)
    if rc != 0:
        return []
    result = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        result.append({
            "name": parts[0],
            "image": parts[1],
            "status": parts[2],
            "ports": parts[3] if len(parts) > 3 else "",
        })
    return result


def _ascend_runtime(sudo=False):
    """Detect Ascend Docker runtime (ascend/dockerd plugin or daemon.json)."""
    rc, out, _ = run(_docker_prefix(sudo) +
                     ["info", "--format", "{{json .Runtimes}}"],
                     timeout=30)
    if rc == 0 and out.strip():
        import json as _json
        try:
            runtimes = _json.loads(out.strip())
            if any("ascend" in k.lower() or "mind" in k.lower()
                   for k in runtimes.keys()):
                return True
        except (ValueError, TypeError):
            pass
    # fall back to checking /etc/docker/daemon.json
    rc2, out2, _ = run(["sh", "-c", "cat /etc/docker/daemon.json 2>/dev/null"],
                       timeout=10)
    if rc2 == 0 and "ascend" in out2.lower():
        return True
    return False


def check(image=None, mock=False, sudo=False):
    if mock:
        return ok(MOCK)

    ok_docker, version, stderr = _docker_ok(sudo=sudo)
    if not ok_docker:
        return err("cannot reach docker daemon (may need sudo)",
                   {"stderr": stderr})

    data = {
        "docker": {"server_version": version},
        "ascend_runtime": _ascend_runtime(sudo=sudo),
        "image": {"name": image, "present": _image_present(image, sudo=sudo)} if image else None,
        "containers": _containers(sudo=sudo),
    }
    return ok(data)


def main():
    parser = argparse.ArgumentParser(description="Docker environment tool")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check")
    p.add_argument("--image", default=None)
    p.add_argument("--runtime", choices=["docker", "podman"], default="docker")
    p.add_argument("--mock", action="store_true")
    p.add_argument("--sudo", action="store_true")
    args = parser.parse_args()
    global RUNTIME
    RUNTIME = args.runtime

    if args.cmd == "check":
        emit(check(image=args.image, mock=args.mock, sudo=args.sudo))
    else:
        emit(err("unknown command: %s" % args.cmd))


if __name__ == "__main__":
    main()
