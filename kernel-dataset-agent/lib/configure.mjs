// OpenCode 注册：把 dist/index.js 作为插件写入 ~/.config/opencode/opencode.jsonc，
// 并把包内 skills/<name>/ 扁平链接到 ~/.config/opencode/skills/<name>/。
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
  symlinkSync,
  writeFileSync,
} from "node:fs"
import { homedir } from "node:os"
import { dirname, join, resolve } from "node:path"
import { pathToFileURL } from "node:url"
import { applyEdits, modify, parse, printParseErrorCode } from "jsonc-parser"

const AGENT_KEY = "kernel-dataset"
const OWNER = "kernel-dataset"
const PACKAGE_SEGMENTS = [
  "agent-kernel-dataset",
  "witty-agent-kernel-dataset",
  "-kernel-dataset-online",
  "-kernel-dataset-offline",
]
const SKILLS = ["kernel-dataset"]

export function resolveConfigPath() {
  if (process.env.KERNEL_DATASET_OPENCODE_CONFIG) {
    return resolve(process.env.KERNEL_DATASET_OPENCODE_CONFIG)
  }
  const configHome = process.env.XDG_CONFIG_HOME
    ? resolve(process.env.XDG_CONFIG_HOME)
    : join(homedir(), ".config")
  return join(configHome, "opencode", "opencode.jsonc")
}

export function resolveSkillsDir() {
  if (process.env.KERNEL_DATASET_OPENCODE_CONFIG) {
    return resolve(join(dirname(resolve(process.env.KERNEL_DATASET_OPENCODE_CONFIG)), "skills"))
  }
  const configHome = process.env.XDG_CONFIG_HOME
    ? resolve(process.env.XDG_CONFIG_HOME)
    : join(homedir(), ".config")
  return join(configHome, "opencode", "skills")
}

function readManagedFile(path, label = "OpenCode config") {
  if (!existsSync(path)) {
    return { existed: false, mode: 0o600, raw: "{\n  \"$schema\": \"https://opencode.ai/config.json\"\n}\n" }
  }
  const file = lstatSync(path)
  if (file.isSymbolicLink() || !file.isFile()) {
    throw new Error(`拒绝修改非普通文件 ${label}: ${path}`)
  }
  return { existed: true, mode: file.mode & 0o777, raw: readFileSync(path, "utf8") }
}

function createConfigBackup(path, raw, mode, owner = OWNER) {
  const timestamp = new Date().toISOString().replace(/[-:.]/g, "")
  const basePath = `${path}.${owner}-backup-${timestamp}`
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
      if (fileDescriptor !== null) closeSync(fileDescriptor)
      if (error.code !== "EEXIST") {
        rmSync(backupPath, { force: true })
        throw error
      }
    }
  }
  throw new Error(`无法为 ${path} 生成唯一备份文件`)
}

function atomicWrite(path, content, mode, owner = OWNER) {
  const directory = dirname(path)
  mkdirSync(directory, { recursive: true, mode: 0o700 })
  const temporaryPath = join(directory, `.${owner}-${process.pid}-${Date.now()}`)
  let fileDescriptor = null
  try {
    fileDescriptor = openSync(temporaryPath, "wx", mode)
    writeFileSync(fileDescriptor, content, "utf8")
    fsyncSync(fileDescriptor)
    closeSync(fileDescriptor)
    fileDescriptor = null
    renameSync(temporaryPath, path)
  } finally {
    if (fileDescriptor !== null) closeSync(fileDescriptor)
    rmSync(temporaryPath, { force: true })
  }
}

function writeManagedFile({ path, before, after, mode, existed, owner = OWNER }) {
  if (before === after) return { changed: false, backupPath: null }
  const backupPath = existed ? createConfigBackup(path, before, mode, owner) : null
  atomicWrite(path, after, mode, owner)
  return { changed: true, backupPath }
}

function parseConfig(raw, configPath) {
  const errors = []
  const config = parse(raw, errors, { allowTrailingComma: true, disallowComments: false })
  if (errors.length > 0) {
    const detail = errors.map(({ error, offset }) => `${printParseErrorCode(error)} at offset ${offset}`).join(", ")
    throw new Error(`OpenCode JSONC 解析失败 ${configPath}: ${detail}`)
  }
  if (!config || typeof config !== "object" || Array.isArray(config)) {
    throw new Error(`OpenCode 配置根节点必须是对象: ${configPath}`)
  }
  return config
}

function applyModify(raw, path, value, formattingOptions) {
  return applyEdits(raw, modify(raw, path, value, { formattingOptions }))
}

function getLocalPluginSpec(packageRoot) {
  const pluginPath = join(packageRoot, "dist", "index.js")
  if (!existsSync(pluginPath)) throw new Error(`OpenCode 插件入口不存在: ${pluginPath}`)
  const entry = lstatSync(pluginPath)
  if (entry.isSymbolicLink() || !entry.isFile()) {
    throw new Error(`拒绝注册非普通文件的插件入口: ${pluginPath}`)
  }
  return pathToFileURL(realpathSync(pluginPath)).href
}

