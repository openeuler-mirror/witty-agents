// 常驻服务生命周期：detached 采集进程 + pid/日志/心跳跟踪。
// 与 NL2SQL 的 nl2sql-web 保持同一套约定：pid.json + .log 均落在包的 .runtime/ 下。
import { execFileSync, spawn } from "node:child_process"
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { join } from "node:path"

import { loadConfig, RUNTIME_DIR } from "../src/config.mjs"

const START_TIMEOUT_MS = 15000
const HEARTBEAT_STALE_FACTOR = 3

export function runtimePaths() {
  return {
    runtimeDir: RUNTIME_DIR,
    pidFile: join(RUNTIME_DIR, "kernel-dataset.pid.json"),
    logFile: join(RUNTIME_DIR, "kernel-dataset.log"),
    heartbeatFile: join(RUNTIME_DIR, "heartbeat.json"),
  }
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

function processIsAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

function processLooksOwned(pid) {
  if (!processIsAlive(pid)) return false
  try {
    const command = execFileSync("ps", ["-p", String(pid), "-o", "command="], { encoding: "utf8" })
    return command.includes("kernel-dataset")
  } catch {
    return false
  }
}

function readJsonFile(path) {
  if (!existsSync(path)) return null
  try {
    return JSON.parse(readFileSync(path, "utf8"))
  } catch {
    return null
  }
}

function tailLog(logFile, maximumBytes = 4096) {
  if (!existsSync(logFile)) return "(服务日志尚未创建)"
  return readFileSync(logFile, "utf8").slice(-maximumBytes).trim() || "(服务日志为空)"
}

export function serviceStatus(options = {}) {
  const paths = runtimePaths()
  const record = readJsonFile(paths.pidFile)
  const alive = processLooksOwned(record?.pid)
  const heartbeat = readJsonFile(paths.heartbeatFile)
  const intervalMs = options.intervalMs || heartbeat?.intervalMs || loadConfig().intervalMs
  const heartbeatAge = heartbeat?.updatedAt ? Date.now() - new Date(heartbeat.updatedAt).getTime() : null
  const heartbeatFresh = heartbeatAge !== null && heartbeatAge <= intervalMs * HEARTBEAT_STALE_FACTOR

  let state = "stopped"
  if (alive && heartbeatFresh) state = "running"
  else if (alive && heartbeatAge === null) state = "starting"
  else if (alive) state = "stale"

  return {
    name: "kernel-dataset",
    state,
    pid: alive ? record.pid : null,
    tracked: alive,
    startedAt: alive ? record.startedAt || null : null,
    args: record?.args || [],
    intervalMs,
    heartbeatAgeMs: heartbeatAge,
    lastCycle: heartbeat?.cycle ?? null,
    lastSummary: heartbeat?.summary ?? null,
    lastError: heartbeat?.lastError ?? null,
    logFile: paths.logFile,
    pidFile: paths.pidFile,
  }
}

export async function startService(options = {}) {
  const initial = serviceStatus(options)
  if (initial.state === "running") return { ...initial, action: "already-running" }
  if (initial.state === "starting") {
    throw new Error(`kernel-dataset 进程 ${initial.pid} 正在启动，请先用 status 确认后再启动`)
  }
  if (initial.state === "stale") {
    throw new Error(`kernel-dataset 进程 ${initial.pid} 已失联（心跳过期），请先 stop 再启动`)
  }

  const paths = runtimePaths()
  mkdirSync(paths.runtimeDir, { recursive: true })
  rmSync(paths.heartbeatFile, { force: true })

  const entry = join(options.packageRoot, "src", "main.mjs")
  if (!existsSync(entry)) throw new Error(`采集入口不存在: ${entry}`)
  const args = [entry, ...(options.forwardArgs || [])]
  const logFd = openSync(paths.logFile, "a")
  let child
  try {
    child = spawn(process.execPath, args, {
      cwd: options.packageRoot,
      detached: true,
      stdio: ["ignore", logFd, logFd],
      env: process.env,
    })
    child.unref()
  } finally {
    closeSync(logFd)
  }
  writeFileSync(paths.pidFile, `${JSON.stringify({
    pid: child.pid,
    startedAt: new Date().toISOString(),
    command: process.execPath,
    args,
  }, null, 2)}\n`)

  const deadline = Date.now() + (options.startTimeoutMs || START_TIMEOUT_MS)
  while (Date.now() < deadline) {
    if (!processIsAlive(child.pid)) {
      rmSync(paths.pidFile, { force: true })
      throw new Error(`kernel-dataset 进程启动后立即退出:\n${tailLog(paths.logFile)}`)
    }
    if (existsSync(paths.heartbeatFile)) {
      return { ...serviceStatus(options), action: "started" }
    }
    await delay(200)
  }
  // 心跳没出现不代表启动失败（首轮采集可能很久），只要进程还在就算启动成功
  if (processIsAlive(child.pid)) return { ...serviceStatus(options), action: "started" }
  rmSync(paths.pidFile, { force: true })
  throw new Error(`kernel-dataset 未在 ${options.startTimeoutMs || START_TIMEOUT_MS}ms 内就绪:\n${tailLog(paths.logFile)}`)
}

export async function stopService(options = {}) {
  const paths = runtimePaths()
  const record = readJsonFile(paths.pidFile)
  if (!record || !processIsAlive(record.pid)) {
    rmSync(paths.pidFile, { force: true })
    return { ...serviceStatus(options), action: "already-stopped" }
  }
  process.kill(record.pid, "SIGTERM")
  const deadline = Date.now() + (options.stopTimeoutMs || 15000)
  while (Date.now() < deadline && processIsAlive(record.pid)) await delay(100)
  if (processIsAlive(record.pid)) process.kill(record.pid, "SIGKILL")
  rmSync(paths.pidFile, { force: true })
  return { ...serviceStatus(options), action: "stopped" }
}

export { tailLog }