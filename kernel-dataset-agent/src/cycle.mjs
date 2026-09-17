// 单轮编排：逐个数据集跑采集器，数据集之间互相隔离（一个失败不影响其它），
// 并把水位/进度写回 .runtime/state/<dataset>.json。
import { collectorFor } from "./collectors/index.mjs"
import { loadDatasetState, saveDatasetState, freshState } from "./store.mjs"

function mergeState(previous, result, { elapsedMs }) {
  const next = {
    ...previous,
    cycles: (previous.cycles || 0) + 1,
    written: (previous.written || 0) + (result.written || 0),
    skipped: (previous.skipped || 0) + (result.skipped || 0),
    failed: (previous.failed || 0) + (result.failed || 0),
    lastRunAt: new Date().toISOString(),
    lastElapsedMs: elapsedMs,
    lastError: null,
  }
  if (result.watermark) next.watermark = result.watermark
  for (const [key, value] of Object.entries(result.statePatch || {})) next[key] = value
  return next
}

export function selectedDatasets(config, overrides = {}) {
  const requested = overrides.datasetIds && overrides.datasetIds.length > 0
    ? overrides.datasetIds
    : Object.keys(config.datasets)
  const unknown = requested.filter((id) => !config.datasets[id])
  if (unknown.length > 0) {
    throw new Error(`未知数据集: ${unknown.join(", ")}；可选: ${Object.keys(config.datasets).join(", ")}`)
  }
  return requested
}

export async function runCycle({ config, logger, overrides = {} }) {
  const startedAt = new Date().toISOString()
  const results = {}

  for (const datasetId of selectedDatasets(config, overrides)) {
    const dataset = config.datasets[datasetId]
    const scoped = logger.child(datasetId)
    if (dataset.enabled === false) {
      results[datasetId] = { dataset: datasetId, disabled: true }
      scoped.info("数据集已禁用，跳过")
      continue
    }

    const state = loadDatasetState(datasetId) || freshState(datasetId, { intervalMs: config.intervalMs })
    const startedMs = Date.now()
    try {
      const collector = collectorFor(dataset.kind)
      const result = await collector({ config, dataset, state, logger: scoped, overrides })
      const elapsedMs = Date.now() - startedMs
      saveDatasetState(datasetId, mergeState(state, result, { elapsedMs }))
      results[datasetId] = { dataset: datasetId, elapsedMs, ...result, statePatch: undefined }
      scoped.info(
        `本轮完成：新增 ${result.written || 0}，已存在 ${result.skipped || 0}，失败 ${result.failed || 0}，耗时 ${elapsedMs}ms`
        + (result.truncated ? "（已截断，下一轮继续）" : ""),
      )
    } catch (error) {
      // 限流或网络故障不推进水位，下一轮从同一水位续传
      saveDatasetState(datasetId, {
        ...state,
        cycles: (state.cycles || 0) + 1,
        lastRunAt: new Date().toISOString(),
        lastError: error.message,
      })
      results[datasetId] = { dataset: datasetId, error: error.message, rateLimited: Boolean(error.rateLimited) }
      scoped.error(`本轮失败：${error.message}`)
    }
  }

  const summary = Object.values(results).reduce(
    (accumulator, item) => {
      if (item.error) accumulator.failedDatasets += 1
      else if (!item.disabled) accumulator.okDatasets += 1
      accumulator.written += item.written || 0
      return accumulator
    },
    { okDatasets: 0, failedDatasets: 0, written: 0 },
  )

  return { startedAt, finishedAt: new Date().toISOString(), results, summary }
}