function isPluginSpec(spec) {
  if (typeof spec !== "string") return false
  if (spec === AGENT_KEY) return true
  if (!spec.startsWith("file://")) return false
  try {
    const pluginPath = new URL(spec).pathname.replaceAll("\\", "/")
    if (!pluginPath.endsWith("/dist/index.js")) return false
    return PACKAGE_SEGMENTS.some((segment) => pluginPath.includes(segment))
  } catch {
    return false
  }
}

export function linkSkills(packageRoot, skillsDir = resolveSkillsDir()) {
  mkdirSync(skillsDir, { recursive: true, mode: 0o700 })
  const linked = []
  const conflicts = []
  for (const skill of SKILLS) {
    const source = join(packageRoot, "skills", skill)
    if (!existsSync(source)) continue
    const linkPath = join(skillsDir, skill)
    if (existsSync(linkPath)) {
      const existing = lstatSync(linkPath)
      const alreadyLinked = existing.isSymbolicLink() && realpathSync(linkPath) === realpathSync(source)
      if (alreadyLinked) linked.push({ skill, linkPath, alreadyLinked: true, changed: false })
      else conflicts.push({ skill, linkPath })
      continue
    }
    symlinkSync(source, linkPath)
    linked.push({ skill, linkPath, changed: true })
  }
  return { linked, conflicts }
}

export function unlinkSkills(skillsDir = resolveSkillsDir()) {
  const removed = []
  const conflicts = []
  for (const skill of SKILLS) {
    const linkPath = join(skillsDir, skill)
    if (!existsSync(linkPath)) continue
    if (!lstatSync(linkPath).isSymbolicLink()) {
      conflicts.push({ skill, linkPath })
      continue
    }
    rmSync(linkPath)
    removed.push({ skill, linkPath })
  }
  return { removed, conflicts }
}

export function registerAgent(packageRoot, configPath = resolveConfigPath()) {
  const { configPath: path, raw, mode, existed } = { configPath, ...readManagedFile(configPath) }
  const config = parseConfig(raw, path)
  const link = linkSkills(packageRoot)
  const desired = getLocalPluginSpec(packageRoot)
  const current = config.plugin || []
  const plugins = current.filter((plugin) => !isPluginSpec(plugin))
  plugins.push(desired)

  const changed = plugins.length !== current.length || plugins.some((plugin, index) => plugin !== current[index])
  if (!changed) {
    return { changed: false, configPath: path, agentKey: AGENT_KEY, pluginSpec: desired, link }
  }

  const eol = raw.includes("\r\n") ? "\r\n" : "\n"
  const formattingOptions = { insertSpaces: true, tabSize: 2, eol }
  const updated = applyModify(raw, ["plugin"], plugins, formattingOptions)
  const { backupPath } = writeManagedFile({ path, before: raw, after: updated, mode, existed })
  return { changed: true, configPath: path, agentKey: AGENT_KEY, pluginSpec: desired, link, backupPath }
}

export function removeAgent(configPath = resolveConfigPath()) {
  const { configPath: path, raw, mode, existed } = { configPath, ...readManagedFile(configPath) }
  if (!existed) {
    return { changed: false, configPath: path, agentKey: AGENT_KEY, removedPluginSpecs: [] }
  }
  const config = parseConfig(raw, path)
  const current = config.plugin || []
  const removedPluginSpecs = current.filter(isPluginSpec)
  const plugins = current.filter((plugin) => !isPluginSpec(plugin))
  if (removedPluginSpecs.length === 0) {
    return { changed: false, configPath: path, agentKey: AGENT_KEY, removedPluginSpecs }
  }

  const eol = raw.includes("\r\n") ? "\r\n" : "\n"
  const formattingOptions = { insertSpaces: true, tabSize: 2, eol }
  const updated = applyModify(raw, ["plugin"], plugins, formattingOptions)
  const link = unlinkSkills()
  const { backupPath } = writeManagedFile({ path, before: raw, after: updated, mode, existed })
  return { changed: true, configPath: path, agentKey: AGENT_KEY, removedPluginSpecs, link, backupPath }
}

export function agentStatus(configPath = resolveConfigPath()) {
  const { configPath: path, raw, existed } = { configPath, ...readManagedFile(configPath) }
  if (!existed) {
    return { changed: false, configured: false, configPath: path, agentKey: AGENT_KEY, pluginSpecs: [] }
  }
  const config = parseConfig(raw, path)
  const pluginSpecs = (config.plugin || []).filter(isPluginSpec)
  return { changed: false, configured: pluginSpecs.length > 0, configPath: path, agentKey: AGENT_KEY, pluginSpecs }
}

export { AGENT_KEY }