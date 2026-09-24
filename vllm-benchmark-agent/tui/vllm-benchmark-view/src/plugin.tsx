/** @jsxImportSource @opentui/solid */
import type { TuiPlugin, TuiPluginApi, TuiPluginModule } from "@opencode-ai/plugin/tui"
import { homedir } from "node:os"
import { join } from "node:path"
import { For, Show, createSignal } from "solid-js"
import { createBenchmarkTracker } from "./benchmark-tracker"
import { buildTree, type BenchmarkSnapshot, type BenchmarkTask } from "./benchmark-types"
import { formatElapsed, mascot, statusMeta, truncate } from "./benchmark-ui"

const id = "vllm-benchmark-view"

function pointerCandidates(api: TuiPluginApi): string[] {
  const home = process.env.HOME || homedir()
  const raw = [
    join(home, ".vllm-benchmark", "current.json"),
    join(api.state.path.worktree, ".vllm-benchmark", "current.json"),
    join(api.state.path.directory, ".vllm-benchmark", "current.json"),
    join(process.cwd(), ".vllm-benchmark", "current.json"),
  ]
  return Array.from(new Set(raw.filter(Boolean)))
}

function View(props: {
  api: TuiPluginApi
  snapshot: () => BenchmarkSnapshot | null
  now: () => number
}) {
  const theme = () => props.api.theme.current

  const colorFor = (status?: string) => {
    const t = theme()
    switch (statusMeta(status).tone) {
      case "success":
        return t.success
      case "warning":
        return t.warning
      case "error":
        return t.error
      case "info":
        return t.info
      default:
        return t.textMuted
    }
  }

  const rows = () => buildTree(props.snapshot()?.tasks)

  const suffix = (task: BenchmarkTask) => {
    const parts: string[] = []
    const elapsed = formatElapsed(task, props.now())
    if (elapsed) parts.push(elapsed)
    if (task.status === "running" && (task.running != null || task.waiting != null)) {
      parts.push(`running=${task.running ?? "?"} waiting=${task.waiting ?? "?"}`)
    }
    return parts.length ? `   ${parts.join("   ")}` : ""
  }

  return (
    <box flexDirection="column">
      <text fg={theme().text}>
        <b>{mascot(props.snapshot()?.progress?.state)} vLLM Benchmark</b>
        {props.snapshot()?.progress?.state ? `  ${props.snapshot()?.progress?.state}` : ""}
      </text>
      <Show
        when={props.snapshot()}
        fallback={<text fg={theme().textMuted}>等待 benchmark…</text>}
      >
        <For each={rows()}>
          {(task) => (
            <box flexDirection="column">
              <box flexDirection="row">
                <box width={2}>
                  <text fg={colorFor(task.status)}>{statusMeta(task.status).icon} </text>
                </box>
                <box flexGrow={1}>
                  <text fg={colorFor(task.status)} wrapMode="word">
                    {truncate(task.label)}
                  </text>
                </box>
              </box>
              <Show when={task.children && task.children.length > 0}>
                <For each={task.children}>
                  {(child) => (
                    <box flexDirection="row" paddingLeft={2}>
                      <box width={2}>
                        <text fg={colorFor(child.status)}>{statusMeta(child.status).icon} </text>
                      </box>
                      <box flexGrow={1}>
                        <text fg={colorFor(child.status)} wrapMode="word">
                          {truncate(child.label, 60)}
                          {suffix(child)}
                        </text>
                      </box>
                    </box>
                  )}
                </For>
              </Show>
            </box>
          )}
        </For>
      </Show>
    </box>
  )
}

const tui: TuiPlugin = async (api) => {
  const [snapshot, setSnapshot] = createSignal<BenchmarkSnapshot | null>(null)
  const [now, setNow] = createSignal(Date.now())

  const tracker = createBenchmarkTracker(pointerCandidates(api), setSnapshot)
  const timer = setInterval(() => setNow(Date.now()), 1000)

  api.lifecycle.onDispose(() => {
    tracker.dispose()
    clearInterval(timer)
  })

  api.slots.register({
    order: 360, // after built-in LSP (300), before Todo (400)
    slots: {
      sidebar_content(_ctx, _props) {
        return <View api={api} snapshot={snapshot} now={now} />
      },
    },
  })
}

const plugin: TuiPluginModule = {
  id,
  tui,
}

export default plugin
