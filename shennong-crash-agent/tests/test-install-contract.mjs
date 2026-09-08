#!/usr/bin/env node

import { execFileSync, spawn, spawnSync } from "node:child_process"
import { createHash } from "node:crypto"
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
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
const CONFIGURE_ONLY = process.env.SHENNONG_TEST_CONFIGURE_ONLY === "1"

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
  const installResult = spawnSync("npm", installArgs, {
    cwd: project,
    encoding: "utf8",
    env: environment,
  })
  process.stdout.write(installResult.stdout || "")
  process.stderr.write(installResult.stderr || "")
  assert(installResult.status === 0, `${variant}: npm install failed`)
  assert(
    `${installResult.stdout}\n${installResult.stderr}`.includes("npm exec -- shennong-setup install"),
    `${variant}: npm install did not show the setup next-step hint`,
  )
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
  for (const path of [
    "lib/configure/backup.mjs",
    "lib/configure/common.mjs",
    "lib/configure/adapters/index.mjs",
    "lib/configure/adapters/opencode.mjs",
    "lib/configure/adapters/dsh.mjs",
    "frameworks/dsh/package.json.template",
    "frameworks/dsh/cordis.patch.yml.template",
    "frameworks/dsh/shennong-persona.md",
  ]) {
    assert(existsSync(join(packageRoot, path)), `${variant}: framework adapter file is missing: ${path}`)
  }
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
  return {
    packageName: report.packageName,
    packageRoot,
    pluginSpec: pathToFileURL(realpathSync(pluginPath)).href,
    project,
    report,
  }
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
    config.plugin.filter((name) => name === installation.pluginSpec).length === 1,
    `configure: ${installation.pluginSpec} is missing or duplicated`,
  )
  assert(!config.plugin.includes(installation.packageName), "configure: package name was registered instead of local entry")
  assert(after.includes("keep-mcp-comment"), "configure: unrelated MCP comment was removed")
  assert(config.mcp?.["other-mcp"]?.enabled === false, "configure: unrelated MCP was changed")
  assert(
    JSON.stringify(config.mcp?.["crash-feature-matcher"]) === JSON.stringify({
      type: "local",
      command: [
        "bash",
        realpathSync(join(installation.packageRoot, "skills", "crash-feature-matcher", "run_mcp.sh")),
      ],
      enabled: true,
      timeout: 30000,
    }),
    "configure: crash-feature-matcher MCP registration is incorrect",
  )
  assert(
    JSON.stringify(config.mcp?.["witty-log-detection"]) === JSON.stringify({
      type: "remote",
      url: "http://127.0.0.1:12144/sse",
      enabled: true,
      timeout: 30000,
    }),
    "configure: witty-log-detection MCP registration is incorrect",
  )
  assert(!Object.hasOwn(config.mcp, "crash_feature_matcher"), "configure: legacy crash MCP remains")
  assert(!Object.hasOwn(config.mcp, "witty_log_detection"), "configure: legacy witty MCP remains")

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

function exerciseFrameworkAdapterBoundary(installation, configPath, environment) {
  const before = readFileSync(configPath, "utf8")
  const status = spawnSync(
    "npm",
    ["exec", "--offline", "--", "shennong-configure", "status", "--target", "dsh"],
    {
      cwd: installation.project,
      encoding: "utf8",
      env: environment,
    },
  )
  assert(status.status === 0, `DSH adapter status failed: ${status.stderr}`)
  assert(status.stdout.includes('"framework": "dsh"'), "DSH adapter status did not identify the framework")
  assert(status.stdout.includes('"supported": false'), "DSH adapter did not report its gated state")
  assert(status.stdout.includes('"templatesReady": true'), "DSH adapter templates are incomplete")
  assert(readFileSync(configPath, "utf8") === before, "DSH status unexpectedly changed OpenCode configuration")

  const install = spawnSync(
    "npm",
    ["exec", "--offline", "--", "shennong-configure", "install", "--target", "dsh"],
    {
      cwd: installation.project,
      encoding: "utf8",
      env: environment,
    },
  )
  assert(install.status !== 0, "gated DSH install unexpectedly succeeded")
  assert(
    install.stderr.includes("Streamable HTTP /mcp"),
    `gated DSH install failure did not explain the transport boundary: ${install.stderr}`,
  )
  assert(readFileSync(configPath, "utf8") === before, "gated DSH install changed OpenCode configuration")
}

