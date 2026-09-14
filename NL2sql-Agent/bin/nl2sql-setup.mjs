#!/usr/bin/env node

import { createHash } from "node:crypto"
import { execFileSync } from "node:child_process"
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { homedir } from "node:os"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const BIN_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = resolve(BIN_DIR, "..")
const VARIANT_FILE = join(PROJECT_ROOT, "package-variant.json")
const WHEEL_MANIFEST_FILE = join(PROJECT_ROOT, "python-wheel-manifest.json")
const CONTENT_MANIFEST_FILE = join(PROJECT_ROOT, "package-content-manifest.json")
const REQUIREMENTS_FILE = join(PROJECT_ROOT, "requirements.txt")

const IMPORT_MODULES = [
  "fastapi",
  "uvicorn",
  "pydantic",
  "pydantic_settings",
  "httpx",
  "openai",
  "yaml",
  "dotenv",
  "aiofiles",
  "sse_starlette",
  "nl2sql_core",
]

function venvDirForPackage(packageName) {
  const key = String(packageName).replace(/^@/, "").replace(/\//g, "-")
  const cacheRoot = process.env.NL2SQL_VENV_CACHE
    ? resolve(process.env.NL2SQL_VENV_CACHE)
    : join(homedir(), ".cache", "witty-agents")
  return join(cacheRoot, key, "venvs", "nl2sql")
}

function usage() {
  console.log(`Usage:
  nl2sql-setup install [--python /path/to/python] [--force]
  nl2sql-setup check   [--python /path/to/python]

Commands:
  install   Create a virtual environment and install the backend dependencies (default)
  check     Verify package variant, Python, and (offline) wheel platform without changing files`)
}

function parseArgs(argv) {
  const options = { command: "install", python: process.env.NL2SQL_PYTHON || null, force: false }
  let commandSeen = false
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (["install", "check"].includes(arg) && !commandSeen) {
      options.command = arg
      commandSeen = true
    } else if (arg === "--force") {
      options.force = true
    } else if (arg.startsWith("--python=")) {
      options.python = arg.slice("--python=".length)
    } else if (arg === "--python") {
      options.python = argv[++index]
    } else if (arg === "--help" || arg === "-h") {
      usage()
      process.exit(0)
    } else {
      throw new Error(`unknown argument: ${arg}`)
    }
  }
  return options
}

function inspectPython(cmd) {
  const output = execFileSync(cmd, [
    "-c",
    "import json,platform,sys,sysconfig; print(json.dumps({'python': platform.python_version(), 'implementation': platform.python_implementation(), 'system': platform.system().lower(), 'machine': platform.machine(), 'cache_tag': sys.implementation.cache_tag, 'sysconfig_platform': sysconfig.get_platform(), 'soabi': sysconfig.get_config_var('SOABI'), 'libc': list(platform.libc_ver())}))",
  ], { encoding: "utf8" }).trim()
  return JSON.parse(output)
}

function isPythonSupported(info) {
  const [major, minor] = info.python.split(".").map(Number)
  return major === 3 && minor >= 11 && minor < 13
}

function matchesWheelPlatform(info, expected) {
  if (!expected) return true
  const actualMinor = info.python.split(".").slice(0, 2).join(".")
  const expectedMinor = expected.python.split(".").slice(0, 2).join(".")
  return actualMinor === expectedMinor
    && info.implementation === expected.implementation
    && info.system === expected.system
    && info.machine === expected.machine
    && info.cache_tag === expected.cache_tag
    && (!expected.sysconfig_platform || info.sysconfig_platform === expected.sysconfig_platform)
    && (!expected.soabi || info.soabi === expected.soabi)
}

function findPython(expectedPlatform, explicitPython) {
  const candidates = explicitPython
    ? [explicitPython]
    : [...new Set([
      process.env.PYTHON_BIN,
      "python3.11",
      "python3.12",
      "python3",
      "python",
    ].filter(Boolean))]
  for (const cmd of candidates) {
    try {
      const info = inspectPython(cmd)
      if (isPythonSupported(info) && matchesWheelPlatform(info, expectedPlatform)) {
        return { command: cmd, info }
      }
    } catch (error) {
      if (explicitPython) {
        throw new Error(`specified Python is unavailable or incompatible: ${explicitPython}: ${error.message}`)
      }
    }
  }
  if (explicitPython) {
    const info = inspectPython(explicitPython)
    throw new Error(`specified Python is incompatible: ${explicitPython} (${JSON.stringify(info)})`)
  }
  return null
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex")
}

function getPackageMetadata() {
  if (!existsSync(VARIANT_FILE)) throw new Error(`package variant metadata is missing: ${VARIANT_FILE}`)
  const metadata = JSON.parse(readFileSync(VARIANT_FILE, "utf8"))
  if (!["online", "offline"].includes(metadata.variant)) throw new Error(`invalid package variant: ${metadata.variant}`)
  const packageJson = JSON.parse(readFileSync(join(PROJECT_ROOT, "package.json"), "utf8"))
  return { ...metadata, packageName: packageJson.name, packageVersion: packageJson.version }
}

function childEnvironment(offline) {
  return {
    ...process.env,
    PYTHONNOUSERSITE: "1",
    PIP_DISABLE_PIP_VERSION_CHECK: "1",
    ...(offline ? { PIP_NO_INDEX: "1" } : {}),
  }
}

