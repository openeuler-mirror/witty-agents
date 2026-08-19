#!/usr/bin/env node
import { existsSync, mkdirSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { execSync } from "node:child_process"

const __dirname = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = __dirname

const VENV_DIR = join(PROJECT_ROOT, ".venvs")

const VENVS = [
  {
    name: "crash-feature-matcher",
    requirements: join(PROJECT_ROOT, "skills", "crash-feature-matcher", "requirements.txt"),
    pyproject: join(PROJECT_ROOT, "skills", "crash-feature-matcher", "pyproject.toml"),
    editable: true,
  },
  {
    name: "witty-log-detection",
    requirements: join(PROJECT_ROOT, "skills", "witty-log-detection", "src", "requirements.txt"),
    pyproject: join(PROJECT_ROOT, "skills", "witty-log-detection", "src", "pyproject.toml"),
    editable: false,
  },
  {
    name: "crash-report-generator",
    requirements: join(PROJECT_ROOT, "skills", "crash-report-generator", "requirements.txt"),
    pyproject: null,
    editable: false,
  },
]

function findPython() {
  const candidates = ["python3", "python"]
  for (const cmd of candidates) {
    try {
      execSync(`${cmd} --version`, { stdio: "ignore" })
      return cmd
    } catch {
      continue
    }
  }
  return null
}

function main() {
  const python = findPython()
  if (!python) {
    console.error("[shennong-crash-agent] ERROR: python3 not found. Please install Python >=3.9.")
    process.exit(1)
  }

  console.log(`[shennong-crash-agent] Using Python: ${python}`)
  mkdirSync(VENV_DIR, { recursive: true })

  for (const venv of VENVS) {
    const venvPath = join(VENV_DIR, venv.name)
    const venvPython = join(venvPath, "bin", "python")

    if (existsSync(venvPath)) {
      console.log(`[shennong-crash-agent] venv already exists: ${venvPath}, skipping creation`)
    } else {
      console.log(`[shennong-crash-agent] Creating venv: ${venvPath}`)
      execSync(`${python} -m venv ${venvPath}`, { stdio: "inherit", cwd: PROJECT_ROOT })
    }

    if (existsSync(venv.requirements)) {
      console.log(`[shennong-crash-agent] Installing requirements for ${venv.name}`)
      execSync(`${venvPython} -m pip install -r ${venv.requirements}`, { stdio: "inherit", cwd: PROJECT_ROOT })
    }

    if (venv.editable && existsSync(venv.pyproject)) {
      const pkgDir = dirname(venv.pyproject)
      console.log(`[shennong-crash-agent] Installing editable package for ${venv.name} from ${pkgDir}`)
      execSync(`${venvPython} -m pip install -e ${pkgDir}`, { stdio: "inherit", cwd: PROJECT_ROOT })
    }
  }

  console.log("[shennong-crash-agent] MCP venvs setup complete.")
  console.log("")
  console.log("[shennong-crash-agent] Next step: register this plugin in OpenCode.")
  console.log("  Add the following to ~/.config/opencode/opencode.jsonc (or .opencode/opencode.jsonc):")
  console.log("")
  console.log('  {')
  console.log('    "plugin": ["shennong-crash-agent"],')
  console.log('    "$schema": "https://opencode.ai/config.json"')
  console.log('  }')
  console.log("")
  console.log("  Then restart OpenCode and run: opencode agent list")

}

main()
