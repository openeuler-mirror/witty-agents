import type { TaskStatus } from "./benchmark-types"

export type Tone = "success" | "warning" | "error" | "info" | "muted"

export function statusMeta(status?: string): { icon: string; tone: Tone } {
  switch (status as TaskStatus | undefined) {
    case "completed":
      return { icon: "✓", tone: "success" }
    case "running":
      return { icon: "→", tone: "info" }
    case "blocked":
      return { icon: "!", tone: "warning" }
    case "failed":
      return { icon: "✗", tone: "error" }
    case "cancelled":
      return { icon: "-", tone: "muted" }
    case "skipped":
      return { icon: "–", tone: "muted" }
    default:
      return { icon: "○", tone: "muted" }
  }
}

export function truncate(label: string, maxLength = 72): string {
  if (label.length <= maxLength) return label
  if (maxLength <= 1) return label.slice(0, maxLength)
  return `${label.slice(0, maxLength - 1)}…`
}

/** Pure presentation: the DeepSeek whale reflects overall run state. */
export function mascot(state?: string): string {
  switch (state) {
    case "DONE":
      return "✓ 🐳"
    case "FAILED":
    case "CANCELLED":
      return "! 🐳"
    case "IDLE":
    case "":
    case undefined:
      return "🐳"
    default:
      return "🐳 ~~~>"
  }
}

/**
 * Elapsed time is computed locally from `started_at` for running rows, so the
 * TUI can tick every second without the runner writing every second. Finished
 * rows use the runner's frozen `elapsed_sec`.
 */
export function formatElapsed(
  task: { status?: string; started_at?: string; elapsed_sec?: number },
  now: number,
): string | undefined {
  if (task.status === "running" && task.started_at) {
    const started = Date.parse(task.started_at)
    if (!Number.isNaN(started)) {
      return `${Math.max(0, Math.floor((now - started) / 1000))}s`
    }
  }
  if (typeof task.elapsed_sec === "number") return `${Math.floor(task.elapsed_sec)}s`
  return undefined
}
