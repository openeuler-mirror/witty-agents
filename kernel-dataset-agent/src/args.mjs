// 运行参数解析：所有覆盖项都只作用于本次进程，不写回配置文件。
import { DEFAULT_DATA_ROOT } from "./config.mjs"

export const RUN_USAGE = `用法:
  kernel-dataset-setup run [选项]        前台运行一轮或常驻
  kernel-dataset-setup start [选项]      后台常驻（detached）
  kernel-dataset-setup status            查看后台服务状态（JSON）
  kernel-dataset-setup stop              停止后台服务
  kernel-dataset-setup install           准备本地依赖（本 agent 无外部依赖，仅做校验）
  kernel-dataset-setup check             校验本地依赖与环境

选项:
  --once                  只跑一轮后退出（默认常驻）
  --dataset <a,b>         只跑指定数据集（默认全部）
  --limit <n>             每个数据集本轮最多写入 n 条（email 为每个 part 最多 n 页）
  --max-parts <n>         每个数据集本轮最多处理的 part 数（仅 email）
  --max-pages <n>         分页接口本轮最多翻 n 页
  --since <ISO>           指定起始水位/起始时间（首次回补历史缺口时使用）
  --full                  全量复核（提交所有历史窗口）
  --interval <ms>         常驻周期，默认 3600000（1 小时）
  --root <path>           数据根目录，覆盖配置文件/环境变量（内置默认 ${DEFAULT_DATA_ROOT}）
  --log-level <level>     debug | info | warn | error，默认 info
`

const LEVELS = ["debug", "info", "warn", "error"]

function requireValue(argv, index, name) {
  const value = argv[index]
  if (value === undefined) throw new Error(`${name} 需要一个取值`)
  return value
}

function positiveInteger(value, name) {
  const parsed = Number(value)
  if (!Number.isInteger(parsed) || parsed <= 0) throw new Error(`${name} 需为正整数: ${value}`)
  return parsed
}

export function parseRunArgs(argv) {
  const overrides = { datasetIds: [], full: false, once: false, limit: 0, maxParts: 0, maxPages: 0 }
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === "--once") overrides.once = true
    else if (arg === "--full") overrides.full = true
    else if (arg === "--limit") overrides.limit = positiveInteger(requireValue(argv, ++index, "--limit"), "--limit")
    else if (arg.startsWith("--limit=")) overrides.limit = positiveInteger(arg.slice(8), "--limit")
    else if (arg === "--max-parts") overrides.maxParts = positiveInteger(requireValue(argv, ++index, "--max-parts"), "--max-parts")
    else if (arg.startsWith("--max-parts=")) overrides.maxParts = positiveInteger(arg.slice(12), "--max-parts")
    else if (arg === "--max-pages") overrides.maxPages = positiveInteger(requireValue(argv, ++index, "--max-pages"), "--max-pages")
    else if (arg.startsWith("--max-pages=")) overrides.maxPages = positiveInteger(arg.slice(12), "--max-pages")
    else if (arg === "--dataset") overrides.datasetIds = requireValue(argv, ++index, "--dataset").split(",").filter(Boolean)
    else if (arg.startsWith("--dataset=")) overrides.datasetIds = arg.slice(10).split(",").filter(Boolean)
    else if (arg === "--since") overrides.since = requireValue(argv, ++index, "--since")
    else if (arg.startsWith("--since=")) overrides.since = arg.slice(8)
    else if (arg === "--interval") overrides.intervalMs = positiveInteger(requireValue(argv, ++index, "--interval"), "--interval")
    else if (arg.startsWith("--interval=")) overrides.intervalMs = positiveInteger(arg.slice(11), "--interval")
    else if (arg === "--root") overrides.dataRoot = requireValue(argv, ++index, "--root")
    else if (arg.startsWith("--root=")) overrides.dataRoot = arg.slice(7)
    else if (arg === "--log-level") overrides.logLevel = requireValue(argv, ++index, "--log-level")
    else if (arg.startsWith("--log-level=")) overrides.logLevel = arg.slice(12)
    else throw new Error(`未知参数: ${arg}`)
  }
  if (overrides.since && Number.isNaN(new Date(overrides.since).getTime())) {
    throw new Error(`--since 不是合法时间: ${overrides.since}`)
  }
  if (overrides.logLevel && !LEVELS.includes(overrides.logLevel)) {
    throw new Error(`--log-level 只能是 ${LEVELS.join(" | ")}`)
  }
  return overrides
}