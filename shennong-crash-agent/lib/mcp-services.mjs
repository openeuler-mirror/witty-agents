import { execFileSync, spawn } from "node:child_process"
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { get } from "node:http"
import { join } from "node:path"

const DEFAULT_HOST = "127.0.0.1"
const DEFAULT_PORT = 12144
const DEFAULT_START_TIMEOUT_MS = 60_000

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

function processIsAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) {
    return false
  }
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

function processLooksOwned(pid) {
  if (!processIsAlive(pid)) {
    return false
  }
  try {
    const command = execFileSync("ps", ["-p", String(pid), "-o", "command="], {
      encoding: "utf8",
    })
    return command.includes("run_server.sh") || command.includes("src/server.py")
  } catch {
    return false
  }
}

function readPidRecord(pidFile) {
  if (!existsSync(pidFile)) {
    return null
  }
  try {
    const record = JSON.parse(readFileSync(pidFile, "utf8"))
    return Number.isInteger(record.pid) && record.pid > 0 ? record : null
  } catch {
    return null
  }
}

function endpointIsSse(host, port, timeoutMs = 1500) {
  return new Promise((resolve) => {
    let settled = false
    const finish = (result) => {
      if (!settled) {
        settled = true
        resolve(result)
      }
    }
    const request = get({ host, port, path: "/sse" }, (response) => {
      const contentType = String(response.headers["content-type"] || "").toLowerCase()
      const healthy = response.statusCode === 200 && contentType.includes("text/event-stream")
      response.destroy()
      finish(healthy)
    })
    request.setTimeout(timeoutMs, () => {
      request.destroy()
      finish(false)
    })
    request.once("error", () => finish(false))
  })
}

function runtimePaths(projectRoot) {
  const runtimeDir = join(projectRoot, ".runtime")
  return {
    runtimeDir,
    pidFile: join(runtimeDir, "witty-log-detection.pid.json"),
    logFile: join(runtimeDir, "witty-log-detection.log"),
  }
}

function tailLog(logFile, maximumBytes = 4096) {
  if (!existsSync(logFile)) {
    return "(service log was not created)"
  }
  const content = readFileSync(logFile, "utf8")
  return content.slice(-maximumBytes).trim() || "(service log is empty)"
}

export function componentReadiness(projectRoot) {
  const matcherPython = join(projectRoot, ".venvs", "crash-feature-matcher", "bin", "python")
  const matcherLauncher = join(projectRoot, "skills", "crash-feature-matcher", "run_mcp.sh")
  const logPython = join(projectRoot, ".venvs", "witty-log-detection", "bin", "python")
  const logLauncher = join(projectRoot, "skills", "witty-log-detection", "run_server.sh")
  const reportPython = join(projectRoot, ".venvs", "crash-report-generator", "bin", "python")
  return {
    crashFeatureMatcher: existsSync(matcherPython) && existsSync(matcherLauncher),
    wittyLogDetection: existsSync(logPython) && existsSync(logLauncher),
    crashReportGenerator: existsSync(reportPython),
  }
}

export async function serviceStatus(projectRoot, options = {}) {
  const host = options.host || DEFAULT_HOST
  const port = options.port || DEFAULT_PORT
  const paths = runtimePaths(projectRoot)
  const record = readPidRecord(paths.pidFile)
  const trackedProcessAlive = processLooksOwned(record?.pid)
  const listening = await endpointIsSse(host, port, options.probeTimeoutMs)
  return {
    name: "witty-log-detection",
    transport: "sse",
    endpoint: `http://${host}:${port}/sse`,
    state: trackedProcessAlive && listening
      ? "running"
      : listening
        ? "external"
        : trackedProcessAlive
          ? "starting"
          : "stopped",
    pid: trackedProcessAlive ? record.pid : null,
    tracked: trackedProcessAlive,
    listening,
    logFile: paths.logFile,
    readiness: componentReadiness(projectRoot),
  }
}

export async function startServices(projectRoot, options = {}) {
  const readiness = componentReadiness(projectRoot)
  if (!readiness.crashFeatureMatcher) {
    throw new Error("crash-feature-matcher environment or stdio launcher is missing")
  }
  if (!readiness.wittyLogDetection) {
    throw new Error("witty-log-detection environment or SSE launcher is missing")
  }
  if (!readiness.crashReportGenerator) {
    throw new Error("crash-report-generator environment is missing")
  }

  const initial = await serviceStatus(projectRoot, options)
  if (initial.state === "running") {
    return { ...initial, action: "already-running", readiness }
  }
  if (initial.state === "external") {
    return { ...initial, action: "already-listening-untracked", readiness }
  }
  if (initial.state === "starting") {
    throw new Error(
      `witty-log-detection process ${initial.pid} is already starting; retry status before starting another process`,
    )
  }

  const host = options.host || DEFAULT_HOST
  const port = options.port || DEFAULT_PORT
  const startTimeoutMs = options.startTimeoutMs
    || Number(process.env.SHENNONG_MCP_START_TIMEOUT_MS)
    || DEFAULT_START_TIMEOUT_MS
  const paths = runtimePaths(projectRoot)
  mkdirSync(paths.runtimeDir, { recursive: true })
  rmSync(paths.pidFile, { force: true })

  const launcher = options.launcher
    || join(projectRoot, "skills", "witty-log-detection", "run_server.sh")
  const command = options.command || "bash"
  const args = options.args || [launcher]
  const logFd = openSync(paths.logFile, "a")
  let child
  try {
    child = spawn(command, args, {
      cwd: projectRoot,
      detached: true,
      stdio: ["ignore", logFd, logFd],
      env: { ...process.env, PYTHONUNBUFFERED: "1", ...(options.env || {}) },
    })
    child.unref()
  } finally {
    closeSync(logFd)
  }
  writeFileSync(paths.pidFile, `${JSON.stringify({
    pid: child.pid,
    startedAt: new Date().toISOString(),
    command,
    args,
  }, null, 2)}\n`)

  const deadline = Date.now() + startTimeoutMs
  while (Date.now() < deadline) {
    const status = await serviceStatus(projectRoot, { ...options, host, port })
    if (status.state === "running") {
      return { ...status, action: "started", readiness }
    }
    if (!processIsAlive(child.pid)) {
      rmSync(paths.pidFile, { force: true })
      throw new Error(`witty-log-detection exited before becoming ready:\n${tailLog(paths.logFile)}`)
    }
    await delay(250)
  }

  if (processIsAlive(child.pid)) {
    process.kill(child.pid, "SIGTERM")
  }
  rmSync(paths.pidFile, { force: true })
  throw new Error(
    `witty-log-detection did not listen on ${host}:${port} within ${startTimeoutMs}ms:\n${tailLog(paths.logFile)}`,
  )
}

export async function stopServices(projectRoot, options = {}) {
  const paths = runtimePaths(projectRoot)
  const record = readPidRecord(paths.pidFile)
  if (!record || !processIsAlive(record.pid)) {
    rmSync(paths.pidFile, { force: true })
    return { ...(await serviceStatus(projectRoot, options)), action: "already-stopped" }
  }

  process.kill(record.pid, "SIGTERM")
  const deadline = Date.now() + (options.stopTimeoutMs || 10_000)
  while (Date.now() < deadline && processIsAlive(record.pid)) {
    await delay(100)
  }
  if (processIsAlive(record.pid)) {
    process.kill(record.pid, "SIGKILL")
  }
  rmSync(paths.pidFile, { force: true })
  return { ...(await serviceStatus(projectRoot, options)), action: "stopped" }
}
