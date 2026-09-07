#!/usr/bin/env node

import { execFileSync } from "node:child_process"
import { mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { arch } from "node:os"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(SCRIPT_DIR, "../..")
const REGISTRY_PATH = join(REPO_ROOT, "ci", "agents.json")
const DEFAULT_OUTPUT = join(REPO_ROOT, "ci-artifacts", "build-plan.json")

function parseArgs(argv) {
  const options = {
    agent: process.env.AGENT || "auto",
    variant: process.env.VARIANT || "default",
    packageStyle: process.env.PACKAGE_STYLE || "organization",
    targetArchitecture: process.env.TARGET_ARCH || "native",
    publish: process.env.PUBLISH === "true",
    output: DEFAULT_OUTPUT,
  }
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]
    const [rawKey, inlineValue] = argument.split("=", 2)
    const key = rawKey.replace(/^--/, "")
    const value = inlineValue ?? argv[++index]
    if (key === "agent") options.agent = value
    else if (key === "variant") options.variant = value
    else if (key === "package-style") options.packageStyle = value
    else if (key === "target-arch") options.targetArchitecture = value
    else if (key === "publish") options.publish = value === "true"
    else if (key === "output") options.output = resolve(REPO_ROOT, value)
    else throw new Error(`unknown argument: ${argument}`)
  }
  if (!["organization", "plain"].includes(options.packageStyle)) {
    throw new Error("PACKAGE_STYLE must be organization or plain")
  }
  if (!["native", "x86_64", "aarch64"].includes(options.targetArchitecture)) {
    throw new Error("TARGET_ARCH must be native, x86_64, or aarch64")
  }
  return options
}

