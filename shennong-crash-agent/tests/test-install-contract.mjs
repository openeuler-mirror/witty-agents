#!/usr/bin/env node

import { execFileSync, spawnSync } from "node:child_process"
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { basename, dirname, join, resolve } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import { parse } from "jsonc-parser"

const TEST_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = resolve(TEST_DIR, "..")
const ARTIFACT_DIR = join(PROJECT_ROOT, "artifacts")
const sandbox = mkdtempSync(join(tmpdir(), "shennong-install-contract-"))
const TEST_VARIANTS = (process.env.SHENNONG_TEST_VARIANTS || "online,offline")
  .split(",")
  .map((variant) => variant.trim())
  .filter(Boolean)

if (TEST_VARIANTS.length === 0 || TEST_VARIANTS.some((variant) => !["online", "offline"].includes(variant))) {
  throw new Error("SHENNONG_TEST_VARIANTS must contain online and/or offline")
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

function readdirRecursive(root, prefix = "") {
  const output = []
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const relativePath = join(prefix, entry.name)
    if (entry.isDirectory()) {
      output.push(...readdirRecursive(join(root, entry.name), relativePath))
    } else if (entry.isFile()) {
      output.push(relativePath)
    }
  }
  return output
}

function packageArtifact(variant) {
  const report = JSON.parse(readFileSync(join(ARTIFACT_DIR, `${variant}-package-report.json`), "utf8"))
  return { report, tgz: join(ARTIFACT_DIR, report.filename) }
}

async function installVariant(variant, configPath, environment) {
  const { report, tgz } = packageArtifact(variant)
  const project = join(sandbox, `consumer-${variant}`)
  mkdirSync(project, { recursive: true })
  writeFileSync(join(project, "package.json"), `${JSON.stringify({ name: `consumer-${variant}`, private: true }, null, 2)}\n`)
  const configBeforeInstall = readFileSync(configPath, "utf8")
  const installArgs = [
    "install",
    "--foreground-scripts",
    "--no-audit",
    "--no-fund",
    ...(variant === "offline"
      ? ["--offline", "--cache", join(sandbox, "empty-offline-npm-cache")]
      : []),
    tgz,
  ]
  execFileSync("npm", installArgs, { cwd: project, stdio: "inherit", env: environment })
  assert(
    readFileSync(configPath, "utf8") === configBeforeInstall,
    `${variant}: npm install unexpectedly changed OpenCode configuration`,
  )

  const packageRoot = join(project, "node_modules", ...report.packageName.split("/"))
  assert(existsSync(packageRoot), `${variant}: installed package directory is missing`)
  assert(!existsSync(join(packageRoot, ".venvs")), `${variant}: npm install unexpectedly created .venvs`)
  assert(!existsSync(join(project, ".venvs")), `${variant}: npm install polluted consumer project with .venvs`)
  assert(existsSync(join(packageRoot, "package-content-manifest.json")), `${variant}: content manifest is missing`)
  const packagedDatabases = readdirRecursive(packageRoot).filter((path) => (
    path.endsWith(".db") || path.endsWith(".db-wal") || path.endsWith(".db-shm")
  ))
  assert(
    packagedDatabases.length === 0,
    `${variant}: runtime databases leaked into package: ${packagedDatabases.join(", ")}`,
  )

  const pluginPath = join(packageRoot, "dist", "index.js")
  execFileSync(process.execPath, ["--check", pluginPath], { cwd: project, stdio: "inherit" })
  const pluginModule = await import(`${pathToFileURL(pluginPath).href}?contract=${Date.now()}`)
  assert(typeof pluginModule.default === "function", `${variant}: default plugin export is missing`)
  const hooks = await pluginModule.default({})
  const pluginConfig = {}
  await hooks.config(pluginConfig)
  assert(pluginConfig.agent?.shennong?.mode === "primary", `${variant}: Shennong primary agent was not registered`)

  const setupBin = join(project, "node_modules", ".bin", "shennong-setup")
  const configureBin = join(project, "node_modules", ".bin", "shennong-configure")
  assert(existsSync(setupBin), `${variant}: shennong-setup bin link is missing`)
  assert(existsSync(configureBin), `${variant}: shennong-configure bin link is missing`)
  execFileSync("npm", ["exec", "--offline", "--", "shennong-setup", "--help"], {
    cwd: project,
    stdio: "ignore",
    env: environment,
  })
  if (variant === "offline" && report.contentComplete === false) {
    const check = spawnSync("npm", ["exec", "--offline", "--", "shennong-setup", "check"], {
      cwd: project,
      encoding: "utf8",
      env: environment,
    })
    assert(check.status !== 0, "offline: incomplete content was incorrectly reported ready")
    assert(
      check.stderr.includes("package content is incomplete"),
      `offline: incomplete-content failure was unclear: ${check.stderr}`,
    )
  }
  return { packageName: report.packageName, packageRoot, project, report }
}

