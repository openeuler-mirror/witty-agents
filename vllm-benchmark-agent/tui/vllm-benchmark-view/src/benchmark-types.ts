// Schema for the files written by the vLLM benchmark runner.
//
// The runner (agent/main.py) is the single source of truth. This module only
// describes what the TUI reads; it never mutates benchmark state.

export type TaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "skipped"
  | "blocked"
  | "failed"
  | "cancelled"

/** <worktree>/.vllm-benchmark/current.json */
export interface UiPointer {
  data_root: string
  run_id: string
  progress: string
  tasks: string
  updated_at?: string
}

/** runs/<run_id>/progress.json */
export interface ProgressState {
  run_id?: string
  state?: string
  stage?: string
  substage?: string
  started_at?: string
  updated_at?: string
  level?: number
  completed_levels?: number
  report_output?: string
  message?: string
  issue?: { reason?: string } | null
  [key: string]: unknown
}

/** One entry of tasks.json `tasks[]` or `benchmark_rounds[]`. */
export interface BenchmarkTask {
  id: string
  label: string
  status: TaskStatus
  detail?: string
  reason?: string
  attempt?: number
  total_attempts?: number
  elapsed_sec?: number
  started_at?: string
  running?: number | null
  waiting?: number | null
  concurrency?: number
  completed_rounds?: number
  total_rounds?: number
  children?: BenchmarkTask[]
}

/** runs/<run_id>/tasks.json */
export interface TasksFile {
  tasks: BenchmarkTask[]
  benchmark_rounds: BenchmarkTask[]
  run_id?: string
  updated_at?: string
}

export interface BenchmarkSnapshot {
  pointer: UiPointer
  progress: ProgressState
  tasks: TasksFile
}

/**
 * The runner keeps `tasks[]` and `benchmark_rounds[]` flat for backwards
 * compatibility with `main.py watch`. The UI wants a tree, so nest the rounds
 * under the `benchmark` task without changing the on-disk format.
 */
export function buildTree(tasks: TasksFile | undefined): BenchmarkTask[] {
  if (!tasks) return []
  const rounds = tasks.benchmark_rounds ?? []
  return (tasks.tasks ?? []).map((task) =>
    task.id === "benchmark" ? { ...task, children: rounds } : task,
  )
}
