#!/usr/bin/env node

import { execFileSync } from "node:child_process"
import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(SCRIPT_DIR, "../..")
const VALID_PHASES = new Set([
  "prepare",
  "prepare-assets",
  "install-dependencies",
  "validate",
  "build",
  "artifact-gates",
  "install-contract",
  "real-install",
])

function parseArgs(argv) {
  let phase = null
  let planPath = resolve(REPO_ROOT, "ci-artifacts/build-plan.json")
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]
    if (argument.startsWith("--phase=")) phase = argument.slice("--phase=".length)
    else if (argument === "--phase") phase = argv[++index]
    else if (argument.startsWith("--plan=")) planPath = resolve(REPO_ROOT, argument.slice("--plan=".length))
    else if (argument === "--plan") planPath = resolve(REPO_ROOT, argv[++index])
    else throw new Error(`unknown argument: ${argument}`)
  }
  if (!VALID_PHASES.has(phase)) throw new Error(`unknown phase: ${phase}`)
  return { phase, planPath }
}

function main() {
  const { phase, planPath } = parseArgs(process.argv.slice(2))
  const plan = JSON.parse(readFileSync(planPath, "utf8"))
  if (!Array.isArray(plan.agents)) throw new Error("invalid build plan")
  if (plan.agents.length === 0) {
    console.log(`[${phase}] no affected Agent; stage skipped`)
    return
  }
  for (const agent of plan.agents) {
    const directory = resolve(REPO_ROOT, agent.directory)
    const driver = resolve(directory, agent.driver)
    console.log(`===== ${agent.displayName}: ${phase} =====`)
    execFileSync(process.execPath, [
      driver,
      `--phase=${phase}`,
      `--variants=${agent.variants.join(",")}`,
      `--package-style=${plan.packageStyle}`,
      `--target-arch=${plan.targetArchitecture}`,
    ], {
      cwd: directory,
      env: {
        ...process.env,
        WITTY_AGENT_ID: agent.id,
        SELECTED_VARIANTS: agent.variants.join(","),
        PACKAGE_STYLE: plan.packageStyle,
        TARGET_ARCH: plan.targetArchitecture,
      },
      stdio: "inherit",
    })
  }
}

try {
  main()
} catch (error) {
  console.error(`[agent-phase] ${error.message}`)
  process.exit(1)
}