function listConfigBackups(configPath) {
  const prefix = `${basename(configPath)}.shennong-backup-`
  return readdirSync(dirname(configPath))
    .filter((name) => name.startsWith(prefix))
    .map((name) => join(dirname(configPath), name))
    .sort()
}

function exerciseConfigure(installation, configPath, environment) {
  const before = readFileSync(configPath, "utf8")
  const backupsBefore = listConfigBackups(configPath)
  const command = ["exec", "--offline", "--", "shennong-configure"]
  execFileSync("npm", command, {
    cwd: installation.project,
    stdio: "inherit",
    env: environment,
  })

  const after = readFileSync(configPath, "utf8")
  const config = parse(after, [], { allowTrailingComma: true, disallowComments: false })
  assert(after.includes("keep-this-comment"), "configure: OpenCode JSONC comment was removed")
  assert(config.custom?.token === "keep-me", "configure: unrelated OpenCode config was changed")
  assert(config.plugin.includes("other-plugin"), "configure: unrelated OpenCode plugin was removed")
  assert(
    config.plugin.filter((name) => name === installation.packageName).length === 1,
    `configure: ${installation.packageName} is missing or duplicated`,
  )

  const backupsAfter = listConfigBackups(configPath)
  assert(
    backupsAfter.length === backupsBefore.length + 1,
    "configure: changing an existing config did not create exactly one backup",
  )
  const createdBackup = backupsAfter.find((path) => !backupsBefore.includes(path))
  assert(readFileSync(createdBackup, "utf8") === before, "configure: backup is not byte-identical to the previous config")

  execFileSync("npm", command, {
    cwd: installation.project,
    stdio: "inherit",
    env: environment,
  })
  assert(readFileSync(configPath, "utf8") === after, "configure: repeated run changed config bytes")
  assert(
    listConfigBackups(configPath).length === backupsAfter.length,
    "configure: repeated no-op run created an unnecessary backup",
  )
}

