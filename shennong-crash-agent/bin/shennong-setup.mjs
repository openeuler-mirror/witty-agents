#!/usr/bin/env node

import { createHash } from "node:crypto"
import { execFileSync } from "node:child_process"
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  readdirSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { homedir } from "node:os"
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path"
import { fileURLToPath } from "node:url"
import { serviceStatus, startServices, stopServices } from "../lib/mcp-services.mjs"

const BIN_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = resolve(BIN_DIR, "..")
const VARIANT_FILE = join(PROJECT_ROOT, "package-variant.json")
const CONTENT_MANIFEST_FILE = join(PROJECT_ROOT, "package-content-manifest.json")
const WHEEL_MANIFEST_FILE = join(PROJECT_ROOT, "python-wheel-manifest.json")

export function venvsDirForPackage(packageName) {
  const key = String(packageName).replace(/^@/, "").replace(/\//g, "-")
  const cacheRoot = process.env.SHENNONG_VENV_CACHE
    ? resolve(process.env.SHENNONG_VENV_CACHE)
    : join(homedir(), ".cache", "witty-agents")
  return join(cacheRoot, key, "venvs")
}

export function ocrModelsDirForPackage(packageName) {
  const key = String(packageName).replace(/^@/, "").replace(/\//g, "-")
  const cacheRoot = process.env.SHENNONG_VENV_CACHE
    ? resolve(process.env.SHENNONG_VENV_CACHE)
    : join(homedir(), ".cache", "witty-agents")
  return join(cacheRoot, key, "ocr-models")
}

// online 包不含 OCR 模型（体积考虑），setup 时从 PaddleOCR 官方源自动下载到用户缓存目录。
// paramsSha256 与仓库 LFS 指针（git show HEAD:...inference.pdiparams）保持一致。
// SHENNONG_OCR_MODELS_BASE_URL 可覆盖下载源（测试用本地源验证下载逻辑）。
const OCR_MODELS = [
  {
    name: "ch_PP-OCRv4_det_infer",
    path: "/PP-OCRv4/chinese/ch_PP-OCRv4_det_infer.tar",
    paramsSha256:
      "49ee815e30cff43cb1057d33bf0d94193e4d4f1ae28451cad15b40be830df915",
  },
  {
    name: "ch_PP-OCRv4_rec_infer",
    path: "/PP-OCRv4/chinese/ch_PP-OCRv4_rec_infer.tar",
    paramsSha256:
      "a6dbfa63e7ee161688523c954e9e293f77dc24044db81e836ff9c7f103fd191a",
  },
  {
    name: "ch_ppocr_mobile_v2.0_cls_infer",
    path: "/dygraph_v2.0/ch/ch_ppocr_mobile_v2.0_cls_infer.tar",
    paramsSha256:
      "d1efda1b80e174b4fcb168a035ac96c1af4938892bd86a55f300a6027105d08c",
  },
]

function ocrModelVerified(modelDir, paramsSha256) {
  for (const file of [
    "inference.pdiparams",
    "inference.pdiparams.info",
    "inference.pdmodel",
  ]) {
    if (!existsSync(join(modelDir, file))) {
      return false
    }
  }
  return sha256(join(modelDir, "inference.pdiparams")) === paramsSha256
}

async function ensureOcrModels(metadata) {
  if (metadata.variant !== "online") {
    return
  }
  const root = ocrModelsDirForPackage(metadata.packageName)
  for (const model of OCR_MODELS) {
    const dest = join(root, model.name)
    if (ocrModelVerified(dest, model.paramsSha256)) {
      console.log(`[shennong-setup] OCR model already present: ${model.name}`)
      continue
    }
    const tmp = `${dest}.download-${process.pid}-${Date.now()}`
    try {
      const baseUrl = (
        process.env.SHENNONG_OCR_MODELS_BASE_URL ||
        "https://paddleocr.bj.bcebos.com"
      ).replace(/\/$/, "")
      console.log(`[shennong-setup] Downloading OCR model: ${model.name}`)
      const response = await fetch(`${baseUrl}${model.path}`)
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      mkdirSync(tmp, { recursive: true })
      const tarPath = join(tmp, "model.tar")
      writeFileSync(tarPath, Buffer.from(await response.arrayBuffer()))
      execFileSync("tar", ["xf", tarPath, "-C", tmp], { cwd: tmp })
      const extracted = join(tmp, model.name)
      if (!ocrModelVerified(extracted, model.paramsSha256)) {
        throw new Error("downloaded model failed sha256 verification")
      }
      mkdirSync(dirname(dest), { recursive: true })
      rmSync(dest, { recursive: true, force: true })
      renameSync(extracted, dest)
      console.log(`[shennong-setup] OCR model downloaded: ${model.name}`)
    } catch (error) {
      console.warn(
        `[shennong-setup] WARNING: failed to download OCR model ${model.name} ` +
          `(${error.message}); local OCR will be unavailable. ` +
          `Rerun 'shennong-setup install' when the network is reachable.`
      )
    } finally {
      rmSync(tmp, { recursive: true, force: true })
    }
  }
}

const PACKAGE_NAME = JSON.parse(
  readFileSync(join(PROJECT_ROOT, "package.json"), "utf8")
).name
const VENV_DIR = venvsDirForPackage(PACKAGE_NAME)

const VENVS = [
  {
    name: "crash-feature-matcher",
    requirements: join(PROJECT_ROOT, "skills", "crash-feature-matcher", "requirements.txt"),
    pyproject: join(PROJECT_ROOT, "skills", "crash-feature-matcher", "pyproject.toml"),
    editable: true,
    imports: ["crash_matcher", "fastmcp", "pydantic"],
  },
  {
    name: "witty-log-detection",
    requirements: join(PROJECT_ROOT, "skills", "witty-log-detection", "src", "requirements.txt"),
    pyproject: join(PROJECT_ROOT, "skills", "witty-log-detection", "src", "pyproject.toml"),
    editable: false,
    imports: ["numpy", "sklearn", "faiss", "cv2", "paddle", "paddleocr"],
  },
  {
    name: "crash-report-generator",
    requirements: join(PROJECT_ROOT, "skills", "crash-report-generator", "requirements.txt"),
    pyproject: null,
    editable: false,
    imports: ["jsonschema"],
  },
]

function usage() {
  console.log(`Usage:
  shennong-setup install [--python /path/to/python] [--force]
  shennong-setup check   [--python /path/to/python]
  shennong-setup start
  shennong-setup status
  shennong-setup stop

Commands:
  install   Install three Python environments and ensure MCP services are ready (default)
  check     Check package variant and Python/wheel platform without changing files
  start     Start the persistent witty-log-detection SSE MCP service
  status    Show readiness for three components and the persistent MCP service
  stop      Stop the package-managed witty-log-detection SSE MCP service`)
}

function parseArgs(argv) {
  const options = { command: "install", python: process.env.SHENNONG_PYTHON || null, force: false }
  let commandSeen = false
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (["install", "check", "start", "status", "stop"].includes(arg) && !commandSeen) {
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

function compareVersions(actual, expected) {
  const actualParts = String(actual || "").split(".").map((part) => Number.parseInt(part, 10) || 0)
  const expectedParts = String(expected || "").split(".").map((part) => Number.parseInt(part, 10) || 0)
  const width = Math.max(actualParts.length, expectedParts.length)
  for (let index = 0; index < width; index += 1) {
    const difference = (actualParts[index] || 0) - (expectedParts[index] || 0)
    if (difference !== 0) {
      return difference
    }
  }
  return 0
}

function matchesLibc(actual, expected) {
  const [expectedName, expectedVersion] = expected || []
  if (!expectedName) {
    return true
  }
  const [actualName, actualVersion] = actual || []
  return actualName === expectedName && compareVersions(actualVersion, expectedVersion) >= 0
}

function matchesWheelPlatform(info, expected) {
  if (!expected) {
    return true
  }
  const expectedMinor = expected.python.split(".").slice(0, 2).join(".")
  const actualMinor = info.python.split(".").slice(0, 2).join(".")
  return actualMinor === expectedMinor
    && info.implementation === expected.implementation
    && info.system === expected.system
    && info.machine === expected.machine
    && info.cache_tag === expected.cache_tag
    && (!expected.sysconfig_platform || info.sysconfig_platform === expected.sysconfig_platform)
    && (!expected.soabi || info.soabi === expected.soabi)
    && matchesLibc(info.libc, expected.libc)
}

function findPython(expectedPlatform, explicitPython) {
  const expectedMinor = expectedPlatform?.python?.split(".").slice(0, 2).join(".")
  const candidates = explicitPython
    ? [explicitPython]
    : [...new Set([
      process.env.PYTHON_BIN,
      expectedMinor ? `python${expectedMinor}` : null,
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
      continue
    }
  }
  if (explicitPython) {
    const info = inspectPython(explicitPython)
    throw new Error(`specified Python is incompatible: ${explicitPython} (${JSON.stringify(info)})`)
  }
  return null
}

function getPackageMetadata() {
  if (!existsSync(VARIANT_FILE)) {
    throw new Error(`package variant metadata is missing: ${VARIANT_FILE}`)
  }
  const variantMetadata = JSON.parse(readFileSync(VARIANT_FILE, "utf8"))
  if (!["online", "offline"].includes(variantMetadata.variant)) {
    throw new Error(`invalid package variant: ${variantMetadata.variant}`)
  }
  const packageJson = JSON.parse(readFileSync(join(PROJECT_ROOT, "package.json"), "utf8"))
  return { ...variantMetadata, packageName: packageJson.name, packageVersion: packageJson.version }
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex")
}

function isInside(root, candidate) {
  const rel = relative(root, candidate)
  return rel !== "" && rel !== ".." && !rel.startsWith(`..${sep}`) && !isAbsolute(rel)
}

function resolveRegularPackageFile(relativePath, label) {
  if (typeof relativePath !== "string" || relativePath.length === 0 || isAbsolute(relativePath)) {
    throw new Error(`${label} has an invalid path: ${relativePath}`)
  }
  const absolutePath = resolve(PROJECT_ROOT, relativePath)
  if (!isInside(PROJECT_ROOT, absolutePath) || !existsSync(absolutePath)) {
    throw new Error(`${label} is missing or escapes package root: ${relativePath}`)
  }
  const metadata = lstatSync(absolutePath)
  if (metadata.isSymbolicLink() || !metadata.isFile()) {
    throw new Error(`${label} must be a regular file: ${relativePath}`)
  }
  if (!isInside(realpathSync(PROJECT_ROOT), realpathSync(absolutePath))) {
    throw new Error(`${label} resolves outside package root: ${relativePath}`)
  }
  return { absolutePath, metadata }
}

function listRegularFiles(root, extension) {
  const output = []
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name)
    const metadata = lstatSync(path)
    if (metadata.isSymbolicLink()) {
      throw new Error(`symbolic links are not allowed in offline wheelhouse: ${path}`)
    }
    if (metadata.isDirectory()) {
      output.push(...listRegularFiles(path, extension))
    } else if (metadata.isFile() && path.endsWith(extension)) {
      output.push(path)
    }
  }
  return output.sort()
}

function verifyContentManifest(metadata) {
  const manifestName = metadata.contentManifest || "package-content-manifest.json"
  const { absolutePath } = resolveRegularPackageFile(manifestName, "package content manifest")
  const manifest = JSON.parse(readFileSync(absolutePath, "utf8"))
  if (!metadata.contentComplete || !manifest.contentComplete) {
    const warnings = [...new Set([
      ...(metadata.lfsPointerWarnings || []),
      ...(manifest.lfsPointerWarnings || []),
    ])]
    throw new Error(`package content is incomplete; Git LFS files were not materialized: ${warnings.join(", ")}`)
  }
  if (!Array.isArray(manifest.files) || manifest.fileCount !== manifest.files.length) {
    throw new Error("package content manifest count does not match its file list")
  }
  for (const file of manifest.files) {
    const checked = resolveRegularPackageFile(file.path, "required package content")
    if (checked.metadata.size !== file.size) {
      throw new Error(`required content size mismatch: ${file.path}`)
    }
    if (sha256(checked.absolutePath) !== file.sha256) {
      throw new Error(`required content checksum mismatch: ${file.path}`)
    }
    if (
      checked.metadata.size < 1024
      && readFileSync(checked.absolutePath, "utf8").startsWith("version https://git-lfs.github.com/spec/v1")
    ) {
      throw new Error(`required content is a Git LFS pointer: ${file.path}`)
    }
  }
  return manifest
}

function verifyWheelManifest(metadata) {
  if (metadata.variant !== "offline") {
    return null
  }
  const { absolutePath: manifestPath } = resolveRegularPackageFile(
    "python-wheel-manifest.json",
    "offline wheel manifest",
  )
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
  if (
    !metadata.wheelPlatform
    || JSON.stringify(metadata.wheelPlatform) !== JSON.stringify(manifest.platform)
  ) {
    throw new Error("offline wheel platform metadata does not match its wheel manifest")
  }
  if (!manifest.dependencyClosureVerified) {
    throw new Error("offline wheel dependency closure was not verified during packaging")
  }
  if (manifest.wheelCount !== manifest.wheels.length) {
    throw new Error("offline wheel manifest count does not match its file list")
  }
  const actualWheels = listRegularFiles(join(PROJECT_ROOT, "python-wheels"), ".whl")
    .map((path) => relative(PROJECT_ROOT, path).split(sep).join("/"))
  const expectedWheels = manifest.wheels.map(({ path }) => path).sort()
  if (
    actualWheels.length !== expectedWheels.length
    || actualWheels.some((path, index) => path !== expectedWheels[index])
  ) {
    throw new Error("offline wheelhouse contains missing, extra, or unlisted wheel files")
  }
  for (const wheel of manifest.wheels) {
    if (!wheel.path.startsWith("python-wheels/")) {
      throw new Error(`offline wheel has an invalid manifest path: ${wheel.path}`)
    }
    const checked = resolveRegularPackageFile(wheel.path, "offline wheel")
    if (checked.metadata.size !== wheel.size) {
      throw new Error(`offline wheel size mismatch: ${wheel.path}`)
    }
    if (sha256(checked.absolutePath) !== wheel.sha256) {
      throw new Error(`offline wheel checksum mismatch: ${wheel.path}`)
    }
  }
  return manifest
}

function childEnvironment(offline) {
  return {
    ...process.env,
    PYTHONNOUSERSITE: "1",
    PIP_DISABLE_PIP_VERSION_CHECK: "1",
    PIP_REQUIRE_VIRTUALENV: "1",
    ...(offline ? { PIP_NO_INDEX: "1" } : {}),
  }
}

function assertVirtualEnvironment(venvPython, offline) {
  execFileSync(venvPython, [
    "-c",
    "import sys; assert sys.prefix != sys.base_prefix, 'pip target is not a virtual environment'",
  ], { stdio: "inherit", env: childEnvironment(offline) })
}

function verifyPythonEnvironment(venvPython, imports, offline) {
  assertVirtualEnvironment(venvPython, offline)
  execFileSync(venvPython, ["-m", "pip", "check"], {
    stdio: "inherit",
    cwd: PROJECT_ROOT,
    env: childEnvironment(offline),
  })
  const importProgram = [
    "import importlib",
    ...imports.map((moduleName) => `importlib.import_module(${JSON.stringify(moduleName)})`),
  ].join("; ")
  execFileSync(venvPython, ["-c", importProgram], {
    stdio: "inherit",
    cwd: PROJECT_ROOT,
    env: childEnvironment(offline),
  })
}

function pipInstall(venvPython, args, offline) {
  assertVirtualEnvironment(venvPython, offline)
  execFileSync(venvPython, [
    "-m", "pip", "install",
    "--disable-pip-version-check",
    ...(offline ? ["--isolated", "--no-cache-dir"] : []),
    ...args,
  ], {
    stdio: "inherit",
    cwd: PROJECT_ROOT,
    env: childEnvironment(offline),
  })
}

function installRequirements(venvPython, requirements, wheelDir, offline) {
  const args = []
  if (offline) {
    args.push("--no-index", "--find-links", wheelDir)
  }
  args.push("-r", requirements)
  pipInstall(venvPython, args, offline)
}

function installCrashFeatureMatcher(venvPython, pkgDir, wheelDir, offline) {
  if (!offline) {
    pipInstall(venvPython, ["-e", pkgDir], false)
    return
  }
  const wheel = readdirSync(wheelDir).find((name) => (
    name.startsWith("crash_feature_matcher-") && name.endsWith(".whl")
  ))
  if (!wheel) {
    throw new Error(`offline wheel missing for crash-feature-matcher in ${wheelDir}`)
  }
  pipInstall(venvPython, [
    "--no-index", "--find-links", wheelDir, join(wheelDir, wheel),
  ], true)
}

function checkSetup(options) {
  const metadata = getPackageMetadata()
  const contentManifest = verifyContentManifest(metadata)
  const manifest = verifyWheelManifest(metadata)
  const expectedPlatform = metadata.variant === "offline" ? manifest.platform : null
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
    requiredContentFileCount: contentManifest.fileCount,
    wheelCount: manifest?.wheelCount || 0,
    status: "ready",
  }, null, 2))
  return { metadata, contentManifest, manifest, python }
}

