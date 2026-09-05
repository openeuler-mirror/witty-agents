#!/usr/bin/env node

import { execFileSync } from "node:child_process"
import {
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs"
import { createHash } from "node:crypto"
import { basename, dirname, join, relative, resolve, sep } from "node:path"
import { fileURLToPath } from "node:url"
import { validatePlugin } from "../lib/validate-plugin.mjs"

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = resolve(SCRIPT_DIR, "..")
const DEFAULT_OUTPUT_DIR = join(PROJECT_ROOT, "artifacts")
const ONLINE_MAX_BYTES = Number(process.env.ONLINE_MAX_BYTES || 10 * 1024 * 1024)
const OFFLINE_CONSTRAINTS = join(PROJECT_ROOT, "packaging", "offline-constraints.txt")
const REQUIRED_FILES_MANIFEST = join(PROJECT_ROOT, "packaging", "required-package-files.txt")

const COMPONENTS = [
  {
    name: "crash-feature-matcher",
    requirements: "skills/crash-feature-matcher/requirements.txt",
    localProject: "skills/crash-feature-matcher",
  },
  {
    name: "witty-log-detection",
    requirements: "skills/witty-log-detection/src/requirements.txt",
  },
  {
    name: "crash-report-generator",
    requirements: "skills/crash-report-generator/requirements.txt",
  },
]

function parseArgs(argv) {
  const options = {
    variant: null,
    outputDir: DEFAULT_OUTPUT_DIR,
    python: process.env.PYTHON_BIN || null,
  }

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg.startsWith("--variant=")) {
      options.variant = arg.slice("--variant=".length)
    } else if (arg === "--variant") {
      options.variant = argv[++index]
    } else if (arg.startsWith("--out-dir=")) {
      options.outputDir = resolve(PROJECT_ROOT, arg.slice("--out-dir=".length))
    } else if (arg === "--out-dir") {
      options.outputDir = resolve(PROJECT_ROOT, argv[++index])
    } else if (arg.startsWith("--python=")) {
      options.python = arg.slice("--python=".length)
    } else if (arg === "--python") {
      options.python = argv[++index]
    } else {
      throw new Error(`unknown argument: ${arg}`)
    }
  }

  if (!['online', 'offline'].includes(options.variant)) {
    throw new Error("--variant must be online or offline")
  }
  return options
}

function commandOutput(command, args) {
  return execFileSync(command, args, {
    cwd: PROJECT_ROOT,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "inherit"],
    maxBuffer: 64 * 1024 * 1024,
  }).trim()
}

function findPython(explicitPython) {
  const candidates = explicitPython
    ? [explicitPython]
    : ["python3.11", process.env.PYTHON_BIN, "python3.12", "python3", "python"].filter(Boolean)
  for (const candidate of candidates) {
    try {
      const output = commandOutput(candidate, ["--version"])
      const match = output.match(/Python\s+(\d+)\.(\d+)\.(\d+)/)
      if (match && Number(match[1]) === 3 && [11, 12].includes(Number(match[2]))) {
        return { command: candidate, version: match[0] }
      }
    } catch {
      // Try the next executable.
    }
  }
  const detail = explicitPython ? `: ${explicitPython}` : ""
  throw new Error(`offline packaging requires Python 3.11 or 3.12${detail}; use --python or PYTHON_BIN`)
}

function shouldCopy(source, variant) {
  const rel = relative(PROJECT_ROOT, source)
  const segments = rel.split(sep)
  if (segments.includes("__pycache__") || segments.includes(".venvs")) {
    return false
  }
  if (
    source.endsWith(".pyc")
    || source.endsWith(".DS_Store")
    || source.endsWith(".db")
    || source.endsWith(".db-wal")
    || source.endsWith(".db-shm")
    || basename(source).startsWith("._")
  ) {
    return false
  }
  if (rel.startsWith(join("skills", "witty-log-detection", "test"))) {
    return false
  }
  if (rel === join("skills", "crash-feature-matcher", "scripts", "test_community_retrieval.py")) {
    return false
  }
  if (
    variant === "online" &&
    rel.startsWith(join("skills", "witty-log-detection", "src", "model", "ocr"))
  ) {
    return false
  }
  return true
}

