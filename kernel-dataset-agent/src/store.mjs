// 落盘与状态：一切写入均为“临时文件 + fsync + rename”原子替换，
// 保证扫描进程（NL2SQL / 神农等下游）不会读到半截 JSON。
import {
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
  writeSync,
} from "node:fs"
import { dirname, join } from "node:path"

import { STATE_DIR, datasetStateFile } from "./config.mjs"

export function ensureDir(path) {
  mkdirSync(path, { recursive: true })
  return path
}

export function pathExists(path) {
  try {
    return statSync(path).isFile()
  } catch {
    return false
  }
}

export function atomicWriteFile(path, content) {
  ensureDir(dirname(path))
  const temporaryPath = `${path}.tmp-${process.pid}-${Date.now()}`
  let fileDescriptor = null
  try {
    fileDescriptor = openSync(temporaryPath, "wx", 0o644)
    writeSync(fileDescriptor, content)
    fsyncSync(fileDescriptor)
    closeSync(fileDescriptor)
    fileDescriptor = null
    renameSync(temporaryPath, path)
  } finally {
    if (fileDescriptor !== null) closeSync(fileDescriptor)
    rmSync(temporaryPath, { force: true })
  }
}

export function atomicWriteJson(path, value) {
  atomicWriteFile(path, `${JSON.stringify(value, null, 2)}\n`)
}

export function readJson(path, fallback = null) {
  if (!existsSync(path)) return fallback
  try {
    return JSON.parse(readFileSync(path, "utf8"))
  } catch {
    return fallback
  }
}

export function appendJsonLines(path, lines) {
  if (lines.length === 0) return
  ensureDir(dirname(path))
  const descriptor = openSync(path, "a")
  try {
    writeSync(descriptor, `${lines.map((line) => JSON.stringify(line)).join("\n")}\n`)
    fsyncSync(descriptor)
  } finally {
    closeSync(descriptor)
  }
}

export function readJsonLines(path) {
  if (!existsSync(path)) return []
  return readFileSync(path, "utf8")
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line) => {
      try {
        return JSON.parse(line)
      } catch {
        return null
      }
    })
    .filter(Boolean)
}

// 流式读取目录项，避免对上百万文件目录一次性 readdir 造成内存峰值。
export async function* streamDirNames(dir) {
  const { opendir } = await import("node:fs/promises")
  let handle
  try {
    handle = await opendir(dir)
  } catch (error) {
    if (error.code === "ENOENT") return
    throw error
  }
  for await (const entry of handle) {
    if (entry.isFile()) yield entry.name
  }
}

export function loadDatasetState(datasetId) {
  return readJson(datasetStateFile(datasetId), null)
}

export function saveDatasetState(datasetId, state) {
  ensureDir(STATE_DIR)
  atomicWriteJson(datasetStateFile(datasetId), state)
}

export function freshState(datasetId, { intervalMs }) {
  return {
    datasetId,
    watermark: null,
    initialWatermarkAt: new Date(Date.now() - intervalMs).toISOString(),
    cycles: 0,
    written: 0,
    skipped: 0,
    lastRunAt: null,
    lastError: null,
    bootstrappedFrom: null,
  }
}

export function stateFilePath(datasetId) {
  return join(STATE_DIR, `${datasetId}.json`)
}