function exerciseExplicitSetup(installation, environment) {
  const offline = installation.report.variant === "offline"
  const pythonInfo = installation.report.wheelPlatform || {
    python: "3.11.9",
    implementation: "CPython",
    system: "linux",
    machine: "x86_64",
    cache_tag: "cpython-311",
    sysconfig_platform: "linux-x86_64",
    soabi: "cpython-311-x86_64-linux-gnu",
    libc: ["glibc", "2.28"],
  }
  const pythonInfoJson = JSON.stringify(pythonInfo)
  const setupLog = join(sandbox, "setup-python-calls.log")
  const setupPython = join(sandbox, "setup-python")
  writeFileSync(setupLog, "")
  writeFileSync(setupPython, `#!/bin/sh
printf '%s\n' "$*" >> "$SETUP_PYTHON_LOG"
if [ "$1" = "-c" ]; then
  case "$2" in
    *sys.prefix*) exit 0 ;;
    *importlib.import_module*)
      if [ "$SETUP_FAIL_IMPORT" = "1" ]; then exit 42; fi
      exit 0
      ;;
    *) printf '%s\n' '${pythonInfoJson}' ;;
  esac
elif [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  mkdir -p "$3/bin"
  cp "$0" "$3/bin/python"
  chmod 755 "$3/bin/python"
elif [ "$1" = "src/server.py" ]; then
  exec "$SHENNONG_FAKE_NODE" -e 'require("node:http").createServer((request, response) => { response.writeHead(200, {"content-type": "text/event-stream"}); response.write("event: ready\\ndata: ok\\n\\n") }).listen(12144, "127.0.0.1")' src/server.py
fi
exit 0
`)
  chmodSync(setupPython, 0o755)
  const setupEnvironment = {
    ...environment,
    SETUP_PYTHON_LOG: setupLog,
    SHENNONG_FAKE_NODE: process.execPath,
    SHENNONG_MCP_START_TIMEOUT_MS: "5000",
  }
  const command = [
    "exec", "--offline", "--", "shennong-setup", "install", `--python=${setupPython}`,
  ]
  execFileSync("npm", command, {
    cwd: installation.project,
    stdio: "inherit",
    env: setupEnvironment,
  })
  const venvRoot = join(installation.packageRoot, ".venvs")
  for (const name of ["crash-feature-matcher", "witty-log-detection", "crash-report-generator"]) {
    assert(existsSync(join(venvRoot, name, "bin", "python")), `setup: missing venv ${name}`)
  }
  assert(existsSync(join(venvRoot, "setup-complete.json")), "setup: completion marker is missing")
  const marker = JSON.parse(readFileSync(join(venvRoot, "setup-complete.json"), "utf8"))
  assert(/^[a-f0-9]{64}$/.test(marker.contentManifestSha256), "setup: content manifest digest is missing")
  if (offline) {
    assert(/^[a-f0-9]{64}$/.test(marker.wheelManifestSha256), "offline setup: wheel manifest digest is missing")
  } else {
    assert(marker.wheelManifestSha256 === null, "online setup: unexpected wheel manifest digest")
  }
  const firstCalls = readFileSync(setupLog, "utf8")
  assert(firstCalls.includes("-m venv"), "setup: Python venv creation was not invoked")
  assert(!firstCalls.includes(".venvs.tmp-"), "setup: venv was created in a movable temporary path")
  assert(firstCalls.includes("-m pip install"), "setup: pip install was not invoked")
  assert(firstCalls.includes("-m pip check"), "setup: pip check was not invoked")
  if (offline) {
    const installCalls = firstCalls.split("\n").filter((line) => line.includes("-m pip install"))
    assert(installCalls.length >= 3, "offline setup: expected pip install calls were not recorded")
    for (const call of installCalls) {
      assert(call.includes("--no-index"), `offline setup: pip install can reach an index: ${call}`)
      assert(call.includes("--find-links"), `offline setup: bundled wheelhouse was not selected: ${call}`)
      assert(!/https?:\/\//.test(call), `offline setup: pip install contains a remote URL: ${call}`)
    }
  }
  for (const moduleName of ["crash_matcher", "faiss", "paddleocr", "jsonschema"]) {
    assert(firstCalls.includes(`importlib.import_module(\"${moduleName}\")`), `setup: ${moduleName} import was not verified`)
  }

  execFileSync("npm", command, {
    cwd: installation.project,
    stdio: "inherit",
    env: setupEnvironment,
  })
  const secondCalls = readFileSync(setupLog, "utf8")
  assert(
    secondCalls.split("-m pip install").length === firstCalls.split("-m pip install").length,
    "setup: idempotent rerun unexpectedly invoked pip again",
  )
  assert(
    secondCalls.split("-m pip check").length > firstCalls.split("-m pip check").length,
    "setup: idempotent rerun did not revalidate installed dependencies",
  )

  const status = JSON.parse(execFileSync("npm", ["exec", "--offline", "--", "shennong-setup", "status"], {
    cwd: installation.project,
    encoding: "utf8",
    env: setupEnvironment,
  }))
  assert(status.state === "running", `setup: witty-log-detection is not running: ${status.state}`)
  assert(status.tracked === true, "setup: witty-log-detection PID is not tracked")

  const stopped = JSON.parse(execFileSync("npm", ["exec", "--offline", "--", "shennong-setup", "stop"], {
    cwd: installation.project,
    encoding: "utf8",
    env: setupEnvironment,
  }))
  assert(stopped.action === "stopped", `setup: MCP stop command did not stop the service: ${stopped.action}`)

  const markerPath = join(venvRoot, "setup-complete.json")
  const markerBeforeFailedForce = readFileSync(markerPath, "utf8")
  const failedForce = spawnSync("npm", [...command, "--force"], {
    cwd: installation.project,
    encoding: "utf8",
    env: { ...setupEnvironment, SETUP_FAIL_IMPORT: "1" },
  })
  assert(failedForce.status !== 0, "setup: injected force reinstall failure unexpectedly passed")
  assert(
    readFileSync(markerPath, "utf8") === markerBeforeFailedForce,
    "setup: failed force reinstall did not restore the previous completion marker",
  )
  assert(
    readdirSync(installation.packageRoot).every((name) => !name.startsWith(".venvs.backup-")),
    "setup: failed force reinstall left a backup directory after restoration",
  )
}

try {
  const home = join(sandbox, "home")
  const fakeBin = join(sandbox, "fakebin")
  const pythonLog = join(sandbox, "python-calls.log")
  const configPath = join(home, ".config", "opencode", "opencode.jsonc")
  mkdirSync(dirname(configPath), { recursive: true })
  mkdirSync(fakeBin, { recursive: true })
  writeFileSync(configPath, `{
  // keep-this-comment
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["other-plugin", "shennong-crash-agent-online", "@openeuler/agent-shennong-crash-online@0.10.2",],
  "custom": { "token": "keep-me", },
}\n`)
  writeFileSync(pythonLog, "")

  const trap = join(fakeBin, "python-trap")
  writeFileSync(trap, "#!/bin/sh\nprintf '%s\\n' \"$0 $*\" >> \"$PYTHON_TRAP_LOG\"\nexit 97\n")
  chmodSync(trap, 0o755)
  for (const name of ["python", "python3", "python3.11", "python3.12", "python3.13", "pip", "pip3"]) {
    symlinkSync("python-trap", join(fakeBin, name))
  }

  const environment = {
    ...process.env,
    HOME: home,
    PATH: `${fakeBin}:${process.env.PATH}`,
    PYTHON_TRAP_LOG: pythonLog,
    SHENNONG_OPENCODE_CONFIG: configPath,
    npm_config_audit: "false",
    npm_config_fund: "false",
  }

  const configuredPackages = []
  if (TEST_VARIANTS.includes("online")) {
    const online = await installVariant("online", configPath, environment)
    assert(readFileSync(pythonLog, "utf8") === "", "online npm install or --help invoked Python/pip")
    exerciseExplicitSetup(online, environment)
    assert(readFileSync(pythonLog, "utf8") === "", "setup used an implicit Python instead of --python")
    exerciseConfigure(online, configPath, environment)
    assert(readFileSync(pythonLog, "utf8") === "", "configure unexpectedly invoked Python/pip")
    configuredPackages.push(online.packageName)
  }

  if (TEST_VARIANTS.includes("offline")) {
    const offline = await installVariant("offline", configPath, environment)
    assert(readFileSync(pythonLog, "utf8") === "", "offline npm install or --help invoked Python/pip")
    if (offline.report.contentComplete && offline.report.pythonDependencyClosureVerified) {
      exerciseExplicitSetup(offline, environment)
    }
    exerciseConfigure(offline, configPath, environment)
    assert(readFileSync(pythonLog, "utf8") === "", "offline configure unexpectedly invoked Python/pip")
    configuredPackages.push(offline.packageName)
  }

  const finalConfig = parse(readFileSync(configPath, "utf8"), [], {
    allowTrailingComma: true,
    disallowComments: false,
  })
  const finalPackage = configuredPackages.at(-1)
  for (const packageName of configuredPackages.slice(0, -1)) {
    assert(!finalConfig.plugin.includes(packageName), `configure did not replace previous package ${packageName}`)
  }
  assert(finalConfig.plugin.filter((name) => name === finalPackage).length === 1, "final plugin registration is not unique")
  console.log("install contract: PASS")
} finally {
  rmSync(sandbox, { recursive: true, force: true })
}
