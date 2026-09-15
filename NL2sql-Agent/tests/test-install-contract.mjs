#!/usr/bin/env node

import { execFileSync } from "node:child_process"
import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  readlinkSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { basename, dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { parse } from "jsonc-parser"

const TEST_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = resolve(TEST_DIR, "..")
const ARTIFACT_DIR = join(PROJECT_ROOT, "artifacts")
const sandbox = mkdtempSync(join(tmpdir(), "nl2sql-install-contract-"))
const TEST_VARIANTS = (process.env.NL2SQL_TEST_VARIANTS || "online,offline")
  .split(",").map((variant) => variant.trim()).filter(Boolean)

if (TEST_VARIANTS.length === 0 || TEST_VARIANTS.some((variant) => !["online", "offline"].includes(variant))) {
  throw new Error("NL2SQL_TEST_VARIANTS must contain online and/or offline")
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function packageArtifact(variant) {
  const report = JSON.parse(readFileSync(join(ARTIFACT_DIR, `${variant}-package-report.json`), "utf8"))
  return { report, tgz: join(ARTIFACT_DIR, report.filename) }
}

function listBackups(configPath) {
  const prefix = `${basename(configPath)}.nl2sql-backup-`
  return readdirSync(dirname(configPath))
    .filter((name) => name.startsWith(prefix))
    .sort()
}

function installVariant(variant, configPath, environment) {
  const { report, tgz } = packageArtifact(variant)
  const project = join(sandbox, `consumer-${variant}`)
  mkdirSync(project, { recursive: true })
  writeFileSync(join(project, "package.json"), `${JSON.stringify({ name: `consumer-${variant}`, private: true }, null, 2)}\n`)
  const configBefore = readFileSync(configPath, "utf8")
  execFileSync("npm", [
    "install", "--no-audit", "--no-fund",
    ...(variant === "offline" ? ["--offline", "--cache", join(sandbox, "empty-offline-npm-cache")] : []),
    tgz,
  ], { cwd: project, stdio: "inherit", env: environment })
  assert(readFileSync(configPath, "utf8") === configBefore, `${variant}: npm install changed OpenCode configuration`)

  const packageRoot = join(project, "node_modules", ...report.packageName.split("/"))
  assert(existsSync(packageRoot), `${variant}: installed package directory is missing`)
  assert(existsSync(join(packageRoot, "package-content-manifest.json")), `${variant}: content manifest is missing`)
  assert(existsSync(join(packageRoot, "opencode_plugin", "role-prompt.md")), `${variant}: agent prompt is missing`)
  return { project, packageRoot }
}

function exerciseConfigure(project, configPath, environment) {
  const backupsBefore = listBackups(configPath).length
  execFileSync("npm", ["exec", "--offline", "--", "nl2sql-agent", "configure"], {
    cwd: project, stdio: "inherit", env: environment,
  })
  const after = readFileSync(configPath, "utf8")
  const config = parse(after, [], { allowTrailingComma: true, disallowComments: false })
  assert(after.includes("keep-this-comment"), "configure: JSONC comment was removed")
  assert(config.custom?.token === "keep-me", "configure: unrelated custom config was changed")
  assert(config.agent?.["other-agent"], "configure: unrelated agent was removed")
  assert(
    Array.isArray(config.plugin) && config.plugin.some((spec) => (
      typeof spec === "string" && spec.endsWith("/dist/index.js") && spec.includes("nl2sql")
    )),
    "configure: nl2sql plugin was not registered",
  )
  assert(listBackups(configPath).length === backupsBefore + 1, "configure: did not create exactly one backup")

  const skillLink = join(environment.XDG_CONFIG_HOME, "opencode", "skills", "nl2sql")
  assert(lstatSync(skillLink).isSymbolicLink(), "configure: nl2sql skill link is missing")
  assert(existsSync(join(readlinkSync(skillLink), "SKILL.md")), "configure: nl2sql skill link target has no SKILL.md")

  execFileSync("npm", ["exec", "--offline", "--", "nl2sql-agent", "configure"], {
    cwd: project, stdio: "inherit", env: environment,
  })
  assert(readFileSync(configPath, "utf8") === after, "configure: repeated run changed config bytes")
  assert(listBackups(configPath).length === backupsBefore + 1, "configure: repeated no-op run created a backup")
}

function exerciseRemove(project, configPath, environment) {
  const backupsBefore = listBackups(configPath).length
  execFileSync("npm", ["exec", "--offline", "--", "nl2sql-agent", "remove"], {
    cwd: project, stdio: "inherit", env: environment,
  })
  const after = readFileSync(configPath, "utf8")
  const config = parse(after, [], { allowTrailingComma: true, disallowComments: false })
  assert(after.includes("keep-this-comment"), "configure remove: JSONC comment was removed")
  assert(config.custom?.token === "keep-me", "configure remove: unrelated custom config was changed")
  assert(config.agent?.["other-agent"], "configure remove: unrelated agent was removed")
  assert(
    !Array.isArray(config.plugin) || !config.plugin.some((spec) => (
      typeof spec === "string" && spec.endsWith("/dist/index.js") && spec.includes("nl2sql")
    )),
    "configure remove: nl2sql plugin registration remains",
  )
  assert(
    !existsSync(join(environment.XDG_CONFIG_HOME, "opencode", "skills", "nl2sql")),
    "configure remove: nl2sql skill link remains",
  )
  assert(listBackups(configPath).length === backupsBefore + 1, "configure remove: did not create exactly one backup")

  execFileSync("npm", ["exec", "--offline", "--", "nl2sql-agent", "remove"], {
    cwd: project, stdio: "inherit", env: environment,
  })
  assert(readFileSync(configPath, "utf8") === after, "configure remove: repeated run changed config")
  assert(listBackups(configPath).length === backupsBefore + 1, "configure remove: repeated no-op run created a backup")
}

function exerciseOfflineSetup(packageRoot, project, environment) {
  for (const required of ["nl2sql_core", "apps", "requirements.txt", "python-wheels", "python-wheel-manifest.json"]) {
    assert(existsSync(join(packageRoot, required)), `offline: bundled backend path is missing: ${required}`)
  }
  const install = ["exec", "--offline", "--", "nl2sql-setup", "install"]
  execFileSync("npm", install, { cwd: project, stdio: "inherit", env: environment })
  execFileSync("npm", ["exec", "--offline", "--", "nl2sql-setup", "check"], { cwd: project, stdio: "inherit", env: environment })
  execFileSync("npm", install, { cwd: project, stdio: "inherit", env: environment })
}

try {
  const home = join(sandbox, "home")
  const configPath = join(home, ".config", "opencode", "opencode.jsonc")
  mkdirSync(dirname(configPath), { recursive: true })
  writeFileSync(configPath, `{
  // keep-this-comment
  "$schema": "https://opencode.ai/config.json",
  "agent": { "other-agent": { "description": "keep-me", "prompt": "{file:/tmp/other.md}" }, },
  "theme": "system",
  "custom": { "token": "keep-me", },
}
`)

  const environment = {
    ...process.env,
    HOME: home,
    XDG_CONFIG_HOME: join(home, ".config"),
    NL2SQL_OPENCODE_CONFIG: configPath,
    npm_config_audit: "false",
    npm_config_fund: "false",
  }

  const configured = []
  for (const variant of TEST_VARIANTS) {
    const installation = installVariant(variant, configPath, environment)
    exerciseConfigure(installation.project, configPath, environment)
    if (variant === "offline") exerciseOfflineSetup(installation.packageRoot, installation.project, environment)
    exerciseRemove(installation.project, configPath, environment)
    configured.push(installation)
  }
  console.log("install contract: PASS")
} finally {
  rmSync(sandbox, { recursive: true, force: true })
}