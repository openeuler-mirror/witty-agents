#!/usr/bin/env node
// 采集进程入口：kernel-dataset-setup run|start 都落到这里。
// 前台/后台只是 stdio 与 detached 的差别，采集逻辑完全一致。
import { parseRunArgs, RUN_USAGE } from "./args.mjs"
import { loadConfig, RUNTIME_DIR } from "./config.mjs"
import { createLogger } from "./log.mjs"
import { runDaemon } from "./daemon.mjs"
import { ensureDir } from "./store.mjs"

async function main() {
  const argv = process.argv.slice(2)
  if (argv.includes("--help") || argv.includes("-h")) {
    console.log(RUN_USAGE)
    return
  }
  const overrides = parseRunArgs(argv)
  const config = loadConfig({ overrides })
  ensureDir(RUNTIME_DIR)
  const logger = createLogger({ level: overrides.logLevel || process.env.KERNEL_DATASET_LOG_LEVEL || "info" })
  const outcome = await runDaemon({ config, logger, overrides })
  process.exitCode = outcome.cycles > 0 ? 0 : 1
}

main().catch((error) => {
  process.stderr.write(`kernel-dataset 启动失败: ${error.stack || error.message}\n`)
  process.exitCode = 1
})