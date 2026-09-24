#!/usr/bin/env node

import { execFileSync } from "node:child_process"
import { mkdirSync, readFileSync, rmSync } from "node:fs"
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
  if (options.variants.length === 0 || options.variants.some((variant) => !["online"].includes(variant))) {
    throw new Error("only the online variant is supported")
  }
  return options
}

function run(command, args, extra = {}) {
  const { env: extraEnvironment = {} } = extra
  execFileSync(command, args, {
    cwd: PROJECT_ROOT,
    env: { ...process.env, NPM_CONFIG_CACHE: NPM_CACHE_DIR, ...extraEnvironment },
    stdio: "inherit",
  })
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

  console.log(`Node=${process.version} npm=${npmVersion}`)
}

function verifyInstall(variant) {
  const report = JSON.parse(readFileSync(join(ARTIFACT_DIR, `${variant}-package-report.json`), "utf8"))
  const args = [
    "scripts/verify-package-install.mjs",
    `--variant=${variant}`,
    `--artifact=${join(ARTIFACT_DIR, report.filename)}`,
    `--report=${join(REPORT_DIR, `install-flow-${variant}.json`)}`,
  ]
  run(process.execPath, args)
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  if (options.phase === "prepare") prepare(options)
  else if (options.phase === "prepare-assets") console.log("[vllm-ci] no external assets to prepare")
  else if (options.phase === "install-dependencies") {
    run("npm", ["ci", "--ignore-scripts", "--no-audit", "--no-fund"])
    run(process.execPath, ["bin/vllm-benchmark-setup.mjs", "install"])
  }
  else if (options.phase === "validate") {
    run("npm", ["run", "validate"])
    run("npm", ["test"])
  }
  else if (options.phase === "build") {
    for (const variant of options.variants) {
      run("npm", ["run", "pack:variant", "--",
        `--variant=${variant}`,
        `--package-style=${options.packageStyle}`,
        "--out-dir=artifacts",
        `--target-arch=${options.targetArchitecture}`,
      ])
    }
  }
  else if (options.phase === "artifact-gates") run("npm", ["run", "ci:verify-artifacts", "--",
    `--variants=${options.variants.join(",")}`,
    `--package-style=${options.packageStyle}`,
  ])
  else if (options.phase === "install-contract") run("npm", ["run", "test:install-contract"], {
    env: { VLLM_BENCHMARK_TEST_VARIANTS: options.variants.join(",") },
  })
  else if (options.phase === "real-install") {
    if (process.env.RUN_REAL_INSTALL_VALIDATION !== "true") {
      console.log("real install validation disabled")
      return
    }
    for (const variant of options.variants) verifyInstall(variant)
  }
}

try {
  main()
} catch (error) {
  console.error(`[vllm-ci] ${error.message}`)
  process.exit(1)
}