function setupFingerprints(metadata) {
  const venvHashes = VENVS.map((venv) => {
    const files = [venv.requirements]
    if (venv.pyproject && existsSync(venv.pyproject)) {
      files.push(venv.pyproject)
    }
    return `${venv.name}:${files.map(sha256).join("|")}`
  })
  return {
    pythonDepsSha256: createHash("sha256").update(venvHashes.join("\n")).digest("hex"),
    wheelManifestSha256: metadata.variant === "offline" ? sha256(WHEEL_MANIFEST_FILE) : null,
  }
}

function inspectExistingSetup(metadata, pythonInfo, fingerprints, offline) {
  if (!existsSync(VENV_DIR)) {
    return { ready: false, reason: "setup directory does not exist" }
  }
  const directory = lstatSync(VENV_DIR)
  if (directory.isSymbolicLink() || !directory.isDirectory()) {
    throw new Error(`refusing to use non-directory or symbolic-link setup path: ${VENV_DIR}`)
  }
  const markerPath = join(VENV_DIR, "setup-complete.json")
  if (!existsSync(markerPath)) {
    return { ready: false, reason: "completion marker is missing" }
  }
  try {
    const marker = JSON.parse(readFileSync(markerPath, "utf8"))
    if (
      marker.package !== metadata.packageName
      || marker.version !== metadata.packageVersion
      || marker.variant !== metadata.variant
      || JSON.stringify(marker.python) !== JSON.stringify(pythonInfo)
      || marker.pythonDepsSha256 !== fingerprints.pythonDepsSha256
      || marker.wheelManifestSha256 !== fingerprints.wheelManifestSha256
    ) {
      return { ready: false, reason: "completion marker does not match this package, manifests, or Python" }
    }
    for (const venv of VENVS) {
      const venvPython = join(VENV_DIR, venv.name, "bin", "python")
      if (!existsSync(venvPython) || JSON.stringify(inspectPython(venvPython)) !== JSON.stringify(pythonInfo)) {
        return { ready: false, reason: `virtual environment is incomplete or incompatible: ${venv.name}` }
      }
      verifyPythonEnvironment(venvPython, venv.imports, offline)
    }
    return { ready: true, marker }
  } catch (error) {
    return { ready: false, reason: `completion marker or virtual environment is invalid: ${error.message}` }
  }
}

