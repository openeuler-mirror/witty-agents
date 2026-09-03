#!/usr/bin/env node

import { execFileSync, spawnSync } from "node:child_process"
import { existsSync, mkdirSync, readFileSync, rmSync } from "node:fs"
import { arch } from "node:os"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const CI_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = resolve(CI_DIR, "..")
const ARTIFACT_DIR = join(PROJECT_ROOT, "artifacts")
const REPORT_DIR = join(PROJECT_ROOT, "ci-reports")
const NPM_CACHE_DIR = process.env.NPM_CONFIG_CACHE || join(PROJECT_ROOT, ".ci-npm-cache")
const VALID_PHASES = new Set([
  "prepare", "prepare-assets", "install-dependencies", "validate", "build",
  "artifact-gates", "install-contract", "real-install",
])

function parseArgs(argv) {
  const options = {
    phase: null,
    variants: (process.env.SELECTED_VARIANTS || "online").split(",").filter(Boolean),
    packageStyle: process.env.PACKAGE_STYLE || "organization",
    targetArchitecture: process.env.TARGET_ARCH || "native",
  }
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]
    const [rawKey, inlineValue] = argument.split("=", 2)
    const key = rawKey.replace(/^--/, "")
    const value = inlineValue ?? argv[++index]
    if (key === "phase") options.phase = value
    else if (key === "variants") options.variants = value.split(",").filter(Boolean)
    else if (key === "package-style") options.packageStyle = value
    else if (key === "target-arch") options.targetArchitecture = value
    else throw new Error(`unknown argument: ${argument}`)
  }
  if (!VALID_PHASES.has(options.phase)) throw new Error(`unsupported phase: ${options.phase}`)
  if (options.variants.some((variant) => !["online", "offline"].includes(variant))) {
    throw new Error("variants must contain online and/or offline")
  }
  return options
}

function run(command, args, extra = {}) {
  const { env: extraEnvironment = {}, ...extraOptions } = extra
  execFileSync(command, args, {
    cwd: PROJECT_ROOT,
    env: { ...process.env, NPM_CONFIG_CACHE: NPM_CACHE_DIR, ...extraEnvironment },
    stdio: "inherit",
    ...extraOptions,
  })
}

function canRun(command, args) {
  return spawnSync(command, args, { cwd: PROJECT_ROOT, stdio: "ignore" }).status === 0
}

function nativeArchitecture() {
  if (arch() === "x64") return "x86_64"
  if (arch() === "arm64") return "aarch64"
  return arch()
}

