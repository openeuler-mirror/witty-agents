import { existsSync, lstatSync, readFileSync, realpathSync } from "node:fs"
import { homedir } from "node:os"
import { join, resolve } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import { applyEdits, modify, parse, printParseErrorCode } from "jsonc-parser"
import { readManagedFile, writeManagedFile } from "../backup.mjs"
import { syncAllSkills } from "../../sync-skills.mjs"

/* install/sync-skills 时强制同步到用户级目录的核心 skill（OpenCode 优先解析用户级副本）
   需与 dist/index.js 中 agent.shennong.skills 一致，否则部分 skill 永远停留在旧副本 */
export const CORE_SKILLS = Object.freeze([
  "crash-feature-matcher",
  "crash-report-generator",
  "gitcode",
  "vmcore-analysis",
  "witty-log-detection",
])

function syncCoreSkills(packageRoot) {
  try {
    return syncAllSkills(packageRoot, CORE_SKILLS, join(homedir(), ".config", "opencode", "skills"))
  } catch (error) {
    return { root: "", results: [], error: String(error && error.message || error) }
  }
}

const SCHEMA_URL = "https://opencode.ai/config.json"
const SHENNONG_PACKAGE_NAMES = new Set([
  "shennong-crash-agent",
  "shennong-crash-agent-online",
  "shennong-crash-agent-offline",
  "@openeuler/agent-shennong-crash",
  "@openeuler/agent-shennong-crash-online",
  "@openeuler/agent-shennong-crash-offline",
  "openeuler-agent-shennong-crash",
  "openeuler-agent-shennong-crash-online",
  "openeuler-agent-shennong-crash-offline",
  "witty-agent-shennong",
  "witty-agent-shennong-online",
  "witty-agent-shennong-offline",
])
const SHENNONG_MCP_NAMES = new Set([
  "crash-feature-matcher",
  "crash_feature_matcher",
  "witty-log-detection",
  "witty_log_detection",
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
          || pluginPath.includes("/openeuler-agent-shennong-crash/")
          || pluginPath.includes("/openeuler-agent-shennong-crash-online/")
          || pluginPath.includes("/openeuler-agent-shennong-crash-offline/")
          || pluginPath.includes("/witty-agent-shennong/")
          || pluginPath.includes("/witty-agent-shennong-online/")
          || pluginPath.includes("/witty-agent-shennong-offline/")
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

function getOpenCodeMcpConfig(packageRoot) {
  const launcher = join(packageRoot, "skills", "crash-feature-matcher", "run_mcp.sh")
  if (!existsSync(launcher)) {
    throw new Error(`crash-feature-matcher MCP launcher is missing: ${launcher}`)
  }
  const entry = lstatSync(launcher)
  if (entry.isSymbolicLink() || !entry.isFile()) {
    throw new Error(`refusing to register non-regular MCP launcher: ${launcher}`)
  }
  return {
    "crash-feature-matcher": {
      type: "local",
      command: ["bash", realpathSync(launcher)],
      enabled: true,
      timeout: 30000,
    },
    "witty-log-detection": {
      type: "remote",
      url: "http://127.0.0.1:12144/sse",
      enabled: true,
      timeout: 30000,
    },
  }
}

function sameJson(left, right) {
  return JSON.stringify(left) === JSON.stringify(right)
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
  if (
    config.mcp !== undefined
    && (!config.mcp || typeof config.mcp !== "object" || Array.isArray(config.mcp))
  ) {
    throw new Error(`OpenCode config field "mcp" must be an object: ${configPath}`)
  }
  return config
}

function applyModify(raw, path, value, formattingOptions) {
  return applyEdits(raw, modify(raw, path, value, { formattingOptions }))
}

function readOpenCodeConfig() {
  const configPath = getConfigPath()
  return {
    configPath,
    ...readManagedFile(configPath, {
      defaultContent: `{
  "$schema": "${SCHEMA_URL}"
}\n`,
      defaultMode: 0o600,
      label: "OpenCode config",
    }),
  }
}

export function registerOpenCodePlugin(packageRoot) {
  if (process.env.SHENNONG_SKIP_CONFIG === "1") {
    return { skipped: true, reason: "SHENNONG_SKIP_CONFIG=1" }
  }

  const packageName = readPackageName(packageRoot)
  const pluginSpec = getLocalPluginSpec(packageRoot)
  const desiredMcp = getOpenCodeMcpConfig(packageRoot)
  const { configPath, raw, mode, existed } = readOpenCodeConfig()
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

  const pluginChanged = !(
    currentPlugins.length === plugins.length
    && currentPlugins.every((plugin, index) => plugin === plugins[index])
  )
  const currentMcp = config.mcp || {}
  const removedMcpNames = [...SHENNONG_MCP_NAMES]
    .filter((name) => !(name in desiredMcp) && Object.hasOwn(currentMcp, name))
  const changedMcpNames = Object.entries(desiredMcp)
    .filter(([name, value]) => !sameJson(currentMcp[name], value))
    .map(([name]) => name)

  if (!pluginChanged && removedMcpNames.length === 0 && changedMcpNames.length === 0) {
    return {
      changed: false,
      configPath,
      packageName,
      pluginSpec,
      mcpNames: Object.keys(desiredMcp),
    }
  }

  const eol = raw.includes("\r\n") ? "\r\n" : "\n"
  const formattingOptions = { insertSpaces: true, tabSize: 2, eol }
  let updated = raw
  if (pluginChanged) {
    updated = applyModify(updated, ["plugin"], plugins, formattingOptions)
  }
  for (const name of removedMcpNames) {
    updated = applyModify(updated, ["mcp", name], undefined, formattingOptions)
  }
  for (const name of changedMcpNames) {
    updated = applyModify(updated, ["mcp", name], desiredMcp[name], formattingOptions)
  }
  const { backupPath } = writeManagedFile({
    path: configPath,
    before: raw,
    after: updated,
    mode,
    existed,
    owner: "shennong",
  })
  return {
    changed: true,
    configPath,
    packageName,
    pluginSpec,
    mcpNames: Object.keys(desiredMcp),
    backupPath,
  }
}

export function removeOpenCodePlugin() {
  if (process.env.SHENNONG_SKIP_CONFIG === "1") {
    return { skipped: true, reason: "SHENNONG_SKIP_CONFIG=1" }
  }

  const { configPath, raw, mode, existed } = readOpenCodeConfig()
  if (!existed) {
    return { changed: false, configPath, removedPlugins: [], removedMcpNames: [] }
  }

  const config = parseConfig(raw, configPath)
  const currentPlugins = config.plugin || []
  const removedPlugins = []
  const plugins = []
  for (const plugin of currentPlugins) {
    if (typeof plugin !== "string") {
      throw new Error(`OpenCode config field "plugin" must contain only strings: ${configPath}`)
    }
    if (isShennongPackageSpec(plugin)) {
      removedPlugins.push(plugin)
    } else {
      plugins.push(plugin)
    }
  }
  const currentMcp = config.mcp || {}
  const removedMcpNames = [...SHENNONG_MCP_NAMES]
    .filter((name) => Object.hasOwn(currentMcp, name))

  if (removedPlugins.length === 0 && removedMcpNames.length === 0) {
    return { changed: false, configPath, removedPlugins, removedMcpNames }
  }

  const eol = raw.includes("\r\n") ? "\r\n" : "\n"
  const formattingOptions = { insertSpaces: true, tabSize: 2, eol }
  let updated = raw
  if (removedPlugins.length > 0) {
    updated = applyModify(updated, ["plugin"], plugins, formattingOptions)
  }
  for (const name of removedMcpNames) {
    updated = applyModify(updated, ["mcp", name], undefined, formattingOptions)
  }
  const { backupPath } = writeManagedFile({
    path: configPath,
    before: raw,
    after: updated,
    mode,
    existed,
    owner: "shennong",
  })
  return { changed: true, configPath, removedPlugins, removedMcpNames, backupPath }
}

export function getOpenCodeStatus() {
  const { configPath, raw, existed } = readOpenCodeConfig()
  if (!existed) {
    return {
      changed: false,
      configured: false,
      configPath,
      pluginSpecs: [],
      mcpNames: [],
    }
  }
  const config = parseConfig(raw, configPath)
  const pluginSpecs = (config.plugin || []).filter((plugin) => (
    typeof plugin === "string" && isShennongPackageSpec(plugin)
  ))
  const mcpNames = [...SHENNONG_MCP_NAMES]
    .filter((name) => Object.hasOwn(config.mcp || {}, name))
  return {
    changed: false,
    configured: pluginSpecs.length > 0 || mcpNames.length > 0,
    configPath,
    pluginSpecs,
    mcpNames,
  }
}

export const opencodeAdapter = Object.freeze({
  id: "opencode",
  label: "OpenCode",
  capabilities: Object.freeze({ install: true, remove: true, status: true, "sync-skills": true }),
  install({ packageRoot }) {
    const result = registerOpenCodePlugin(packageRoot)
    const skillSync = syncCoreSkills(packageRoot)
    return { ...result, skillSync }
  },
  remove() {
    return removeOpenCodePlugin()
  },
  status() {
    return getOpenCodeStatus()
  },
  "sync-skills"({ packageRoot }) {
    return { skillSync: syncCoreSkills(packageRoot) }
  },
})
