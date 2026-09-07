#!/usr/bin/env node

import { execFileSync } from "node:child_process"
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { basename, dirname, join, resolve } from "node:path"
import { pathToFileURL } from "node:url"
import { parse } from "jsonc-parser"

const VENV_NAMES = [
  "crash-feature-matcher",
  "witty-log-detection",
  "crash-report-generator",
]

function parseArgs(argv) {
  const options = {
    artifact: null,
    variant: null,
    python: process.env.PYTHON_BIN || "python3.11",
    report: null,
  }
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === "--artifact") {
      options.artifact = argv[++index]
    } else if (arg.startsWith("--artifact=")) {
      options.artifact = arg.slice("--artifact=".length)
    } else if (arg === "--variant") {
      options.variant = argv[++index]
    } else if (arg.startsWith("--variant=")) {
      options.variant = arg.slice("--variant=".length)
    } else if (arg === "--python") {
      options.python = argv[++index]
    } else if (arg.startsWith("--python=")) {
      options.python = arg.slice("--python=".length)
    } else if (arg === "--report") {
      options.report = argv[++index]
    } else if (arg.startsWith("--report=")) {
      options.report = arg.slice("--report=".length)
    } else {
      throw new Error(`unknown argument: ${arg}`)
    }
  }
  if (!options.artifact || !["online", "offline"].includes(options.variant)) {
    throw new Error("--artifact and --variant=online|offline are required")
  }
  options.artifact = resolve(options.artifact)
  options.report = resolve(options.report || `install-flow-${options.variant}.json`)
  if (!existsSync(options.artifact)) {
    throw new Error(`package artifact does not exist: ${options.artifact}`)
  }
  return options
}

function run(command, args, options = {}) {
  return execFileSync(command, args, {
    cwd: options.cwd,
    env: options.env || process.env,
    encoding: options.encoding,
    stdio: options.encoding ? ["ignore", "pipe", "inherit"] : "inherit",
    maxBuffer: 64 * 1024 * 1024,
  })
}

function pythonSnapshot(python, cwd, env) {
  const identity = run(python, [
    "-c",
    "import json,platform,sys; print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'version':platform.python_version()}))",
  ], { cwd, env, encoding: "utf8" }).trim()
  const packages = run(python, ["-m", "pip", "freeze", "--all"], {
    cwd,
    env,
    encoding: "utf8",
  }).trim().split("\n").filter(Boolean).sort()
  return { identity: JSON.parse(identity), packages }
}

