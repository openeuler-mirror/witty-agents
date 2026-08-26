import {
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { homedir } from "node:os"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import { applyEdits, modify, parse, printParseErrorCode } from "jsonc-parser"

const SCHEMA_URL = "https://opencode.ai/config.json"
const SHENNONG_PACKAGE_NAMES = new Set([
  "shennong-crash-agent",
  "shennong-crash-agent-online",
  "shennong-crash-agent-offline",
  "@openeuler/agent-shennong-crash",
  "@openeuler/agent-shennong-crash-online",
  "@openeuler/agent-shennong-crash-offline",
])

function isShennongPackageSpec(spec) {
  for (const packageName of SHENNONG_PACKAGE_NAMES) {
    if (spec === packageName || spec.startsWith(`${packageName}@`)) {
      return true
    }
  }
  if (spec.startsWith("file://")) {
    try {
      const pluginPath = fileURLToPath(spec).replaceAll("\\", "/")
      return (
        pluginPath.endsWith("/dist/index.js")
        && (
          pluginPath.includes("/shennong-crash-agent/")
          || pluginPath.includes("/agent-shennong-crash/")
          || pluginPath.includes("/agent-shennong-crash-online/")
          || pluginPath.includes("/agent-shennong-crash-offline/")
        )
      )
    } catch {
      return false
    }
  }
  return false
}

function getConfigPath() {
  if (process.env.SHENNONG_OPENCODE_CONFIG) {
    return resolve(process.env.SHENNONG_OPENCODE_CONFIG)
  }
  const configHome = process.env.XDG_CONFIG_HOME
    ? resolve(process.env.XDG_CONFIG_HOME)
    : join(homedir(), ".config")
  return join(configHome, "opencode", "opencode.jsonc")
}

function readPackageName(packageRoot) {
  const packageJson = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8"))
  if (typeof packageJson.name !== "string" || packageJson.name.length === 0) {
    throw new Error("package.json does not contain a valid package name")
  }
  return packageJson.name
}

function getLocalPluginSpec(packageRoot) {
  const pluginPath = join(packageRoot, "dist", "index.js")
  if (!existsSync(pluginPath)) {
    throw new Error(`OpenCode plugin entry is missing: ${pluginPath}`)
  }
  const entry = lstatSync(pluginPath)
  if (entry.isSymbolicLink() || !entry.isFile()) {
    throw new Error(`refusing to register non-regular OpenCode plugin entry: ${pluginPath}`)
  }
  return pathToFileURL(realpathSync(pluginPath)).href
}

function parseConfig(raw, configPath) {
  const errors = []
  const config = parse(raw, errors, { allowTrailingComma: true, disallowComments: false })
  if (errors.length > 0) {
    const detail = errors
      .map(({ error, offset }) => `${printParseErrorCode(error)} at offset ${offset}`)
      .join(", ")
    throw new Error(`invalid OpenCode JSONC in ${configPath}: ${detail}`)
  }
  if (!config || typeof config !== "object" || Array.isArray(config)) {
    throw new Error(`OpenCode config root must be an object: ${configPath}`)
  }
  if (config.plugin !== undefined && !Array.isArray(config.plugin)) {
    throw new Error(`OpenCode config field "plugin" must be an array: ${configPath}`)
  }
  return config
}

function atomicWrite(configPath, content, mode) {
  const directory = dirname(configPath)
  mkdirSync(directory, { recursive: true, mode: 0o700 })
  const temporaryPath = join(directory, `.opencode.jsonc.shennong-${process.pid}-${Date.now()}`)
  let fileDescriptor = null
  try {
    fileDescriptor = openSync(temporaryPath, "wx", mode)
    writeFileSync(fileDescriptor, content, "utf8")
    fsyncSync(fileDescriptor)
    closeSync(fileDescriptor)
    fileDescriptor = null
    renameSync(temporaryPath, configPath)
  } finally {
    if (fileDescriptor !== null) {
      closeSync(fileDescriptor)
    }
    rmSync(temporaryPath, { force: true })
  }
}

function createConfigBackup(configPath, raw, mode) {
  const timestamp = new Date().toISOString().replace(/[-:.]/g, "")
  const basePath = `${configPath}.shennong-backup-${timestamp}`
  for (let attempt = 0; attempt < 1000; attempt += 1) {
    const backupPath = attempt === 0 ? basePath : `${basePath}-${attempt}`
    let fileDescriptor = null
    try {
      fileDescriptor = openSync(backupPath, "wx", mode)
      writeFileSync(fileDescriptor, raw, "utf8")
      fsyncSync(fileDescriptor)
      closeSync(fileDescriptor)
      return backupPath
    } catch (error) {
      if (fileDescriptor !== null) {
        closeSync(fileDescriptor)
      }
      if (error.code !== "EEXIST") {
        rmSync(backupPath, { force: true })
        throw error
      }
    }
  }
  throw new Error(`unable to create a unique OpenCode config backup for ${configPath}`)
}

export function registerOpenCodePlugin(packageRoot) {
  if (process.env.SHENNONG_SKIP_CONFIG === "1") {
    return { skipped: true, reason: "SHENNONG_SKIP_CONFIG=1" }
  }

  const packageName = readPackageName(packageRoot)
  const pluginSpec = getLocalPluginSpec(packageRoot)
  const configPath = getConfigPath()
  let raw = `{
  "$schema": "${SCHEMA_URL}"
}\n`
  let mode = 0o600
  let configExisted = false

  if (existsSync(configPath)) {
    const file = lstatSync(configPath)
    if (file.isSymbolicLink() || !file.isFile()) {
      throw new Error(`refusing to modify non-regular OpenCode config: ${configPath}`)
    }
    configExisted = true
    mode = file.mode & 0o777
    raw = readFileSync(configPath, "utf8")
  }

  const config = parseConfig(raw, configPath)
  const currentPlugins = config.plugin || []
  const plugins = []
  for (const plugin of currentPlugins) {
    if (typeof plugin !== "string") {
      throw new Error(`OpenCode config field "plugin" must contain only strings: ${configPath}`)
    }
    if (!isShennongPackageSpec(plugin)) {
      plugins.push(plugin)
    }
  }
  plugins.push(pluginSpec)

  if (
    currentPlugins.length === plugins.length
    && currentPlugins.every((plugin, index) => plugin === plugins[index])
  ) {
    return { changed: false, configPath, packageName, pluginSpec }
  }

  const eol = raw.includes("\r\n") ? "\r\n" : "\n"
  const edits = modify(raw, ["plugin"], plugins, {
    formattingOptions: { insertSpaces: true, tabSize: 2, eol },
  })
  const updated = applyEdits(raw, edits)
  const backupPath = configExisted ? createConfigBackup(configPath, raw, mode) : null
  atomicWrite(configPath, updated, mode)
  return { changed: true, configPath, packageName, pluginSpec, backupPath }
}

export function removeOpenCodePlugin() {
  if (process.env.SHENNONG_SKIP_CONFIG === "1") {
    return { skipped: true, reason: "SHENNONG_SKIP_CONFIG=1" }
  }

  const configPath = getConfigPath()
  if (!existsSync(configPath)) {
    return { changed: false, configPath, removed: [] }
  }

  const file = lstatSync(configPath)
  if (file.isSymbolicLink() || !file.isFile()) {
    throw new Error(`refusing to modify non-regular OpenCode config: ${configPath}`)
  }
  const mode = file.mode & 0o777
  const raw = readFileSync(configPath, "utf8")
  const config = parseConfig(raw, configPath)
  const currentPlugins = config.plugin || []
  const removed = []
  const plugins = []
  for (const plugin of currentPlugins) {
    if (typeof plugin !== "string") {
      throw new Error(`OpenCode config field "plugin" must contain only strings: ${configPath}`)
    }
    if (isShennongPackageSpec(plugin)) {
      removed.push(plugin)
    } else {
      plugins.push(plugin)
    }
  }

  if (removed.length === 0) {
    return { changed: false, configPath, removed }
  }

  const eol = raw.includes("\r\n") ? "\r\n" : "\n"
  const edits = modify(raw, ["plugin"], plugins, {
    formattingOptions: { insertSpaces: true, tabSize: 2, eol },
  })
  const updated = applyEdits(raw, edits)
  const backupPath = createConfigBackup(configPath, raw, mode)
  atomicWrite(configPath, updated, mode)
  return { changed: true, configPath, removed, backupPath }
}
