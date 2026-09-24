import {
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  readlinkSync,
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

const AGENT_KEY = "vllm-benchmark"
const OWNER = "vllm-benchmark"
const PACKAGE_NAME = /^(?:agent-|witty-agent-)?vllm-benchmark(?:-agent|-online|-offline(?:-(?:x86_64|aarch64))?)?$/
const SKILLS = ["vllm-benchmark"]

export function resolveConfigPath() {
  if (process.env.VLLM_BENCHMARK_OPENCODE_CONFIG) {
    return resolve(process.env.VLLM_BENCHMARK_OPENCODE_CONFIG)
  }
  const configHome = process.env.XDG_CONFIG_HOME
    ? resolve(process.env.XDG_CONFIG_HOME)
    : join(homedir(), ".config")
  return join(configHome, "opencode", "opencode.jsonc")
}

function readManagedFile(path, label = "OpenCode config") {
  if (!existsSync(path)) {
    return { existed: false, mode: 0o600, raw: "{\n  \"$schema\": \"https://opencode.ai/config.json\"\n}\n" }
  }
  const file = lstatSync(path)
  if (file.isSymbolicLink() || !file.isFile()) {
    throw new Error(`refusing to modify non-regular ${label}: ${path}`)
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
  throw new Error(`unable to create a unique backup for ${path}`)
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
    const detail = errors
      .map(({ error, offset }) => `${printParseErrorCode(error)} at offset ${offset}`)
      .join(", ")
    throw new Error(`invalid OpenCode JSONC in ${configPath}: ${detail}`)
  }
  if (!config || typeof config !== "object" || Array.isArray(config)) {
    throw new Error(`OpenCode config root must be an object: ${configPath}`)
  }
  return config
}

function applyModify(raw, path, value, formattingOptions) {
  return applyEdits(raw, modify(raw, path, value, { formattingOptions }))
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

function isPluginSpec(spec) {
  if (typeof spec !== "string") return false
  if (spec === AGENT_KEY) return true
  if (!spec.startsWith("file://")) return false
  try {
    const pluginPath = new URL(spec).pathname.replaceAll("\\", "/")
    if (!pluginPath.endsWith("/dist/index.js")) return false
    return pluginPath.split("/").some((segment) => PACKAGE_NAME.test(decodeURIComponent(segment)))
  } catch {
    return false
  }
}

export function resolveSkillsDir() {
  if (process.env.VLLM_BENCHMARK_OPENCODE_CONFIG) {
    return resolve(join(dirname(resolve(process.env.VLLM_BENCHMARK_OPENCODE_CONFIG)), "skills"))
  }
  const configHome = process.env.XDG_CONFIG_HOME
    ? resolve(process.env.XDG_CONFIG_HOME)
    : join(homedir(), ".config")
  return join(configHome, "opencode", "skills")
}

function linkMetadata(path) {
  try { return lstatSync(path) } catch (error) { if (error.code === "ENOENT") return null; throw error }
}
function ownedSkillLink(path, skill) {
  if (!linkMetadata(path)?.isSymbolicLink()) return false
  const target = resolve(dirname(path), readlinkSync(path)).replaceAll("\\", "/")
  return target.endsWith(`/skills/${skill}`) && target.split("/").some(segment => PACKAGE_NAME.test(segment))
}
export function linkSkills(packageRoot, skillsDir = resolveSkillsDir()) {
  const links = SKILLS.map(skill => ({skill, source: join(packageRoot, "skills", skill), linkPath: join(skillsDir, skill)}))
  for (const {skill, source, linkPath} of links) {
    if (!existsSync(join(source, "SKILL.md"))) throw new Error(`missing skill: ${source}`)
    if (linkMetadata(linkPath) && !ownedSkillLink(linkPath, skill)) throw new Error(`skill path already belongs to user: ${linkPath}`)
  }
  mkdirSync(skillsDir, {recursive: true, mode: 0o700})
  const linked = links.map(({skill, source, linkPath}) => {
    if (existsSync(linkPath) && realpathSync(linkPath) === realpathSync(source)) return {skill, linkPath, changed: false}
    if (linkMetadata(linkPath)) rmSync(linkPath)
    symlinkSync(source, linkPath)
    return {skill, linkPath, changed: true}
  })
  return {linked, conflicts: []}
}
export function unlinkSkills(skillsDir = resolveSkillsDir()) {
  const removed = [], conflicts = []
  for (const skill of SKILLS) {
    const linkPath = join(skillsDir, skill)
    if (!linkMetadata(linkPath)) continue
    if (!ownedSkillLink(linkPath, skill)) { conflicts.push({skill, linkPath}); continue }
    rmSync(linkPath)
    removed.push({skill, linkPath})
  }
  return {removed, conflicts}
}

export function registerAgent(packageRoot, configPath = resolveConfigPath()) {
  const { configPath: path, raw, mode, existed } = {
    configPath,
    ...readManagedFile(configPath),
  }
  const config = parseConfig(raw, path)
  const desired = getLocalPluginSpec(packageRoot)
  const current = config.plugin || []
  if (!Array.isArray(current)) throw new Error("OpenCode plugin must be an array")
  const plugins = current.filter((plugin) => !isPluginSpec(plugin))
  plugins.push(desired)
  const link = linkSkills(packageRoot)

  const changed = plugins.length !== current.length
    || plugins.some((plugin, index) => plugin !== current[index])
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
  const { configPath: path, raw, mode, existed } = {
    configPath,
    ...readManagedFile(configPath),
  }
  if (!existed) {
    return { changed: false, configPath: path, agentKey: AGENT_KEY, removedPluginSpecs: [] }
  }
  const config = parseConfig(raw, path)
  const current = config.plugin || []
  if (!Array.isArray(current)) throw new Error("OpenCode plugin must be an array")
  const link = unlinkSkills()
  const removedPluginSpecs = current.filter(isPluginSpec)
  const plugins = current.filter((plugin) => !isPluginSpec(plugin))
  if (removedPluginSpecs.length === 0) {
    return { changed: false, configPath: path, agentKey: AGENT_KEY, removedPluginSpecs }
  }

  const eol = raw.includes("\r\n") ? "\r\n" : "\n"
  const formattingOptions = { insertSpaces: true, tabSize: 2, eol }
  const updated = applyModify(raw, ["plugin"], plugins, formattingOptions)
  const { backupPath } = writeManagedFile({ path, before: raw, after: updated, mode, existed })
  return { changed: true, configPath: path, agentKey: AGENT_KEY, removedPluginSpecs, link, backupPath }
}

export function agentStatus(configPath = resolveConfigPath()) {
  const { configPath: path, raw, existed } = {
    configPath,
    ...readManagedFile(configPath),
  }
  if (!existed) {
    return { changed: false, configured: false, configPath: path, agentKey: AGENT_KEY, pluginSpecs: [] }
  }
  const config = parseConfig(raw, path)
  const pluginSpecs = (config.plugin || []).filter(isPluginSpec)
  return {
    changed: false,
    configured: pluginSpecs.length > 0,
    configPath: path,
    agentKey: AGENT_KEY,
    pluginSpecs,
  }
}