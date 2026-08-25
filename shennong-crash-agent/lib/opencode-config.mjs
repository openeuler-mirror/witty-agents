import {
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { homedir } from "node:os"
import { dirname, join, resolve } from "node:path"
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

export function registerOpenCodePlugin(packageRoot) {
  if (process.env.SHENNONG_SKIP_CONFIG === "1") {
    return { skipped: true, reason: "SHENNONG_SKIP_CONFIG=1" }
  }

  const packageName = readPackageName(packageRoot)
  const configPath = getConfigPath()
  let raw = `{
  "$schema": "${SCHEMA_URL}"
}\n`
  let mode = 0o600

  if (existsSync(configPath)) {
    const file = lstatSync(configPath)
    if (file.isSymbolicLink() || !file.isFile()) {
      throw new Error(`refusing to modify non-regular OpenCode config: ${configPath}`)
    }
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
  plugins.push(packageName)

  if (
    currentPlugins.length === plugins.length
    && currentPlugins.every((plugin, index) => plugin === plugins[index])
  ) {
    return { changed: false, configPath, packageName }
  }

  const eol = raw.includes("\r\n") ? "\r\n" : "\n"
  const edits = modify(raw, ["plugin"], plugins, {
    formattingOptions: { insertSpaces: true, tabSize: 2, eol },
  })
  const updated = applyEdits(raw, edits)
  atomicWrite(configPath, updated, mode)
  return { changed: true, configPath, packageName }
}
