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
const AGENT_KEY = "openeuler-ops"
const OWNER = "openeuler-ops"
const SKILLS = [
  "agent-tools",
  "ssh-remote-skill",
  "ops-maintenance",
  "log-analyzer",
  "kubernetes",
  "docker-diag",
  "self-improvement",
  "skill-vetter",
  "summarize",
  "buddy-log-analyzer",
]

export function resolveConfigPath() {
  if (process.env.OPENEULER_OPS_OPENCODE_CONFIG) {
    return resolve(process.env.OPENEULER_OPS_OPENCODE_CONFIG)
  }
  const configHome = process.env.XDG_CONFIG_HOME
    ? resolve(process.env.XDG_CONFIG_HOME)
    : join(homedir(), ".config")
  return join(configHome, "opencode", "opencode.jsonc")
}

function defaultContent() {
  return `{
  "$schema": "${SCHEMA_URL}"
}
`
}

function readManagedFile(path, label = "OpenCode config") {
  if (!existsSync(path)) {
    return { existed: false, mode: 0o600, raw: defaultContent() }
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

function agentEntry(packageRoot) {
  return {
    description: "openEuler 运维助手 — 覆盖故障排查、巡检、CVE修复、安全加固、性能调优等16个场景",
    prompt: `{file:${join(packageRoot, "agent.md")}}`,
    skills: SKILLS,
  }
}

function sameJson(left, right) {
  return JSON.stringify(left) === JSON.stringify(right)
}

export function registerAgent(packageRoot, configPath = resolveConfigPath()) {
  const { configPath: path, raw, mode, existed } = {
    configPath,
    ...readManagedFile(configPath),
  }
  const config = parseConfig(raw, path)
  const desired = agentEntry(packageRoot)
  const current = config.agent?.[AGENT_KEY]

  if (sameJson(current, desired)) {
    return { changed: false, configPath: path, agentKey: AGENT_KEY }
  }

  const eol = raw.includes("\r\n") ? "\r\n" : "\n"
  const formattingOptions = { insertSpaces: true, tabSize: 2, eol }
  const updated = applyModify(raw, ["agent", AGENT_KEY], desired, formattingOptions)
  const { backupPath } = writeManagedFile({
    path,
    before: raw,
    after: updated,
    mode,
    existed,
  })
  return { changed: true, configPath: path, agentKey: AGENT_KEY, backupPath }
}

export function removeAgent(configPath = resolveConfigPath()) {
  const { configPath: path, raw, mode, existed } = {
    configPath,
    ...readManagedFile(configPath),
  }
  if (!existed) {
    return { changed: false, configPath: path, agentKey: AGENT_KEY }
  }
  const config = parseConfig(raw, path)
  if (!Object.hasOwn(config.agent || {}, AGENT_KEY)) {
    return { changed: false, configPath: path, agentKey: AGENT_KEY }
  }

  const eol = raw.includes("\r\n") ? "\r\n" : "\n"
  const formattingOptions = { insertSpaces: true, tabSize: 2, eol }
  const updated = applyModify(raw, ["agent", AGENT_KEY], undefined, formattingOptions)
  const { backupPath } = writeManagedFile({
    path,
    before: raw,
    after: updated,
    mode,
    existed,
  })
  return { changed: true, configPath: path, agentKey: AGENT_KEY, backupPath }
}

export function agentStatus(configPath = resolveConfigPath()) {
  const { configPath: path, raw, existed } = {
    configPath,
    ...readManagedFile(configPath),
  }
  if (!existed) {
    return { changed: false, configured: false, configPath: path, agentKey: AGENT_KEY }
  }
  const config = parseConfig(raw, path)
  return {
    changed: false,
    configured: Object.hasOwn(config.agent ?? {}, AGENT_KEY),
    configPath: path,
    agentKey: AGENT_KEY,
  }
}