function copyPackageFiles(stageDir, variant) {
  for (const item of ["dist", "skills", "bin", "lib", "frameworks", "README.md", "agent.md"]) {
    const source = join(PROJECT_ROOT, item)
    if (!existsSync(source)) {
      throw new Error(`required package path is missing: ${source}`)
    }
    cpSync(source, join(stageDir, item), {
      recursive: true,
      filter: (candidate) => shouldCopy(candidate, variant),
    })
  }
}

function bundleRuntimeDependencies(stageDir, basePackage, variant) {
  if (variant !== "offline") {
    return []
  }
  const dependencies = Object.keys(basePackage.dependencies || {})
  for (const dependency of dependencies) {
    const segments = dependency.split("/")
    const source = join(PROJECT_ROOT, "node_modules", ...segments)
    if (!existsSync(source)) {
      throw new Error(`runtime dependency is unavailable for offline bundling: ${dependency}; run npm ci first`)
    }
    cpSync(source, join(stageDir, "node_modules", ...segments), { recursive: true })
  }
  return dependencies
}

function readRequiredPackageFiles() {
  if (!existsSync(REQUIRED_FILES_MANIFEST)) {
    throw new Error(`required-file manifest is missing: ${REQUIRED_FILES_MANIFEST}`)
  }
  return readFileSync(REQUIRED_FILES_MANIFEST, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"))
}

function validateRequiredPackageFiles(stageDir, requiredFiles) {
  const missing = requiredFiles.filter((path) => !existsSync(join(stageDir, path)))
  if (missing.length > 0) {
    throw new Error(`required package files are missing: ${missing.join(", ")}`)
  }
}

function validatePackedFiles(npmResult, requiredFiles) {
  const packedFiles = new Set(npmResult.files.map(({ path }) => path.replace(/^package\//, "")))
  const missing = requiredFiles.filter((path) => !packedFiles.has(path))
  if (missing.length > 0) {
    throw new Error(`required files were omitted from npm package: ${missing.join(", ")}`)
  }
}

function validateNoRuntimeDatabases(npmResult) {
  const databases = npmResult.files
    .map(({ path }) => path.replace(/^package\//, ""))
    .filter((path) => /\.db(?:-wal|-shm)?$/.test(path))
  if (databases.length > 0) {
    throw new Error(`runtime databases must not be published: ${databases.join(", ")}`)
  }
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex")
}

function listFiles(root) {
  const output = []
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name)
    const metadata = lstatSync(path)
    if (metadata.isSymbolicLink()) {
      throw new Error(`symbolic links are not allowed in packages: ${path}`)
    }
    if (metadata.isDirectory()) {
      output.push(...listFiles(path))
    } else if (metadata.isFile()) {
      output.push(path)
    }
  }
  return output.sort()
}

function validateRequirementSource(path) {
  const unsafe = readFileSync(path, "utf8")
    .split(/\r?\n/)
    .map((line, index) => ({ line: line.trim(), number: index + 1 }))
    .filter(({ line }) => line && !line.startsWith("#"))
    .find(({ line }) => (
      line.startsWith("-")
      || line.startsWith("./")
      || line.startsWith("../")
      || line.startsWith("/")
      || line.includes("://")
      || line.includes(" @ ")
      || /^(git|hg|svn|bzr)\+/i.test(line)
    ))
  if (unsafe) {
    throw new Error(`remote/path requirement is not allowed in offline input ${path}:${unsafe.number}: ${unsafe.line}`)
  }
}

function inspectPythonPlatform(pythonCommand) {
  return JSON.parse(commandOutput(pythonCommand, [
    "-c",
    "import json,platform,sys,sysconfig; print(json.dumps({'python': platform.python_version(), 'implementation': platform.python_implementation(), 'system': platform.system().lower(), 'machine': platform.machine(), 'cache_tag': sys.implementation.cache_tag, 'sysconfig_platform': sysconfig.get_platform(), 'soabi': sysconfig.get_config_var('SOABI'), 'libc': list(platform.libc_ver())}))",
  ]))
}

function validateWheelMetadata(pythonCommand, wheelRoot) {
  const script = `
import json, pathlib, re, sys, zipfile
violations = []
for wheel in pathlib.Path(sys.argv[1]).rglob("*.whl"):
    with zipfile.ZipFile(wheel) as archive:
        # A wheel may vendor other distributions (for example setuptools),
        # whose nested .dist-info directories are not the wheel's own metadata.
        metadata_files = [
            name for name in archive.namelist()
            if name.endswith(".dist-info/METADATA") and name.count("/") == 1
        ]
        if len(metadata_files) != 1:
            violations.append({"wheel": str(wheel), "requirement": "invalid METADATA count"})
            continue
        metadata = archive.read(metadata_files[0]).decode("utf-8", "replace")
        for line in metadata.splitlines():
            if line.startswith("Requires-Dist:") and (" @ " in line or "://" in line or re.search(r"(?:git|hg|svn|bzr)\\+", line, re.I)):
                violations.append({"wheel": str(wheel), "requirement": line})
print(json.dumps(violations))
`
  const violations = JSON.parse(commandOutput(pythonCommand, ["-c", script, wheelRoot]))
  if (violations.length > 0) {
    throw new Error(`offline wheels contain URL/VCS dependencies: ${JSON.stringify(violations)}`)
  }
}

function verifyWheelhouses(python, wheelRoot) {
  const verifiedComponents = []
  for (const component of COMPONENTS) {
    const destination = join(wheelRoot, component.name)
    const requirements = join(PROJECT_ROOT, component.requirements)
    const args = [
      "-m", "pip", "install",
      "--isolated", "--no-cache-dir", "--disable-pip-version-check",
      "--break-system-packages", "--dry-run", "--ignore-installed", "--no-index",
      "--find-links", destination,
      "-r", requirements,
    ]
    if (component.localProject) {
      const localWheel = readdirSync(destination).find((name) => (
        name.startsWith("crash_feature_matcher-") && name.endsWith(".whl")
      ))
      if (!localWheel) {
        throw new Error(`local project wheel is missing for ${component.name}`)
      }
      args.push(join(destination, localWheel))
    }
    execFileSync(python.command, args, {
      cwd: PROJECT_ROOT,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "inherit"],
      maxBuffer: 64 * 1024 * 1024,
      env: {
        ...process.env,
        PYTHONNOUSERSITE: "1",
        PIP_DISABLE_PIP_VERSION_CHECK: "1",
      },
    })
    console.log(`[offline] Verified no-index dependency closure for ${component.name}`)
    verifiedComponents.push(component.name)
  }
  return verifiedComponents
}

function buildWheelhouses(stageDir, explicitPython) {
  const python = findPython(explicitPython)
  const wheelRoot = join(stageDir, "python-wheels")
  if (!existsSync(OFFLINE_CONSTRAINTS)) {
    throw new Error(`offline constraints are missing: ${OFFLINE_CONSTRAINTS}`)
  }
  validateRequirementSource(OFFLINE_CONSTRAINTS)
  mkdirSync(wheelRoot, { recursive: true })
  cpSync(OFFLINE_CONSTRAINTS, join(wheelRoot, "offline-constraints.txt"))

  for (const component of COMPONENTS) {
    const destination = join(wheelRoot, component.name)
    const requirements = join(PROJECT_ROOT, component.requirements)
    validateRequirementSource(requirements)
    mkdirSync(destination, { recursive: true })
    console.log(`[offline] Building wheels for ${component.name}`)
    execFileSync(python.command, [
      "-m", "pip", "wheel",
      "--disable-pip-version-check",
      "--wheel-dir", destination,
      "--constraint", OFFLINE_CONSTRAINTS,
      "-r", requirements,
    ], { cwd: PROJECT_ROOT, stdio: "inherit" })

    if (component.localProject) {
      execFileSync(python.command, [
        "-m", "pip", "wheel",
        "--disable-pip-version-check",
        "--no-deps",
        "--wheel-dir", destination,
        join(PROJECT_ROOT, component.localProject),
      ], { cwd: PROJECT_ROOT, stdio: "inherit" })
    }
  }

  const platform = inspectPythonPlatform(python.command)
  const wheels = listFiles(wheelRoot).filter((path) => path.endsWith(".whl")).map((path) => ({
    path: relative(stageDir, path).split(sep).join("/"),
    size: statSync(path).size,
    sha256: sha256(path),
  }))
  validateWheelMetadata(python.command, wheelRoot)
  const verifiedComponents = verifyWheelhouses(python, wheelRoot)
  const manifest = {
    platform,
    wheelCount: wheels.length,
    dependencyClosureVerified: verifiedComponents.length === COMPONENTS.length,
    verifiedComponents,
    wheels,
  }
  writeFileSync(join(stageDir, "python-wheel-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`)
  return manifest
}

function findLfsPointers(stageDir) {
  return listFiles(stageDir)
    .filter((path) => statSync(path).size < 1024)
    .filter((path) => readFileSync(path, "utf8").startsWith("version https://git-lfs.github.com/spec/v1"))
    .map((path) => relative(stageDir, path).split(sep).join("/"))
}

function writeContentManifest(stageDir, requiredFiles, lfsPointers) {
  const packagedSkillFiles = listFiles(join(stageDir, "skills"))
    .map((path) => relative(stageDir, path).split(sep).join("/"))
  const contentPaths = [...new Set([...requiredFiles, ...packagedSkillFiles])].sort()
  const files = contentPaths.map((path) => {
    const absolutePath = join(stageDir, path)
    const metadata = lstatSync(absolutePath)
    if (metadata.isSymbolicLink() || !metadata.isFile()) {
      throw new Error(`required content must be a regular file: ${path}`)
    }
    return {
      path,
      size: metadata.size,
      sha256: sha256(absolutePath),
    }
  })
  const manifest = {
    fileCount: files.length,
    contentComplete: lfsPointers.length === 0,
    lfsPointerWarnings: lfsPointers,
    files,
  }
  writeFileSync(
    join(stageDir, "package-content-manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
  )
  return manifest
}

function writeStagePackageJson(stageDir, basePackage, variant) {
  const {
    scripts: _baseScripts,
    devDependencies: _baseDevDependencies,
    ...publishableBase
  } = basePackage
  const packageJson = {
    ...publishableBase,
    name: variant === "online"
      ? basePackage.name
      : `${basePackage.name}-${variant}`,
    description: variant === "online"
      ? basePackage.description
      : `${basePackage.description} (${variant} package)`,
    files: [
      "dist",
      "skills",
      "bin",
      "lib",
      "frameworks",
      "agent.md",
      "package-variant.json",
      "package-content-manifest.json",
      ...(variant === "offline" ? ["python-wheels", "python-wheel-manifest.json"] : []),
    ],
    shennongVariant: variant,
    ...(variant === "offline"
      ? { bundledDependencies: Object.keys(basePackage.dependencies || {}) }
      : {}),
  }
  writeFileSync(join(stageDir, "package.json"), `${JSON.stringify(packageJson, null, 2)}\n`)
}

function packStage(stageDir, outputDir) {
  mkdirSync(outputDir, { recursive: true })
  const result = JSON.parse(commandOutput("npm", [
    "pack",
    stageDir,
    "--ignore-scripts",
    "--json",
    "--pack-destination",
    outputDir,
  ]))[0]
  if (!result?.filename) {
    throw new Error("npm pack did not return a package filename")
  }
  return { npm: result, tgzPath: join(outputDir, result.filename) }
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  if (!Number.isFinite(ONLINE_MAX_BYTES) || ONLINE_MAX_BYTES <= 0) {
    throw new Error("ONLINE_MAX_BYTES must be a positive number")
  }
  const basePackage = JSON.parse(readFileSync(join(PROJECT_ROOT, "package.json"), "utf8"))
  const requiredFiles = readRequiredPackageFiles()
  const stageDir = join(PROJECT_ROOT, ".package-stage", options.variant)
  rmSync(stageDir, { recursive: true, force: true })
  mkdirSync(stageDir, { recursive: true })

  copyPackageFiles(stageDir, options.variant)
  const bundledRuntimeDependencies = bundleRuntimeDependencies(stageDir, basePackage, options.variant)
  validateRequiredPackageFiles(stageDir, requiredFiles)
  validatePlugin(join(stageDir, "dist", "index.js"), stageDir)
  const lfsPointers = findLfsPointers(stageDir)
  const contentManifest = writeContentManifest(stageDir, requiredFiles, lfsPointers)
  let pythonWheelManifest = null
  if (options.variant === "offline") {
    pythonWheelManifest = buildWheelhouses(stageDir, options.python)
  }

  const variantMetadata = {
    variant: options.variant,
    pythonDependencies: options.variant === "offline" ? "bundled-wheels" : "download-on-install",
    wheelPlatform: pythonWheelManifest?.platform || null,
    contentComplete: contentManifest.contentComplete,
    contentManifest: "package-content-manifest.json",
    lfsPointerWarnings: contentManifest.lfsPointerWarnings,
  }
  writeFileSync(join(stageDir, "package-variant.json"), `${JSON.stringify(variantMetadata, null, 2)}\n`)
  writeStagePackageJson(stageDir, basePackage, options.variant)

  const { npm: npmResult, tgzPath } = packStage(stageDir, options.outputDir)
  validatePackedFiles(npmResult, [
    ...requiredFiles,
    "package-content-manifest.json",
    "package-variant.json",
    "bin/shennong-configure.mjs",
    "bin/shennong-setup.mjs",
    "lib/mcp-services.mjs",
    "lib/opencode-config.mjs",
    "lib/configure/backup.mjs",
    "lib/configure/common.mjs",
    "lib/configure/adapters/index.mjs",
    "lib/configure/adapters/opencode.mjs",
    "lib/configure/adapters/dsh.mjs",
    "frameworks/dsh/package.json.template",
    "frameworks/dsh/cordis.patch.yml.template",
    "frameworks/dsh/shennong-persona.md",
    ...(options.variant === "offline" ? ["node_modules/jsonc-parser/package.json"] : []),
  ])
  validateNoRuntimeDatabases(npmResult)
  const actualSize = statSync(tgzPath).size
  if (options.variant === "online" && actualSize > ONLINE_MAX_BYTES) {
    throw new Error(`online package is ${actualSize} bytes; limit is ${ONLINE_MAX_BYTES} bytes`)
  }

  const report = {
    variant: options.variant,
    packageName: npmResult.name,
    version: npmResult.version,
    filename: npmResult.filename,
    size: actualSize,
    unpackedSize: npmResult.unpackedSize,
    entryCount: npmResult.entryCount,
    sha256: sha256(tgzPath),
    onlineLimitBytes: options.variant === "online" ? ONLINE_MAX_BYTES : null,
    onlineSizePassed: options.variant === "online" ? actualSize <= ONLINE_MAX_BYTES : null,
    pythonWheelCount: pythonWheelManifest?.wheelCount || 0,
    wheelPlatform: pythonWheelManifest?.platform || null,
    pythonDependencyClosureVerified: pythonWheelManifest?.dependencyClosureVerified || false,
    bundledRuntimeDependencies,
    requiredFileCount: requiredFiles.length,
    manifestedContentFileCount: contentManifest.fileCount,
    contentComplete: contentManifest.contentComplete,
    lfsPointerWarnings: contentManifest.lfsPointerWarnings,
  }
  writeFileSync(
    join(options.outputDir, `${options.variant}-package-report.json`),
    `${JSON.stringify(report, null, 2)}\n`,
  )
  writeFileSync(
    join(options.outputDir, `${options.variant}-npm-pack.json`),
    `${JSON.stringify(npmResult, null, 2)}\n`,
  )

  console.log(JSON.stringify(report, null, 2))
  if (!contentManifest.contentComplete) {
    throw new Error(`package contains Git LFS pointer files: ${contentManifest.lfsPointerWarnings.join(", ")}`)
  }
}

try {
  main()
} catch (error) {
  console.error(`[package] ${error.message}`)
  process.exit(1)
}