async function ensureServices() {
  const result = await startServices(PROJECT_ROOT)
  console.log(
    `[shennong-setup] crash-feature-matcher stdio MCP: ready (started on demand by OpenCode)`
  )
  console.log(
    `[shennong-setup] witty-log-detection SSE MCP: ${result.state} (${result.endpoint})`
  )
  if (result.state === "external") {
    console.warn(
      `[shennong-setup] WARNING: ${result.endpoint} is already occupied by an untracked process ` +
        `(possibly a stale service from a previous installation) and will be reused as-is. ` +
        `If MCP tools misbehave, stop that process and rerun 'shennong-setup install'.`
    )
  }
  console.log(`[shennong-setup] crash-report-generator skill: ready`)
  return result
}

async function install(options) {
  const { metadata, python } = checkSetup(options)
  const offline = metadata.variant === "offline"
  await ensureOcrModels(metadata)
  const fingerprints = setupFingerprints(metadata)
  const existing = inspectExistingSetup(metadata, python.info, fingerprints, offline)
  if (existing.ready && !options.force) {
    console.log("[shennong-setup] Python dependencies are already installed and verified.")
    await ensureServices()
    return
  }
  if (existsSync(VENV_DIR) && !options.force) {
    throw new Error(`existing setup is not reusable (${existing.reason}); rerun with --force`)
  }

  const suffix = `${process.pid}-${Date.now()}`
  const backupDir = `${VENV_DIR}.backup-${suffix}`
  rmSync(backupDir, { recursive: true, force: true })

  let backupCreated = false
  let newSetupCreated = false
  try {
    if (existsSync(VENV_DIR)) {
      const current = lstatSync(VENV_DIR)
      if (current.isSymbolicLink() || !current.isDirectory()) {
        throw new Error(`refusing to replace non-directory or symbolic-link setup path: ${VENV_DIR}`)
      }
      renameSync(VENV_DIR, backupDir)
      backupCreated = true
    }
    mkdirSync(VENV_DIR, { recursive: true })
    newSetupCreated = true

    for (const venv of VENVS) {
      const venvPath = join(VENV_DIR, venv.name)
      const venvPython = join(venvPath, "bin", "python")
      console.log(`[shennong-setup] Creating venv: ${venv.name}`)
      execFileSync(python.command, ["-m", "venv", venvPath], {
        stdio: "inherit",
        cwd: PROJECT_ROOT,
        env: childEnvironment(offline),
      })

      const wheelDir = offline ? join(PROJECT_ROOT, "python-wheels", venv.name) : null
      if (offline && !existsSync(wheelDir)) {
        throw new Error(`offline wheelhouse missing: ${wheelDir}`)
      }
      installRequirements(venvPython, venv.requirements, wheelDir, offline)
      if (venv.editable && existsSync(venv.pyproject)) {
        installCrashFeatureMatcher(venvPython, dirname(venv.pyproject), wheelDir, offline)
      }
      verifyPythonEnvironment(venvPython, venv.imports, offline)
    }

    const marker = {
      package: metadata.packageName,
      version: metadata.packageVersion,
      variant: metadata.variant,
      python: python.info,
      ...fingerprints,
      completedAt: new Date().toISOString(),
    }
    writeFileSync(join(VENV_DIR, "setup-complete.json"), `${JSON.stringify(marker, null, 2)}\n`)

    if (backupCreated) {
      rmSync(backupDir, { recursive: true, force: true })
      backupCreated = false
    }
    newSetupCreated = false
    console.log("[shennong-setup] Python dependencies installed successfully.")
    await ensureServices()
  } catch (error) {
    if (newSetupCreated && existsSync(VENV_DIR)) {
      rmSync(VENV_DIR, { recursive: true, force: true })
      newSetupCreated = false
    }
    if (backupCreated && existsSync(backupDir)) {
      try {
        renameSync(backupDir, VENV_DIR)
        backupCreated = false
      } catch (restoreError) {
        throw new Error(
          `${error.message}; failed to restore previous setup from ${backupDir}: ${restoreError.message}`,
        )
      }
    }
    throw error
  } finally {
    if (backupCreated) {
      console.error(`[shennong-setup] Previous setup retained at ${backupDir}`)
    }
  }
}

try {
  const options = parseArgs(process.argv.slice(2))
  if (options.command === "check") {
    checkSetup(options)
  } else if (options.command === "start") {
    await ensureServices()
  } else if (options.command === "status") {
    console.log(JSON.stringify(await serviceStatus(PROJECT_ROOT), null, 2))
  } else if (options.command === "stop") {
    console.log(JSON.stringify(await stopServices(PROJECT_ROOT), null, 2))
  } else {
    await install(options)
  }
} catch (error) {
  console.error(`[shennong-setup] ${error.message}`)
  process.exit(1)
}
