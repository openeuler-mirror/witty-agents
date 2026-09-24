import { existsSync, readFileSync, watch } from "node:fs"
import { dirname, join } from "node:path"
import type { BenchmarkSnapshot, UiPointer } from "./benchmark-types"

export interface BenchmarkTracker {
  dispose(): void
}

const POINTER_PARTS = [".vllm-benchmark", "current.json"]
const DEBOUNCE_MS = 80
const FALLBACK_POLL_MS = 2000

/**
 * Watches the active run directory (and the pointer directory) and pushes a
 * parsed snapshot on change.
 *
 * `pointerCandidates` are tried in order; the first existing file wins. This
 * matters because opencode can be started from any directory, so the plugin
 * cannot assume the benchmark project is its worktree. A user-home pointer is
 * normally the most reliable candidate.
 *
 * The runner writes files with write-tmp-then-rename (tools/common.py), so
 * watching the file itself loses events after the first replace: the watcher
 * stays attached to the old inode. We therefore watch *directories*, debounce
 * the event burst, and keep a low-frequency poll as a safety net.
 *
 * This is a cross-process filesystem channel: no LLM, no MCP, no Todo API.
 */
export function createBenchmarkTracker(
  pointerCandidates: string[],
  onChange: (snapshot: BenchmarkSnapshot) => void,
): BenchmarkTracker {
  const candidates = Array.from(new Set(pointerCandidates.filter(Boolean)))
  const watchers = new Map<string, ReturnType<typeof watch>>()
  let pointerPath = resolvePointer()
  let disposed = false
  let debounceTimer: ReturnType<typeof setTimeout> | undefined

  function resolvePointer(): string {
    for (const candidate of candidates) {
      try {
        if (existsSync(candidate)) return candidate
      } catch {
        /* ignore */
      }
    }
    return candidates[0] ?? join(...POINTER_PARTS)
  }

  const readPointer = (): UiPointer | undefined => {
    try {
      return JSON.parse(readFileSync(pointerPath, "utf8")) as UiPointer
    } catch {
      return undefined
    }
  }

  const readSnapshot = (): BenchmarkSnapshot | undefined => {
    const pointer = readPointer()
    if (!pointer?.progress || !pointer?.tasks) return undefined
    try {
      return {
        pointer,
        progress: JSON.parse(readFileSync(pointer.progress, "utf8")),
        tasks: JSON.parse(readFileSync(pointer.tasks, "utf8")),
      }
    } catch {
      return undefined
    }
  }

  const refresh = () => {
    if (disposed) return
    const snapshot = readSnapshot()
    if (snapshot) onChange(snapshot)
  }

  const scheduleRefresh = () => {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      attach()
      refresh()
    }, DEBOUNCE_MS)
  }

  const watchDir = (dir: string) => {
    if (!dir || watchers.has(dir)) return
    try {
      const w = watch(dir, { persistent: false }, scheduleRefresh)
      w.on("error", () => {
        try {
          w.close()
        } catch {
          /* ignore */
        }
        watchers.delete(dir)
      })
      watchers.set(dir, w)
    } catch {
      /* ignore: poll fallback still covers this directory */
    }
  }

  const attach = () => {
    const resolved = resolvePointer()
    if (resolved !== pointerPath) {
      // A different candidate became available (e.g. the runner just started);
      // drop stale watches and follow the new pointer.
      pointerPath = resolved
      for (const w of watchers.values()) {
        try {
          w.close()
        } catch {
          /* ignore */
        }
      }
      watchers.clear()
    }
    watchDir(dirname(pointerPath))
    const pointer = readPointer()
    if (pointer?.tasks) watchDir(dirname(pointer.tasks))
  }

  const poll = setInterval(() => {
    attach()
    refresh()
  }, FALLBACK_POLL_MS)

  attach()
  refresh()

  return {
    dispose() {
      disposed = true
      if (debounceTimer) clearTimeout(debounceTimer)
      clearInterval(poll)
      for (const w of watchers.values()) {
        try {
          w.close()
        } catch {
          /* ignore */
        }
      }
      watchers.clear()
    },
  }
}