function verifyEnvironment(venvPython, offline) {
  const importProgram = [
    "import importlib",
    ...IMPORT_MODULES.map((moduleName) => `importlib.import_module(${JSON.stringify(moduleName)})`),
  ].join("; ")
  execFileSync(venvPython, ["-c", importProgram], {
    stdio: "inherit",
    cwd: PROJECT_ROOT,
    env: { ...childEnvironment(offline), PYTHONPATH: PROJECT_ROOT },
  })
}

function checkSetup(options) {
  const metadata = getPackageMetadata()
  if (!existsSync(CONTENT_MANIFEST_FILE)) throw new Error(`package content manifest is missing: ${CONTENT_MANIFEST_FILE}`)
  const contentManifest = JSON.parse(readFileSync(CONTENT_MANIFEST_FILE, "utf8"))
  if (!metadata.contentComplete || !contentManifest.contentComplete) {
    throw new Error("package content is incomplete; Git LFS files were not materialized")
  }
  const wheelManifest = metadata.variant === "offline"
    ? JSON.parse(readFileSync(WHEEL_MANIFEST_FILE, "utf8"))
    : null
  if (wheelManifest && JSON.stringify(metadata.wheelPlatform) !== JSON.stringify(wheelManifest.platform)) {
    throw new Error("offline wheel platform metadata does not match its wheel manifest")
  }
  const expectedPlatform = metadata.variant === "offline" ? wheelManifest.platform : null
  const python = findPython(expectedPlatform, options.python)
  if (!python) {
    const expected = expectedPlatform
      ? `${expectedPlatform.system}/${expectedPlatform.machine}/${expectedPlatform.cache_tag}`
      : "Python 3.11 or 3.12"
    throw new Error(`compatible Python not found; expected ${expected}`)
  }
  console.log(JSON.stringify({
    package: metadata.packageName,
    version: metadata.packageVersion,
    variant: metadata.variant,
    python: python.info,
    pythonDependencies: metadata.variant === "offline" ? "bundled-wheels" : "download-on-install",
    wheelCount: wheelManifest?.wheelCount || 0,
    status: "ready",
  }, null, 2))
  return { metadata, wheelManifest, python }
}

function fingerprints(metadata, wheelManifest) {
  return {
    contentManifestSha256: sha256(CONTENT_MANIFEST_FILE),
    wheelManifestSha256: metadata.variant === "offline" ? sha256(WHEEL_MANIFEST_FILE) : null,
  }
}

function install(options) {
  const { metadata, wheelManifest, python } = checkSetup(options)
  const offline = metadata.variant === "offline"
  const venvDir = venvDirForPackage(metadata.packageName)
  const venvPython = join(venvDir, "bin", "python")
  const markerPath = join(venvDir, "setup-complete.json")
  const fingerprint = fingerprints(metadata, wheelManifest)

  if (existsSync(markerPath) && !options.force) {
    try {
      const marker = JSON.parse(readFileSync(markerPath, "utf8"))
      if (
        marker.package === metadata.packageName
        && marker.version === metadata.packageVersion
        && marker.variant === metadata.variant
        && JSON.stringify(marker.python) === JSON.stringify(python.info)
        && marker.contentManifestSha256 === fingerprint.contentManifestSha256
        && marker.wheelManifestSha256 === fingerprint.wheelManifestSha256
        && existsSync(venvPython)
      ) {
        verifyEnvironment(venvPython, offline)
        console.log("[nl2sql-setup] Python dependencies are already installed and verified.")
        return
      }
    } catch {
      // fall through to a clean rebuild
    }
  }

  rmSync(venvDir, { recursive: true, force: true })
  mkdirSync(venvDir, { recursive: true })
  console.log(`[nl2sql-setup] Creating venv: ${venvDir}`)
  execFileSync(python.command, ["-m", "venv", venvDir], {
    stdio: "inherit",
    cwd: PROJECT_ROOT,
    env: childEnvironment(offline),
  })

  const pip = [venvPython, "-m", "pip", "install", "--disable-pip-version-check"]
  if (offline) {
    const wheelRoot = join(PROJECT_ROOT, "python-wheels")
    if (!existsSync(wheelRoot)) throw new Error(`offline wheelhouse is missing: ${wheelRoot}`)
    pip.push("--no-index", "--find-links", wheelRoot)
  }
  pip.push("-r", REQUIREMENTS_FILE)
  execFileSync(pip[0], pip.slice(1), {
    stdio: "inherit",
    cwd: PROJECT_ROOT,
    env: childEnvironment(offline),
  })

  verifyEnvironment(venvPython, offline)

  writeFileSync(markerPath, `${JSON.stringify({
    package: metadata.packageName,
    version: metadata.packageVersion,
    variant: metadata.variant,
    python: python.info,
    ...fingerprint,
    completedAt: new Date().toISOString(),
  }, null, 2)}\n`)
  console.log("[nl2sql-setup] Python dependencies installed successfully.")
}

try {
  const options = parseArgs(process.argv.slice(2))
  if (options.command === "check") {
    checkSetup(options)
  } else {
    install(options)
  }
} catch (error) {
  console.error(`[nl2sql-setup] ${error.message}`)
  process.exit(1)
}