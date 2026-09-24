#!/usr/bin/env node

import { execFileSync } from "node:child_process"
import { createHash } from "node:crypto"
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
import { dirname, join, relative, resolve, sep } from "node:path"
import { fileURLToPath } from "node:url"

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = resolve(SCRIPT_DIR, "..")
const DEFAULT_OUTPUT_DIR = join(PROJECT_ROOT, "artifacts")
const ONLINE_MAX_BYTES = Number(process.env.ONLINE_MAX_BYTES || 10 * 1024 * 1024)
const REQUIRED_FILES_MANIFEST = join(PROJECT_ROOT, "packaging", "required-package-files.txt")

const COPY_ITEMS = ["agent", "tools", "workflow", "dist", "skills", "bin", "lib", "scripts", "benchmark.yaml", "requirements.txt", "README.md"]

function parseArgs(argv) {
  const options = {
    variant: null,
    packageStyle: process.env.PACKAGE_STYLE || "organization",
    outputDir: DEFAULT_OUTPUT_DIR,
    targetArch: process.env.TARGET_ARCH || null,
  }
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg.startsWith("--variant=")) options.variant = arg.slice("--variant=".length)
    else if (arg === "--variant") options.variant = argv[++index]
    else if (arg.startsWith("--package-style=")) options.packageStyle = arg.slice("--package-style=".length)
    else if (arg === "--package-style") options.packageStyle = argv[++index]
    else if (arg.startsWith("--out-dir=")) options.outputDir = resolve(PROJECT_ROOT, arg.slice("--out-dir=".length))
    else if (arg === "--out-dir") options.outputDir = resolve(PROJECT_ROOT, argv[++index])
    else if (arg.startsWith("--target-arch=")) options.targetArch = arg.slice("--target-arch=".length)
    else if (arg === "--target-arch") options.targetArch = argv[++index]
    else throw new Error(`unknown argument: ${arg}`)
  }
  if (!["online"].includes(options.variant)) throw new Error("only --variant=online is supported")
  if (!["organization", "plain"].includes(options.packageStyle)) throw new Error("--package-style must be organization or plain")
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

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex")
}

function listFiles(root) {
  const output = []
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name)
    const metadata = lstatSync(path)
    if (metadata.isSymbolicLink()) throw new Error(`symbolic links are not allowed in packages: ${path}`)
    if (metadata.isDirectory()) output.push(...listFiles(path))
    else if (metadata.isFile()) output.push(path)
  }
  return output.sort()
}

function shouldCopy(source) {
  const rel = relative(PROJECT_ROOT, source)
  return !rel.split(sep).some((part) => ["node_modules", "__pycache__"].includes(part)) && !source.endsWith(".pyc")
}

function copyPackageFiles(stageDir) {
  for (const item of COPY_ITEMS) {
    const source = join(PROJECT_ROOT, item)
    if (!existsSync(source)) throw new Error(`required package path is missing: ${source}`)
    cpSync(source, join(stageDir, item), { recursive: true, filter: (candidate) => shouldCopy(candidate) })
  }
}