function prepare(options) {
  rmSync(ARTIFACT_DIR, { recursive: true, force: true })
  rmSync(REPORT_DIR, { recursive: true, force: true })
  rmSync(join(PROJECT_ROOT, ".package-stage"), { recursive: true, force: true })
  mkdirSync(ARTIFACT_DIR, { recursive: true })
  mkdirSync(REPORT_DIR, { recursive: true })

  const nodeMajor = Number(process.versions.node.split(".")[0])
  if (nodeMajor < 20) throw new Error(`Node.js 20+ required, got ${process.version}`)
  const npmVersion = execFileSync("npm", ["--version"], { encoding: "utf8" }).trim()
  if (Number(npmVersion.split(".")[0]) < 10) throw new Error(`npm 10+ required, got ${npmVersion}`)
  const python = process.env.PYTHON_BIN || "python3.11"
  run(python, ["-c", "import sys; assert (3, 11) <= sys.version_info[:2] < (3, 13), sys.version"])
  run(python, ["-m", "pip", "--version"])
  run("git", ["lfs", "version"])

  const osRelease = readFileSync("/etc/os-release", "utf8")
  if (!/^ID=["']?openeuler["']?$/mi.test(osRelease)) {
    throw new Error("Shennong Jenkins build must run in openEuler")
  }
  const actualArchitecture = nativeArchitecture()
  if (options.targetArchitecture !== actualArchitecture) {
    throw new Error(`TARGET_ARCH=${options.targetArchitecture} requires a native ${options.targetArchitecture} node; current node is ${actualArchitecture}`)
  }

  if (process.env.RUN_REAL_INSTALL_VALIDATION === "true") {
    const libraries = ["libGL.so.1", "libgthread-2.0.so.0", "libXext.so.6", "libXrender.so.1", "libSM.so.6"]
    const ldconfig = execFileSync("ldconfig", ["-p"], { encoding: "utf8" })
    const missing = libraries.filter((library) => !ldconfig.includes(library))
    if (missing.length > 0) throw new Error(`missing openEuler runtime libraries: ${missing.join(", ")}`)
    if (options.variants.includes("offline") && !canRun("sh", ["-c", "command -v unshare >/dev/null && command -v ip >/dev/null"])) {
      throw new Error("offline validation requires unshare and iproute")
    }
  }
  console.log(`Node=${process.version} npm=${npmVersion} Python=${python} architecture=${actualArchitecture}`)
}

function prepareAssets() {
  if (!canRun("git", ["lfs", "pull"])) {
    console.warn("WARNING: git lfs pull failed; checking the trusted OCR cache")
  }
  run(process.execPath, [
    "scripts/prepare-ocr-models.mjs",
    `--cache-dir=${process.env.OCR_MODEL_CACHE_DIR || "/home/shennong-jenkins/ocr-model-cache"}`,
  ])
}

function build(options) {
  const python = process.env.PYTHON_BIN || "python3.11"
  for (const variant of options.variants) {
    const args = [
      "run", "pack:variant", "--",
      `--variant=${variant}`,
      `--package-style=${options.packageStyle}`,
      "--out-dir=artifacts",
    ]
    if (variant === "offline") args.push(`--python=${python}`)
    run("npm", args, { env: { PIP_INDEX_URL: process.env.PYPI_INDEX_URL || process.env.PIP_INDEX_URL || "https://mirrors.huaweicloud.com/repository/pypi/simple" } })
  }
}

function verifyInstall(variant, options) {
  const report = JSON.parse(readFileSync(join(ARTIFACT_DIR, `${variant}-package-report.json`), "utf8"))
  const args = [
    "scripts/verify-package-install.mjs",
    `--variant=${variant}`,
    `--artifact=${join(ARTIFACT_DIR, report.filename)}`,
    `--python=${process.env.PYTHON_BIN || "python3.11"}`,
    `--report=${join(REPORT_DIR, `install-flow-${variant}.json`)}`,
  ]
  const installEnv = { PIP_INDEX_URL: process.env.PYPI_INDEX_URL || process.env.PIP_INDEX_URL || "https://mirrors.huaweicloud.com/repository/pypi/simple" }
  if (variant === "online") {
    run(process.execPath, args, { env: { ...installEnv, SHENNONG_NETWORK_ISOLATION: "none" } })
    return
  }

  let unshareArgs = null
  let isolation = null
  if (canRun("unshare", ["--net", "true"])) {
    unshareArgs = ["--net"]
    isolation = "unshare"
  } else if (canRun("unshare", ["--user", "--map-root-user", "--net", "true"])) {
    unshareArgs = ["--user", "--map-root-user", "--net"]
    isolation = "user-netns"
  }
  if (!unshareArgs) {
    if (process.env.STRICT_OFFLINE_NETWORK_CHECK === "true") {
      throw new Error("offline network isolation is unavailable on this Jenkins node")
    }
    console.warn("WARNING: physical network isolation is not enforced")
    run(process.execPath, args, { env: { ...installEnv, SHENNONG_NETWORK_ISOLATION: "not-enforced" } })
    return
  }
  run("unshare", [
    ...unshareArgs,
    "sh", "-c",
    "ip link set lo up && export SHENNONG_NETWORK_ISOLATION=\"$1\" && shift && exec \"$@\"",
    "sh", isolation, process.execPath, ...args,
  ], { env: installEnv })
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  if (options.phase === "prepare") prepare(options)
  else if (options.phase === "prepare-assets") prepareAssets()
  else if (options.phase === "install-dependencies") run("npm", ["ci", "--ignore-scripts", "--no-audit", "--no-fund"])
  else if (options.phase === "validate") run("npm", ["run", "build"])
  else if (options.phase === "build") build(options)
  else if (options.phase === "artifact-gates") run("npm", [
    "run", "ci:verify-artifacts", "--",
    `--variants=${options.variants.join(",")}`,
    `--package-style=${options.packageStyle}`,
  ])
  else if (options.phase === "install-contract") run("npm", ["run", "test:install-contract"], {
    env: { SHENNONG_TEST_VARIANTS: options.variants.join(",") },
  })
  else if (options.phase === "real-install") {
    if (process.env.RUN_REAL_INSTALL_VALIDATION !== "true") {
      console.log("real install validation disabled")
      return
    }
    for (const variant of options.variants) verifyInstall(variant, options)
  }
}

try {
  main()
} catch (error) {
  console.error(`[shennong-ci] ${error.message}`)
  process.exit(1)
}