function listBackups(configPath) {
  if (!existsSync(dirname(configPath))) {
    return []
  }
  const prefix = `${basename(configPath)}.shennong-backup-`
  return readdirSync(dirname(configPath))
    .filter((name) => name.startsWith(prefix))
    .sort()
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  const startedAt = Date.now()
  const workdir = mkdtempSync(join(tmpdir(), `shennong-real-${options.variant}-`))
  const projectDir = join(workdir, "consumer")
  const homeDir = join(workdir, "home")
  const configPath = join(homeDir, ".config", "opencode", "opencode.jsonc")
  const initialConfig = `{
  // Existing settings must survive Shennong registration.
  "plugin": ["existing-plugin"],
  "theme": "system"
}
`
  mkdirSync(projectDir, { recursive: true })
  mkdirSync(dirname(configPath), { recursive: true })
  writeFileSync(join(projectDir, "package.json"), `${JSON.stringify({
    name: `shennong-${options.variant}-install-verification`,
    private: true,
  }, null, 2)}\n`)
  writeFileSync(configPath, initialConfig)

  const environment = {
    ...process.env,
    HOME: homeDir,
    XDG_CONFIG_HOME: join(homeDir, ".config"),
    SHENNONG_OPENCODE_CONFIG: configPath,
    PYTHONNOUSERSITE: "1",
    PIP_DISABLE_PIP_VERSION_CHECK: "1",
  }

  let succeeded = false
  let serviceStarted = false
  try {
    const pythonBeforeInstall = pythonSnapshot(options.python, projectDir, environment)
    const installArgs = [
      "install",
      "--no-audit",
      "--no-fund",
      ...(options.variant === "offline"
        ? ["--offline", "--cache", join(workdir, "empty-npm-cache")]
        : []),
      options.artifact,
    ]
    run("npm", installArgs, { cwd: projectDir, env: environment })
    const pythonAfterInstall = pythonSnapshot(options.python, projectDir, environment)
    assert(
      JSON.stringify(pythonAfterInstall) === JSON.stringify(pythonBeforeInstall),
      "npm install changed the selected Python environment",
    )
    assert(readFileSync(configPath, "utf8") === initialConfig, "npm install changed OpenCode configuration")

    const packageName = `@openeuler/agent-shennong-crash-${options.variant}`
    const packageRoot = join(projectDir, "node_modules", ...packageName.split("/"))
    const packageCacheKey = packageName.replace(/^@/, "").replace(/\//g, "-")
    const venvCacheRoot = environment.SHENNONG_VENV_CACHE
      ? resolve(environment.SHENNONG_VENV_CACHE)
      : join(homeDir, ".cache", "witty-agents")
    const venvRoot = join(venvCacheRoot, packageCacheKey, "venvs")
    assert(existsSync(packageRoot), `installed package is missing: ${packageRoot}`)
    assert(!existsSync(join(packageRoot, ".venvs")), "npm install unexpectedly created Python environments")

    run("npm", [
      "exec", "--offline", "--", "shennong-setup", "install", `--python=${options.python}`,
    ], { cwd: projectDir, env: environment })
    serviceStarted = true

    const markerPath = join(venvRoot, "setup-complete.json")
    assert(existsSync(markerPath), "setup completion marker is missing")
    const markerBeforeRepeat = readFileSync(markerPath, "utf8")
    for (const name of VENV_NAMES) {
      assert(
        existsSync(join(venvRoot, name, "bin", "python")),
        `Python environment is missing: ${name}`,
      )
    }

    run("npm", [
      "exec", "--offline", "--", "shennong-setup", "install", `--python=${options.python}`,
    ], { cwd: projectDir, env: environment })
    assert(
      readFileSync(markerPath, "utf8") === markerBeforeRepeat,
      "repeated setup rewrote its completion marker",
    )

    const serviceStatus = JSON.parse(run("npm", [
      "exec", "--offline", "--", "shennong-setup", "status",
    ], { cwd: projectDir, env: environment, encoding: "utf8" }))
    assert(serviceStatus.state === "running", "witty-log-detection service is not running after setup")
    assert(serviceStatus.listening === true, "witty-log-detection service is not listening after setup")

    run("npm", [
      "exec", "--offline", "--", "shennong-configure", "install", "--target=opencode",
    ], {
      cwd: projectDir,
      env: environment,
    })
    const configAfterFirstConfigure = readFileSync(configPath, "utf8")
    const backupsAfterFirstConfigure = listBackups(configPath)
    assert(backupsAfterFirstConfigure.length === 1, "configure did not create exactly one backup")
    assert(
      readFileSync(join(dirname(configPath), backupsAfterFirstConfigure[0]), "utf8") === initialConfig,
      "configuration backup does not match the original file",
    )
    const parsedConfig = parse(configAfterFirstConfigure)
    assert(parsedConfig.theme === "system", "configure did not preserve unrelated settings")
    assert(parsedConfig.plugin.includes("existing-plugin"), "configure removed an unrelated plugin")
    const expectedPluginSpec = pathToFileURL(realpathSync(join(packageRoot, "dist", "index.js"))).href
    assert(parsedConfig.plugin.includes(expectedPluginSpec), "configure did not register the installed plugin path")
    assert(parsedConfig.mcp?.["crash-feature-matcher"]?.type === "local", "local MCP was not registered")
    assert(parsedConfig.mcp?.["witty-log-detection"]?.type === "remote", "remote MCP was not registered")

    run("npm", [
      "exec", "--offline", "--", "shennong-configure", "install", "--target=opencode",
    ], {
      cwd: projectDir,
      env: environment,
    })
    assert(readFileSync(configPath, "utf8") === configAfterFirstConfigure, "repeated configure changed configuration")
    assert(listBackups(configPath).length === 1, "repeated configure created another backup")

    run("npm", [
      "exec", "--offline", "--", "shennong-configure", "remove", "--target=opencode",
    ], { cwd: projectDir, env: environment })
    const configAfterRemove = readFileSync(configPath, "utf8")
    const parsedAfterRemove = parse(configAfterRemove)
    assert(parsedAfterRemove.theme === "system", "remove did not preserve unrelated settings")
    assert(parsedAfterRemove.plugin.includes("existing-plugin"), "remove deleted an unrelated plugin")
    assert(!parsedAfterRemove.plugin.includes(expectedPluginSpec), "remove left the Shennong plugin registration")
    assert(!Object.hasOwn(parsedAfterRemove.mcp || {}, "crash-feature-matcher"), "remove left local MCP registration")
    assert(!Object.hasOwn(parsedAfterRemove.mcp || {}, "witty-log-detection"), "remove left remote MCP registration")
    const backupsAfterRemove = listBackups(configPath)
    assert(backupsAfterRemove.length === 2, "remove did not create exactly one additional backup")

    run("npm", [
      "exec", "--offline", "--", "shennong-configure", "remove", "--target=opencode",
    ], { cwd: projectDir, env: environment })
    assert(readFileSync(configPath, "utf8") === configAfterRemove, "repeated remove changed configuration")
    assert(listBackups(configPath).length === 2, "repeated remove created another backup")

    const stopped = JSON.parse(run("npm", [
      "exec", "--offline", "--", "shennong-setup", "stop",
    ], { cwd: projectDir, env: environment, encoding: "utf8" }))
    serviceStarted = false
    assert(stopped.state === "stopped", "setup stop did not stop witty-log-detection")
    assert(stopped.listening === false, "witty-log-detection remains listening after stop")

    run("npm", ["uninstall", packageName, "--no-audit", "--no-fund"], {
      cwd: projectDir,
      env: environment,
    })
    assert(!existsSync(packageRoot), "npm uninstall left the package directory or package-local environments")

    const report = {
      status: "passed",
      variant: options.variant,
      artifact: options.artifact,
      packageName,
      python: pythonBeforeInstall.identity,
      networkIsolation: process.env.SHENNONG_NETWORK_ISOLATION || "none",
      venvs: VENV_NAMES,
      npmInstallPreservedPython: true,
      npmInstallPreservedConfig: true,
      setupIdempotent: true,
      configureBackupCount: 1,
      configureIdempotent: true,
      removeBackupCount: 1,
      removeIdempotent: true,
      mcpServiceStarted: true,
      mcpServiceStopped: true,
      npmUninstallRemovedPackage: true,
      durationSeconds: Number(((Date.now() - startedAt) / 1000).toFixed(3)),
    }
    mkdirSync(dirname(options.report), { recursive: true })
    writeFileSync(options.report, `${JSON.stringify(report, null, 2)}\n`)
    succeeded = true
    console.log(JSON.stringify(report, null, 2))
  } finally {
    if (serviceStarted) {
      try {
        run("npm", ["exec", "--offline", "--", "shennong-setup", "stop"], {
          cwd: projectDir,
          env: environment,
        })
      } catch (error) {
        console.error(`[verify-install] Failed to stop MCP service during cleanup: ${error.message}`)
      }
    }
    if (succeeded) {
      rmSync(workdir, { recursive: true, force: true })
    } else {
      console.error(`[verify-install] Failed workspace retained at ${workdir}`)
    }
  }
}

try {
  main()
} catch (error) {
  console.error(`[verify-install] ${error.message}`)
  process.exit(1)
}
