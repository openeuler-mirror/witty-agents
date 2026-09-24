#!/usr/bin/env python3
"""Per-NPU advisory locks for the vLLM benchmark agent.

A lock means "this NPU is owned by a run's vLLM service", not "this CLI
process is running".  The benchmark CLI is short-lived, while the vLLM service
it launched (or reused) keeps occupying the device, so ownership must outlive
the process that created it.  A lock is therefore only released when the
service is gone (container stopped / explicit `stop`), or reclaimed when it is
provably stale (owning run terminal AND pid dead AND device free).

Metadata is written under a short ``flock`` critical section so two processes
cannot interleave a read-modify-write on the same lock file.  The lock itself
must NOT be held by the process; metadata + run state is the ownership record.

Layout::

    <data_root>/locks/npu_<physical_id>.lock   # JSON metadata
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import time


def lock_path(locks_root, device_id):
    return os.path.join(locks_root, "npu_%s.lock" % int(device_id))


def read_meta(path):
    try:
        with open(path, "r") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def snapshot(locks_root, device_ids):
    """Current metadata for each requested device (None when unlocked)."""
    return {int(d): read_meta(lock_path(locks_root, d))
            for d in sorted({int(x) for x in device_ids or []})}


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except OSError as exc:
        return exc.errno == errno.EPERM
    return True


def _default_active(meta):
    """Fallback liveness: the creating process is still running."""
    return _pid_alive(meta.get("pid"))


def _write_locked(path, meta):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            handle.seek(0)
            handle.truncate()
            json.dump(meta, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def try_acquire(locks_root, device_ids, run_id, pid=None, is_active=None,
                details=None):
    """Acquire every requested device lock atomically (all or nothing).

    ``is_active(meta)`` decides whether an existing owner still holds the
    device; it defaults to pid liveness.  A lock already owned by ``run_id``
    is reclaimed idempotently (so a run can re-probe its own device).

    Returns ``(ok, holders, acquired)`` where ``holders`` maps a busy device id
    to the blocking metadata.
    """
    devices = sorted({int(x) for x in device_ids or []})
    if not devices:
        return True, {}, []
    active = is_active or _default_active
    holders = {}
    for device_id in devices:
        meta = read_meta(lock_path(locks_root, device_id))
        if not meta or meta.get("run_id") == run_id:
            continue
        if active(meta):
            holders[device_id] = meta
    if holders:
        return False, holders, []

    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    meta = {"run_id": run_id, "pid": pid or os.getpid(),
            "created_at": now, "updated_at": now, "devices": devices}
    if details:
        meta.update(details)
    for device_id in devices:
        _write_locked(lock_path(locks_root, device_id),
                      dict(meta, device=device_id))
    return True, {}, devices


def release(locks_root, device_ids, run_id):
    """Release devices only if they are owned by ``run_id``."""
    released = []
    for device_id in sorted({int(x) for x in device_ids or []}):
        path = lock_path(locks_root, device_id)
        meta = read_meta(path)
        if not meta or meta.get("run_id") != run_id:
            continue
        try:
            os.remove(path)
            released.append(device_id)
        except OSError:
            pass
    return released


def release_all(locks_root, device_ids):
    """Release devices regardless of owner (used when a service is stopped)."""
    released = []
    for device_id in sorted({int(x) for x in device_ids or []}):
        path = lock_path(locks_root, device_id)
        if not os.path.exists(path):
            continue
        try:
            os.remove(path)
            released.append(device_id)
        except OSError:
            pass
    return released