function git(args, allowFailure = false) {
  try {
    return execFileSync("git", args, { cwd: REPO_ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim()
  } catch (error) {
    if (allowFailure) return ""
    throw error
  }
}

function gitCommitExists(candidate) {
  try {
    execFileSync("git", ["cat-file", "-e", `${candidate}^{commit}`], {
      cwd: REPO_ROOT,
      stdio: "ignore",
    })
    return true
  } catch {
    return false
  }
}

function loadRegistry() {
  const registry = JSON.parse(readFileSync(REGISTRY_PATH, "utf8"))
  if (registry.schemaVersion !== 1 || !Array.isArray(registry.agents)) {
    throw new Error("ci/agents.json has an unsupported schema")
  }
  for (const entry of registry.agents) {
    if (!entry.id || !Array.isArray(entry.changedPathPrefixes) || entry.changedPathPrefixes.length === 0) {
      throw new Error(`invalid Agent registry entry: ${entry.id || "<missing id>"}`)
    }
  }
  return registry
}

function loadEnabledAgents(registry) {
  return registry.agents.filter(({ enabled }) => enabled).map((entry) => {
    const configPath = resolve(REPO_ROOT, entry.configPath)
    const config = JSON.parse(readFileSync(configPath, "utf8"))
    if (config.schemaVersion !== 1 || config.id !== entry.id) {
      throw new Error(`invalid Agent CI configuration: ${entry.configPath}`)
    }
    return { ...config, configPath: entry.configPath }
  })
}

function changedFiles() {
  const candidates = [
    process.env.GIT_PREVIOUS_SUCCESSFUL_COMMIT,
    process.env.GIT_PREVIOUS_COMMIT,
  ].filter(Boolean)
  const base = candidates.find(gitCommitExists)
  if (!base) {
    return { base: null, files: [], fallbackToAll: true }
  }
  const output = git(["diff", "--name-only", `${base}...HEAD`], true)
  return { base, files: output ? output.split(/\r?\n/).filter(Boolean) : [], fallbackToAll: false }
}

function selectAgents(options, registry, enabledAgents) {
  if (options.agent === "all") {
    return { agents: enabledAgents, changeDetection: { mode: "manual-all", files: [] } }
  }
  if (options.agent !== "auto") {
    const registryEntry = registry.agents.find(({ id }) => id === options.agent)
    if (!registryEntry) throw new Error(`unknown Agent: ${options.agent}`)
    if (!registryEntry.enabled) {
      throw new Error(`${options.agent} is not CI-ready: ${registryEntry.reason || "disabled in ci/agents.json"}`)
    }
    return {
      agents: enabledAgents.filter(({ id }) => id === options.agent),
      changeDetection: { mode: "manual-agent", files: [] },
    }
  }

  const detected = changedFiles()
  if (detected.fallbackToAll) {
    return { agents: enabledAgents, changeDetection: { mode: "auto-fallback-all", ...detected } }
  }
  const commonChange = detected.files.some((path) => (
    path === "Jenkinsfile"
    || path === "ci/agents.json"
    || path.startsWith("ci/scripts/")
    || path.startsWith("ci/jenkins/")
  ))
  const onlyDocumentation = detected.files.length > 0 && detected.files.every((path) => (
    path === "README.md" || path.startsWith("docs/")
  ))
  const affectedRegistryEntries = registry.agents.filter((entry) => detected.files.some((path) => (
    entry.changedPathPrefixes.some((prefix) => path.startsWith(prefix))
  )))
  const unavailable = affectedRegistryEntries.filter(({ enabled }) => !enabled)
  if (unavailable.length > 0) {
    const details = unavailable.map((entry) => `${entry.id}: ${entry.reason || "disabled in ci/agents.json"}`)
    throw new Error(`changed Agent is not CI-ready; ${details.join("; ")}`)
  }
  let selected = []
  if (commonChange) {
    selected = enabledAgents
  } else if (!onlyDocumentation) {
    selected = enabledAgents.filter((agent) => affectedRegistryEntries.some(({ id }) => id === agent.id))
    const recognized = detected.files.every((path) => (
      path === "README.md"
      || path.startsWith("docs/")
      || registry.agents.some((entry) => entry.changedPathPrefixes.some((prefix) => path.startsWith(prefix)))
    ))
    if (!recognized) selected = enabledAgents
  }
  return { agents: selected, changeDetection: { mode: "auto", ...detected } }
}

function normalizeArchitecture(value) {
  if (value !== "native") return value
  if (arch() === "x64") return "x86_64"
  if (arch() === "arm64") return "aarch64"
  return arch()
}

function variantsFor(agent, requestedVariant) {
  if (requestedVariant === "default") return [agent.defaultVariant]
  if (requestedVariant === "all") return [...agent.variants]
  if (!agent.variants.includes(requestedVariant)) {
    throw new Error(`${agent.id} does not support variant: ${requestedVariant}`)
  }
  return [requestedVariant]
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  const registry = loadRegistry()
  const enabledAgents = loadEnabledAgents(registry)
  const selection = selectAgents(options, registry, enabledAgents)
  const targetArchitecture = normalizeArchitecture(options.targetArchitecture)
  const agents = selection.agents.map((agent) => {
    if (!agent.packageStyles.includes(options.packageStyle)) {
      throw new Error(`${agent.id} does not support package style: ${options.packageStyle}`)
    }
    if (!agent.supportedArchitectures.includes(targetArchitecture)) {
      throw new Error(`${agent.id} does not support architecture: ${targetArchitecture}`)
    }
    const variants = variantsFor(agent, options.variant)
    if (options.publish && agent.publishRequiresAllVariants && variants.length !== agent.variants.length) {
      throw new Error(`${agent.id}: publishing requires VARIANT=all`)
    }
    return {
      id: agent.id,
      displayName: agent.displayName,
      directory: agent.directory,
      driver: agent.driver,
      configPath: agent.configPath,
      variants,
    }
  })
  if (options.publish && agents.length === 0) {
    throw new Error("publishing requires at least one selected Agent")
  }
  const plan = {
    schemaVersion: 1,
    status: agents.length > 0 ? "ready" : "no-relevant-changes",
    sourceCommit: git(["rev-parse", "HEAD"]),
    requestedAgent: options.agent,
    requestedVariant: options.variant,
    packageStyle: options.packageStyle,
    targetArchitecture,
    publish: options.publish,
    changeDetection: selection.changeDetection,
    agents,
    generatedAt: new Date().toISOString(),
  }
  mkdirSync(dirname(options.output), { recursive: true })
  writeFileSync(options.output, `${JSON.stringify(plan, null, 2)}\n`)
  console.log(JSON.stringify(plan, null, 2))
}

try {
  main()
} catch (error) {
  console.error(`[resolve-plan] ${error.message}`)
  process.exit(1)
}
