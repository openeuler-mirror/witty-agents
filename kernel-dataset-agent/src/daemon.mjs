// 常驻循环：默认每 intervalMs 跑一轮，SIGTERM/SIGINT 优雅退出。
// 每轮结束写 .runtime/heartbeat.json，供 kernel-dataset-setup status 判断健康度。
import { atomicWriteJson } from "./store.mjs"
import { runCycle, selectedDatasets } from "./cycle.mjs"
import { RUNTIME_DIR } from "./config.mjs"
import { join } from "node:path"

const HEARTBEAT_FILE = join(RUNTIME_DIR, "heartbeat.json")
const SLEEP_SLICE_MS = 1000

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

export function writeHeartbeat(payload) {
  try {
    atomicWriteJson(HEARTBEAT_FILE, { pid: process.pid, updatedAt: new Date().toISOString(), ...payload })
  } catch {
    // 心跳写失败不应影响采集主流程
  }
}

export async function runDaemon({ config, logger, overrides = {} }) {
  if (overrides.intervalMs) config = { ...config, intervalMs: overrides.intervalMs }
  const datasets = selectedDatasets(config, overrides)
  const once = Boolean(overrides.once)

  let stopping = false
  const stop = (signal) => {
    if (stopping) return
    stopping = true
    logger.info(`收到 ${signal}，等待本轮结束后退出`)
  }
  process.on("SIGTERM", () => stop("SIGTERM"))
  process.on("SIGINT", () => stop("SIGINT"))

  logger.info(
    `kernel-dataset 启动：数据集 [${datasets.join(", ")}]，周期 ${config.intervalMs}ms，数据根目录 ${config.dataRoot}`
  )
  writeHeartbeat({ state: "starting", datasets, intervalMs: config.intervalMs })

  let cycle = 0
  while (!stopping) {
    cycle += 1
    const startedMs = Date.now()
    let summary = null
    try {
      const outcome = await runCycle({ config, logger, overrides })
      summary = outcome.summary
      logger.info(
        `第 ${cycle} 轮结束：成功 ${summary.okDatasets} 个数据集，失败 ${summary.failedDatasets} 个，新增 ${summary.written} 条，耗时 ${Date.now() - startedMs}ms`
      )
      writeHeartbeat({ state: "running", cycle, summary, intervalMs: config.intervalMs })
    } catch (error) {
      logger.error(`第 ${cycle} 轮异常：${error.stack || error.message}`)
      writeHeartbeat({ state: "running", cycle, lastError: error.message, intervalMs: config.intervalMs })
    }
    if (once) break

    const deadline = Date.now() + config.intervalMs
    while (!stopping && Date.now() < deadline) {
      await delay(Math.min(SLEEP_SLICE_MS, Math.max(1, deadline - Date.now())))
    }
  }

  writeHeartbeat({ state: "stopped", cycle, intervalMs: config.intervalMs })
  logger.info("kernel-dataset 已退出")
  return { cycles: cycle }
}

export { HEARTBEAT_FILE }