function exerciseRemove(configPath, project, environment) {
  const before = readFileSync(configPath, "utf8")
  const backupsBefore = listConfigBackups(configPath)
  const command = ["exec", "--offline", "--", "shennong-configure", "remove"]
  execFileSync("npm", command, { cwd: project, stdio: "inherit", env: environment })

  const after = readFileSync(configPath, "utf8")
  const config = parse(after, [], { allowTrailingComma: true, disallowComments: false })
  assert(after.includes("keep-this-comment"), "configure remove: OpenCode JSONC comment was removed")
  assert(config.custom?.token === "keep-me", "configure remove: unrelated OpenCode config was changed")
  assert(config.plugin.includes("other-plugin"), "configure remove: unrelated plugin was removed")
  assert(after.includes("keep-mcp-comment"), "configure remove: unrelated MCP comment was removed")
  assert(config.mcp?.["other-mcp"]?.enabled === false, "configure remove: unrelated MCP was changed")
  assert(!Object.hasOwn(config.mcp || {}, "crash-feature-matcher"), "configure remove: crash MCP remains")
  assert(!Object.hasOwn(config.mcp || {}, "witty-log-detection"), "configure remove: witty MCP remains")
  assert(
    config.plugin.every((plugin) => !plugin.includes("shennong-crash") && !plugin.includes("agent-shennong-crash")),
    "configure remove: a Shennong registration remains",
  )
  const backupsAfter = listConfigBackups(configPath)
  assert(backupsAfter.length === backupsBefore.length + 1, "configure remove: backup was not created")
  const createdBackup = backupsAfter.find((path) => !backupsBefore.includes(path))
  assert(readFileSync(createdBackup, "utf8") === before, "configure remove: backup is not byte-identical")

  execFileSync("npm", command, { cwd: project, stdio: "inherit", env: environment })
  assert(readFileSync(configPath, "utf8") === after, "configure remove: repeated run changed config")
  assert(
    listConfigBackups(configPath).length === backupsAfter.length,
    "configure remove: repeated no-op run created a backup",
  )
}

