#!/usr/bin/env node
// 安装契约（不联网）：npm install 无副作用 → setup install×2 / check → configure install×2 → remove×2。
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
const sandbox = mkdtempSync(join(tmpdir(), "kernel-dataset-install-contract-"))
const TEST_VARIANTS = (process.env.KERNEL_DATASET_TEST_VARIANTS || "online,offline")
  .split(",").map((variant) => variant.trim()).filter(Boolean)

if (TEST_VARIANTS.length === 0 || TEST_VARIANTS.some((variant) => !["online", "offline"].includes(variant))) {
  throw new Error("KERNEL_DATASET_TEST_VARIANTS must contain online and/or offline")
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function packageArtifact(variant) {
  const report = JSON.parse(readFileSync(join(ARTIFACT_DIR, `${variant}-package-report.json`), "utf8"))
  return { report, tgz: join(ARTIFACT_DIR, report.filename) }
}

function listBackups(configPath) {
  const prefix = `${basename(configPath)}.kernel-dataset-backup-`
  return readdirSync(dirname(configPath))
    .filter((name) => name.startsWith(prefix))
    .sort()
}

function installVariant(variant, configPath, environment, dataRoot) {
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
  assert(existsSync(join(packageRoot, "agent", "agent.md")), `${variant}: agent prompt is missing`)
  assert(!existsSync(join(packageRoot, ".runtime")), `${variant}: npm install produced runtime side effects`)
  assert(existsSync(join(packageRoot, "config", "datasets.json")), `${variant}: default dataset config is missing`)
  assert(existsSync(join(packageRoot, "src", "main.mjs")), `${variant}: collector entry is missing`)

  const checkReport = JSON.parse(execFileSync("npm", ["exec", "--offline", "--", "kernel-dataset-setup", "check"], {
    cwd: project, env: environment, encoding: "utf8",
  }))
  assert(checkReport.status === "ready", `${variant}: setup check did not report ready`)
  assert(checkReport.dataRoot === dataRoot, `${variant}: setup check ignored KERNEL_DATASET_ROOT`)
  return { project, packageRoot }
}

// 用户配置（~/.config/kernel-dataset-agent/datasets.json）应生效，且被环境变量覆盖
function exerciseUserConfig(project, environment, userDataRoot) {
  const userConfig = join(environment.XDG_CONFIG_HOME, "kernel-dataset-agent", "datasets.json")
  mkdirSync(dirname(userConfig), { recursive: true })
  writeFileSync(userConfig, `${JSON.stringify({ dataRoot: userDataRoot, intervalMs: 1800000 }, null, 2)}\n`)

  const check = (env) => JSON.parse(execFileSync("npm", ["exec", "--offline", "--", "kernel-dataset-setup", "check"], {
    cwd: project, env, encoding: "utf8",
  }))

  const fromUserConfig = check({ ...environment, KERNEL_DATASET_ROOT: undefined })
  assert(fromUserConfig.dataRoot === userDataRoot, "setup check ignored the user config data root")
  assert(fromUserConfig.dataRootSource === "user-config", `expected dataRootSource user-config, got ${fromUserConfig.dataRootSource}`)
  assert(fromUserConfig.intervalMs === 1800000, "setup check ignored the user config interval")
  assert(fromUserConfig.configFiles.includes(userConfig), "setup check did not report the user config file")

  const fromEnv = check(environment)
  assert(fromEnv.dataRoot === environment.KERNEL_DATASET_ROOT, "environment variable did not override the user config")
  assert(fromEnv.dataRootSource === "env", `expected dataRootSource env, got ${fromEnv.dataRootSource}`)
}

function exerciseSetup(project, packageRoot, environment) {
  const setup = ["exec", "--offline", "--", "kernel-dataset-setup"]
  execFileSync("npm", [...setup, "install"], { cwd: project, stdio: "inherit", env: environment })
  const marker = join(packageRoot, ".runtime", "setup-complete.json")
  assert(existsSync(marker), "setup install: marker file is missing")
  assert(JSON.parse(readFileSync(marker, "utf8")).dataRoot === environment.KERNEL_DATASET_ROOT, "setup install: marker recorded the wrong data root")
  execFileSync("npm", [...setup, "install"], { cwd: project, stdio: "inherit", env: environment })
  assert(existsSync(marker), "setup install: repeated run removed the marker file")

  const status = JSON.parse(execFileSync("npm", [...setup, "status"], { cwd: project, env: environment, encoding: "utf8" }))
  assert(status.state === "stopped", `setup status: expected stopped, got ${status.state}`)
  execFileSync("npm", [...setup, "stop"], { cwd: project, stdio: "inherit", env: environment })
}

function exerciseConfigure(project, configPath, environment) {
  const backupsBefore = listBackups(configPath).length
  execFileSync("npm", ["exec", "--offline", "--", "kernel-dataset-configure", "install"], {
    cwd: project, stdio: "inherit", env: environment,
  })
  const after = readFileSync(configPath, "utf8")
  const config = parse(after, [], { allowTrailingComma: true, disallowComments: false })
  assert(after.includes("keep-this-comment"), "configure: JSONC comment was removed")
  assert(config.custom?.token === "keep-me", "configure: unrelated custom config was changed")
  assert(config.agent?.["other-agent"], "configure: unrelated agent was removed")
  assert(
    Array.isArray(config.plugin) && config.plugin.some((spec) => (
      typeof spec === "string" && spec.endsWith("/dist/index.js") && spec.includes("kernel-dataset")
    )),
    "configure: kernel-dataset plugin was not registered",
  )
  assert(listBackups(configPath).length === backupsBefore + 1, "configure: did not create exactly one backup")

  const skillsDir = join(dirname(configPath), "skills")
  const skillLink = join(skillsDir, "kernel-dataset")
  assert(existsSync(skillLink) && lstatSync(skillLink).isSymbolicLink(), "configure: skill link is missing")
  assert(existsSync(join(readlinkSync(skillLink), "SKILL.md")), "configure: skill link target has no SKILL.md")

  execFileSync("npm", ["exec", "--offline", "--", "kernel-dataset-configure", "install"], {
    cwd: project, stdio: "inherit", env: environment,
  })
  assert(readFileSync(configPath, "utf8") === after, "configure: repeated run changed config bytes")
  assert(listBackups(configPath).length === backupsBefore + 1, "configure: repeated no-op run created a backup")
}

function exerciseRemove(project, configPath, environment) {
  const backupsBefore = listBackups(configPath).length
  execFileSync("npm", ["exec", "--offline", "--", "kernel-dataset-configure", "remove"], {
    cwd: project, stdio: "inherit", env: environment,
  })
  const after = readFileSync(configPath, "utf8")
  const config = parse(after, [], { allowTrailingComma: true, disallowComments: false })
  assert(after.includes("keep-this-comment"), "configure remove: JSONC comment was removed")
  assert(config.custom?.token === "keep-me", "configure remove: unrelated custom config was changed")
  assert(config.agent?.["other-agent"], "configure remove: unrelated agent was removed")
  assert(
    !Array.isArray(config.plugin) || !config.plugin.some((spec) => (
      typeof spec === "string" && spec.endsWith("/dist/index.js") && spec.includes("kernel-dataset")
    )),
    "configure remove: kernel-dataset plugin registration remains",
  )
  assert(listBackups(configPath).length === backupsBefore + 1, "configure remove: did not create exactly one backup")

  const skillLink = join(dirname(configPath), "skills", "kernel-dataset")
  assert(!existsSync(skillLink), "configure remove: skill link was not removed")

  execFileSync("npm", ["exec", "--offline", "--", "kernel-dataset-configure", "remove"], {
    cwd: project, stdio: "inherit", env: environment,
  })
  assert(readFileSync(configPath, "utf8") === after, "configure remove: repeated run changed config")
  assert(listBackups(configPath).length === backupsBefore + 1, "configure remove: repeated no-op run created a backup")
}

try {
  const home = join(sandbox, "home")
  const dataRoot = join(sandbox, "data")
  const configPath = join(home, ".config", "opencode", "opencode.jsonc")
  mkdirSync(dirname(configPath), { recursive: true })
  mkdirSync(dataRoot, { recursive: true })
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
    KERNEL_DATASET_OPENCODE_CONFIG: configPath,
    KERNEL_DATASET_ROOT: dataRoot,
    npm_config_audit: "false",
    npm_config_fund: "false",
  }

  for (const variant of TEST_VARIANTS) {
    const installation = installVariant(variant, configPath, environment, dataRoot)
    exerciseUserConfig(installation.project, environment, join(sandbox, `data-user-${variant}`))
    exerciseSetup(installation.project, installation.packageRoot, environment)
    exerciseConfigure(installation.project, configPath, environment)
    exerciseRemove(installation.project, configPath, environment)
  }
  console.log("install contract: PASS")
} finally {
  rmSync(sandbox, { recursive: true, force: true })
}