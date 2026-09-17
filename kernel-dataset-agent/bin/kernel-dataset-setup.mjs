#!/usr/bin/env node
// kernel-dataset-setup —— 安装/校验/常驻服务管理。
//   install(默认) | check | run | start | status | stop
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

import { parseRunArgs, RUN_USAGE } from "../src/args.mjs"
import { loadConfig, RUNTIME_DIR, STATE_DIR } from "../src/config.mjs"
import { createLogger } from "../src/log.mjs"
import { runDaemon } from "../src/daemon.mjs"
import { serviceStatus, startService, stopService } from "../lib/service.mjs"
import { knownKinds } from "../src/collectors/index.mjs"

const BIN_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = resolve(BIN_DIR, "..")
const COMMANDS = ["install", "check", "run", "start", "status", "stop"]
const MARKER_FILE = join(RUNTIME_DIR, "setup-complete.json")
const MIN_NODE_MAJOR = 20

function usage() {
  console.log(`kernel-dataset-setup —— 内核数据集增量更新 agent

用法:
  kernel-dataset-setup [install]   准备本地运行目录（幂等，默认动作）
  kernel-dataset-setup check       校验 Node 版本、配置与数据根目录可写性
  kernel-dataset-setup run         前台运行（--once 只跑一轮）
  kernel-dataset-setup start       后台常驻（默认每 1 小时一轮）
  kernel-dataset-setup status      查看后台服务状态（JSON）
  kernel-dataset-setup stop        停止后台服务

${RUN_USAGE}`)
}

function parseCommand(argv) {
  const forward = []
  let command = "install"
  let commandSeen = false
  for (const arg of argv) {
    if (!commandSeen && COMMANDS.includes(arg)) {
      command = arg
      commandSeen = true
      continue
    }
    if (arg === "--help" || arg === "-h") {
      usage()
      process.exit(0)
    }
    forward.push(arg)
  }
  return { command, forward }
}

function packageMetadata() {
  const packageJson = JSON.parse(readFileSync(join(PROJECT_ROOT, "package.json"), "utf8"))
  return { packageName: packageJson.name, packageVersion: packageJson.version }
}

function checkEnvironment(overrides = {}) {
  const nodeMajor = Number(process.versions.node.split(".")[0])
  if (nodeMajor < MIN_NODE_MAJOR) {
    throw new Error(`需要 Node.js >= ${MIN_NODE_MAJOR}，当前 ${process.versions.node}`)
  }
  const config = loadConfig({ overrides })
  const unknownKinds = Object.entries(config.datasets)
    .filter(([, dataset]) => !knownKinds().includes(dataset.kind))
    .map(([id, dataset]) => `${id}(${dataset.kind})`)
  if (unknownKinds.length > 0) throw new Error(`存在未注册的采集器类型: ${unknownKinds.join(", ")}`)

  mkdirSync(config.dataRoot, { recursive: true })
  mkdirSync(STATE_DIR, { recursive: true })

  return {
    ...packageMetadata(),
    node: process.versions.node,
    dataRoot: config.dataRoot,
    dataRootSource: config.dataRootSource,
    configFiles: config.configFiles,
    intervalMs: config.intervalMs,
    stateDir: STATE_DIR,
    datasets: Object.entries(config.datasets)
      .filter(([, dataset]) => dataset.enabled !== false)
      .map(([id, dataset]) => ({ id, kind: dataset.kind, dir: dataset.dir })),
    tokens: {
      github: Boolean(config.tokens.github),
      gitcode: Boolean(config.tokens.gitcode),
    },
  }
}

function check(overrides = {}) {
  const report = checkEnvironment(overrides)
  console.log(JSON.stringify({ status: "ready", ...report }, null, 2))
  return report
}

// 本 agent 为纯 Node 实现，无 Python/二进制依赖：install 只准备运行目录并落一个幂等标记。
function install(overrides = {}) {
  const report = check(overrides)
  mkdirSync(RUNTIME_DIR, { recursive: true })
  writeFileSync(MARKER_FILE, `${JSON.stringify({
    package: report.packageName,
    version: report.packageVersion,
    node: report.node,
    dataRoot: report.dataRoot,
    completedAt: new Date().toISOString(),
  }, null, 2)}\n`)
  console.log(`[kernel-dataset-setup] 本地运行目录已就绪：${RUNTIME_DIR}`)
  return report
}

try {
  const { command, forward } = parseCommand(process.argv.slice(2))
  // install / check 同样接受 --root 等覆盖项，便于在没有配置文件时直接指定数据根目录
  const overrides = parseRunArgs(forward)
  if (command === "check") {
    check(overrides)
  } else if (command === "status") {
    console.log(JSON.stringify(serviceStatus(), null, 2))
  } else if (command === "stop") {
    console.log(JSON.stringify(await stopService(), null, 2))
  } else if (command === "start") {
    const config = loadConfig({ overrides })
    console.log(JSON.stringify(await startService({
      packageRoot: PROJECT_ROOT,
      forwardArgs: forward,
      intervalMs: config.intervalMs,
    }), null, 2))
  } else if (command === "run") {
    const config = loadConfig({ overrides })
    ensureRuntime()
    const logger = createLogger({ level: overrides.logLevel || "info" })
    await runDaemon({ config, logger, overrides })
  } else {
    install(overrides)
  }
} catch (error) {
  console.error(`[kernel-dataset-setup] ${error.message}`)
  process.exit(1)
}

function ensureRuntime() {
  if (!existsSync(RUNTIME_DIR)) mkdirSync(RUNTIME_DIR, { recursive: true })
}