async function exerciseExplicitSetup(installation, environment) {
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
    *platform.python_version*) printf '%s\n' '${pythonInfoJson}' ;;
    *ctypes.CDLL*)
      if [ "$SETUP_MISSING_RUNTIME" = "1" ]; then
        printf '%s\n' '["libGL.so.1"]'
      else
        printf '%s\n' '[]'
      fi
      ;;
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

  // online 包 setup 需要从网络下载 OCR 模型；用本地 HTTP server 提供仓库内的
  // 真实模型文件，保持契约测试全程离线可运行。
  let ocrServer = null
  if (!offline) {
    const modelSrc = join(PROJECT_ROOT, "skills", "witty-log-detection", "src", "model", "ocr")
    const serveRoot = join(sandbox, "ocr-model-http-root")
    for (const [relative, model] of [
      ["PP-OCRv4/chinese/ch_PP-OCRv4_det_infer.tar", "ch_PP-OCRv4_det_infer"],
      ["PP-OCRv4/chinese/ch_PP-OCRv4_rec_infer.tar", "ch_PP-OCRv4_rec_infer"],
      ["dygraph_v2.0/ch/ch_ppocr_mobile_v2.0_cls_infer.tar", "ch_ppocr_mobile_v2.0_cls_infer"],
    ]) {
      const tarPath = join(serveRoot, ...relative.split("/"))
      mkdirSync(dirname(tarPath), { recursive: true })
      execFileSync("tar", ["cf", tarPath, "-C", modelSrc, model])
    }
    const serverScript = join(sandbox, "ocr-model-server.mjs")
    writeFileSync(serverScript, `import { createReadStream, existsSync } from "node:fs";
import { join, normalize } from "node:path";
import { createServer } from "node:http";
const root = process.argv[2];
const server = createServer((request, response) => {
  const path = join(root, normalize(request.url.replace(/^\\/+/, "")));
  if (request.url.includes("..") || !existsSync(path)) {
    response.writeHead(404);
    response.end();
    return;
  }
  response.writeHead(200, { "content-type": "application/x-tar" });
  createReadStream(path).pipe(response);
});
server.listen(0, "127.0.0.1", () => {
  process.stdout.write(String(server.address().port));
});
`
    )
    ocrServer = spawn(process.execPath, [serverScript, serveRoot], {
      stdio: ["ignore", "pipe", "inherit"],
    })
    const port = await new Promise((resolvePort, rejectPort) => {
      let output = ""
      ocrServer.stdout.on("data", (chunk) => {
        output += chunk
        const parsed = Number.parseInt(output, 10)
        if (Number.isInteger(parsed)) {
          resolvePort(parsed)
        }
      })
      ocrServer.on("exit", () => rejectPort(new Error("OCR model server exited early")))
    })
    setupEnvironment.SHENNONG_OCR_MODELS_BASE_URL = `http://127.0.0.1:${port}`
  }
  const command = [
    "exec", "--offline", "--", "shennong-setup", "install", `--python=${setupPython}`,
  ]
  const missingRuntime = spawnSync("npm", [
    "exec", "--offline", "--", "shennong-setup", "check", `--python=${setupPython}`,
  ], {
    cwd: installation.project,
    encoding: "utf8",
    env: { ...setupEnvironment, SETUP_MISSING_RUNTIME: "1" },
  })
  assert(missingRuntime.status !== 0, "setup: missing Linux runtime library was not rejected")
  assert(
    `${missingRuntime.stdout}\n${missingRuntime.stderr}`.includes("sudo dnf install -y libglvnd-glx"),
    "setup: missing Linux runtime library did not produce an actionable openEuler command",
  )
  assert(
    !readFileSync(setupLog, "utf8").includes("-m pip install"),
    "setup: Python dependencies were installed before the Linux runtime preflight passed",
  )
  execFileSync("npm", command, {
    cwd: installation.project,
    stdio: "inherit",
    env: setupEnvironment,
  })
  const venvKey = installation.packageName
    .replace(/^@/, "")
    .replaceAll("/", "-")
  const venvRoot = join(environment.HOME, ".cache", "witty-agents", venvKey, "venvs")
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
  const ocrModelsRoot = join(environment.HOME, ".cache", "witty-agents", venvKey, "ocr-models")
  if (offline) {
    assert(!existsSync(ocrModelsRoot), "offline setup: unexpectedly downloaded OCR models")
  } else {
    for (const [name, paramsSha256] of [
      ["ch_PP-OCRv4_det_infer", "49ee815e30cff43cb1057d33bf0d94193e4d4f1ae28451cad15b40be830df915"],
      ["ch_PP-OCRv4_rec_infer", "a6dbfa63e7ee161688523c954e9e293f77dc24044db81e836ff9c7f103fd191a"],
      ["ch_ppocr_mobile_v2.0_cls_infer", "d1efda1b80e174b4fcb168a035ac96c1af4938892bd86a55f300a6027105d08c"],
    ]) {
      const params = join(ocrModelsRoot, name, "inference.pdiparams")
      assert(existsSync(params), `online setup: OCR model missing: ${name}`)
      assert(
        createHash("sha256").update(readFileSync(params)).digest("hex") === paramsSha256,
        `online setup: OCR model failed sha256 verification: ${name}`
      )
      assert(
        readdirSync(join(ocrModelsRoot, name)).every((file) => !file.endsWith(".tar")),
        `online setup: OCR model directory contains download residue: ${name}`
      )
    }
  }
  const firstCalls = readFileSync(setupLog, "utf8")
  assert(firstCalls.includes("-m venv"), "setup: Python venv creation was not invoked")
  assert(firstCalls.includes(venvRoot), "setup: venv was not created in the user cache directory")
  assert(!firstCalls.includes(join(installation.packageRoot, ".venvs")), "setup: venv was created inside the package directory")
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
  if (!offline) {
    for (const name of ["ch_PP-OCRv4_det_infer", "ch_PP-OCRv4_rec_infer", "ch_ppocr_mobile_v2.0_cls_infer"]) {
      assert(existsSync(join(ocrModelsRoot, name, "inference.pdiparams")), `online setup: idempotent rerun removed OCR model: ${name}`)
    }
    ocrServer.kill()
  }

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
    readdirSync(dirname(venvRoot)).every((name) => !name.startsWith("venvs.backup-")),
    "setup: failed force reinstall left a backup directory after restoration",
  )
  assert(
    readdirSync(installation.packageRoot).every((name) => !name.startsWith(".venvs")),
    "setup: setup wrote venv state inside the package directory",
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
  "mcp": {
    // keep-mcp-comment
    "other-mcp": { "type": "remote", "url": "https://example.invalid/mcp", "enabled": false, },
    "crash_feature_matcher": { "type": "local", "command": ["false"], },
    "witty_log_detection": { "type": "remote", "url": "http://127.0.0.1:9/sse", },
  },
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

  const configuredInstallations = []
  if (TEST_VARIANTS.includes("online")) {
    const online = await installVariant("online", configPath, environment)
    assert(readFileSync(pythonLog, "utf8") === "", "online npm install or --help invoked Python/pip")
    if (!CONFIGURE_ONLY) {
      await exerciseExplicitSetup(online, environment)
    }
    assert(readFileSync(pythonLog, "utf8") === "", "setup used an implicit Python instead of --python")
    exerciseConfigure(online, configPath, environment)
    exerciseFrameworkAdapterBoundary(online, configPath, environment)
    assert(readFileSync(pythonLog, "utf8") === "", "configure unexpectedly invoked Python/pip")
    configuredInstallations.push(online)
  }

  if (TEST_VARIANTS.includes("offline")) {
    const offline = await installVariant("offline", configPath, environment)
    assert(readFileSync(pythonLog, "utf8") === "", "offline npm install or --help invoked Python/pip")
    if (offline.report.contentComplete && offline.report.pythonDependencyClosureVerified) {
      await exerciseExplicitSetup(offline, environment)
    }
    exerciseConfigure(offline, configPath, environment)
    assert(readFileSync(pythonLog, "utf8") === "", "offline configure unexpectedly invoked Python/pip")
    configuredInstallations.push(offline)
  }

  const finalConfig = parse(readFileSync(configPath, "utf8"), [], {
    allowTrailingComma: true,
    disallowComments: false,
  })
  const finalInstallation = configuredInstallations.at(-1)
  for (const installation of configuredInstallations.slice(0, -1)) {
    assert(!finalConfig.plugin.includes(installation.pluginSpec), `configure did not replace ${installation.pluginSpec}`)
  }
  assert(
    finalConfig.plugin.filter((name) => name === finalInstallation.pluginSpec).length === 1,
    "final local plugin registration is not unique",
  )
  assert(finalConfig.mcp?.["crash-feature-matcher"]?.type === "local", "final crash MCP is missing")
  assert(finalConfig.mcp?.["witty-log-detection"]?.type === "remote", "final witty MCP is missing")
  exerciseRemove(configPath, finalInstallation.project, environment)
  console.log("install contract: PASS")
} finally {
  rmSync(sandbox, { recursive: true, force: true })
}