function readRequiredPackageFiles() {
  return readFileSync(REQUIRED_FILES_MANIFEST, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"))
}

function validateRequiredPackageFiles(stageDir, requiredFiles) {
  const missing = requiredFiles.filter((path) => !existsSync(join(stageDir, path)))
  if (missing.length > 0) throw new Error(`required package files are missing: ${missing.join(", ")}`)
}

function findLfsPointers(stageDir) {
  return listFiles(stageDir)
    .filter((path) => statSync(path).size < 1024)
    .filter((path) => readFileSync(path, "utf8").startsWith("version https://git-lfs.github.com/spec/v1"))
    .map((path) => relative(stageDir, path).split(sep).join("/"))
}

function writeContentManifest(stageDir, requiredFiles, lfsPointers) {
  const packagedFiles = listFiles(stageDir).map((path) => relative(stageDir, path).split(sep).join("/"))
  const contentPaths = [...new Set([...requiredFiles, ...packagedFiles])].sort()
  const files = contentPaths.map((path) => {
    const absolutePath = join(stageDir, path)
    const metadata = lstatSync(absolutePath)
    if (metadata.isSymbolicLink() || !metadata.isFile()) throw new Error(`required content must be a regular file: ${path}`)
    return { path, size: metadata.size, sha256: sha256(absolutePath) }
  })
  const manifest = {
    fileCount: files.length,
    contentComplete: lfsPointers.length === 0,
    lfsPointerWarnings: lfsPointers,
    files,
  }
  writeFileSync(join(stageDir, "package-content-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`)
  return manifest
}

function resolveArch(requested) {
  if (requested && requested !== "native") return requested
  const current = process.arch
  if (current === "x64") return "x86_64"
  if (current === "arm64") return "aarch64"
  return current
}

function resolvePackageBaseName(basePackage, packageStyle) {
  const names = basePackage.wittyAgentDistribution?.packageNames
  const packageName = names?.[packageStyle]
  if (!packageName || typeof packageName !== "string") throw new Error(`package name for style ${packageStyle} is not configured`)
  if (packageStyle === "organization" && !packageName.startsWith("@")) throw new Error("organization package name must be scoped")
  if (packageStyle === "plain" && packageName.startsWith("@")) throw new Error("plain package name must be unscoped")
  return packageName
}

function bundleRuntimeDependencies(stageDir, basePackage, variant) {
  if (variant !== "offline") return []
  const dependencies = Object.keys(basePackage.dependencies || {})
  for (const dependency of dependencies) {
    const segments = dependency.split("/")
    const source = join(PROJECT_ROOT, "node_modules", ...segments)
    if (!existsSync(source)) throw new Error(`runtime dependency is unavailable for offline bundling: ${dependency}; run npm ci first`)
    cpSync(source, join(stageDir, "node_modules", ...segments), { recursive: true })
  }
  return dependencies
}

function writeStagePackageJson(stageDir, basePackage, variant, packageStyle, arch) {
  const {
    scripts: _baseScripts,
    devDependencies: _baseDevDependencies,
    wittyAgentDistribution: _distribution,
    ...publishableBase
  } = basePackage
  const packageBaseName = resolvePackageBaseName(basePackage, packageStyle)
  const packageJson = {
    ...publishableBase,
    name: variant === "offline" ? `${packageBaseName}-offline-${arch}` : `${packageBaseName}-online`,
    description: `${basePackage.description} (${variant}${variant === "offline" ? ` ${arch}` : ""} package)`,
    files: [
      "agent",
      "dist",
      "skills",
      "tools", "workflow", "benchmark.yaml", "requirements.txt",
      "bin",
      "lib",
      "scripts",
      "README.md",
      "package-variant.json",
      "package-content-manifest.json",
      ...(variant === "offline" ? ["node_modules"] : []),
    ],
    wittyPackageStyle: packageStyle,
    shennongVariant: variant,
    ...(variant === "offline" ? { bundledDependencies: Object.keys(basePackage.dependencies || {}) } : {}),
  }
  writeFileSync(join(stageDir, "package.json"), `${JSON.stringify(packageJson, null, 2)}\n`)
}

function packStage(stageDir, outputDir) {
  mkdirSync(outputDir, { recursive: true })
  const result = JSON.parse(commandOutput("npm", [
    "pack", stageDir, "--ignore-scripts", "--json", "--pack-destination", outputDir,
  ]))[0]
  if (!result?.filename) throw new Error("npm pack did not return a package filename")
  return { npm: result, tgzPath: join(outputDir, result.filename) }
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  const basePackage = JSON.parse(readFileSync(join(PROJECT_ROOT, "package.json"), "utf8"))
  const architecture = resolveArch(options.targetArch)
  const requiredFiles = readRequiredPackageFiles()
  const stageDir = join(PROJECT_ROOT, ".package-stage", options.packageStyle, options.variant)
  rmSync(stageDir, { recursive: true, force: true })
  mkdirSync(stageDir, { recursive: true })

  copyPackageFiles(stageDir)
  const bundledRuntimeDependencies = bundleRuntimeDependencies(stageDir, basePackage, options.variant)
  validateRequiredPackageFiles(stageDir, requiredFiles)
  const lfsPointers = findLfsPointers(stageDir)
  const contentManifest = writeContentManifest(stageDir, requiredFiles, lfsPointers)

  const variantMetadata = {
    variant: options.variant,
    packageStyle: options.packageStyle,
    architecture: options.variant === "offline" ? architecture : null,
    contentComplete: contentManifest.contentComplete,
    contentManifest: "package-content-manifest.json",
    lfsPointerWarnings: contentManifest.lfsPointerWarnings,
    bundledRuntimeDependencies,
  }
  writeFileSync(join(stageDir, "package-variant.json"), `${JSON.stringify(variantMetadata, null, 2)}\n`)
  writeStagePackageJson(stageDir, basePackage, options.variant, options.packageStyle, architecture)

  const { npm: npmResult, tgzPath } = packStage(stageDir, options.outputDir)
  const actualSize = statSync(tgzPath).size
  if (options.variant === "online" && actualSize > ONLINE_MAX_BYTES) {
    throw new Error(`online package is ${actualSize} bytes; limit is ${ONLINE_MAX_BYTES} bytes`)
  }

  const report = {
    variant: options.variant,
    packageStyle: options.packageStyle,
    architecture: options.variant === "offline" ? architecture : null,
    packageName: npmResult.name,
    version: npmResult.version,
    filename: npmResult.filename,
    size: actualSize,
    unpackedSize: npmResult.unpackedSize,
    entryCount: npmResult.entryCount,
    sha256: sha256(tgzPath),
    onlineLimitBytes: options.variant === "online" ? ONLINE_MAX_BYTES : null,
    onlineSizePassed: options.variant === "online" ? actualSize <= ONLINE_MAX_BYTES : null,
    bundledRuntimeDependencies,
    requiredFileCount: requiredFiles.length,
    manifestedContentFileCount: contentManifest.fileCount,
    contentComplete: contentManifest.contentComplete,
    lfsPointerWarnings: contentManifest.lfsPointerWarnings,
  }
  writeFileSync(join(options.outputDir, `${options.variant}-package-report.json`), `${JSON.stringify(report, null, 2)}\n`)
  writeFileSync(join(options.outputDir, `${options.variant}-npm-pack.json`), `${JSON.stringify(npmResult, null, 2)}\n`)

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