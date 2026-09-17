// 采集器公共工具：水位解析、按路径取值与幂等写入。
import { atomicWriteFile, pathExists } from "../store.mjs"
import { datasetPath } from "../config.mjs"

export function getByPath(value, path) {
  if (!path) return undefined
  return path.split(".").reduce((current, key) => {
    if (current === null || current === undefined) return undefined
    return current[key]
  }, value)
}

function toIso(value) {
  if (value === null || value === undefined || value === "") return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString()
}

// 水位优先级：命令行 --since > 状态水位 > 数据集 initialSince > 服务启动时刻 - 一个周期。
// 首次运行不带 --since 时只保证“从现在起不丢增量”，历史缺口用 --since 显式回补。
export function resolveWatermark({ dataset, state, since, intervalMs, full = false }) {
  if (full) return { since: new Date(0).toISOString(), source: "full" }
  const fromCli = toIso(since)
  if (fromCli) return { since: fromCli, source: "cli" }
  const fromState = toIso(state.watermark)
  if (fromState) return { since: fromState, source: "state" }
  const fromConfig = toIso(dataset.initialSince)
  if (fromConfig) return { since: fromConfig, source: "config" }
  const fallback = toIso(state.initialWatermarkAt) || new Date(Date.now() - intervalMs).toISOString()
  return { since: fallback, source: "startup-window" }
}

export function itemWatermark(dataset, item) {
  const raw = dataset.watermarkField
    ? getByPath(item, dataset.watermarkField)
    : getByPath(item, dataset.watermarkPath)
  return toIso(raw)
}

export function itemId(dataset, item) {
  const value = getByPath(item, dataset.idField)
  return value === undefined || value === null ? null : String(value)
}

export function maxIso(values) {
  let best = null
  for (const value of values) {
    const iso = toIso(value)
    if (!iso) continue
    if (!best || iso > best) best = iso
  }
  return best
}

export function minIso(values) {
  let best = null
  for (const value of values) {
    const iso = toIso(value)
    if (!iso) continue
    if (!best || iso < best) best = iso
  }
  return best
}

// 单文件幂等落盘：已存在即跳过（同一 sha/id 不重复写）。
// 字节格式与本地既有文件一致：2 空格缩进、无尾换行（本地 bugzilla/commit 样本 100% 无尾换行）。
export function storeItem(config, dataset, id, item, { raw = false, serialized = null } = {}) {
  const target = datasetPath(config, dataset, id)
  if (pathExists(target)) return { written: false, path: target }
  const content = raw ? serialized : JSON.stringify(item, null, 2)
  atomicWriteFile(target, content)
  return { written: true, path: target }
}

export { toIso }