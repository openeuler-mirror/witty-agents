#!/usr/bin/env node

import { execFileSync, spawnSync } from "node:child_process"
import { createHash } from "node:crypto"
import {
  chmodSync,
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { arch, tmpdir } from "node:os"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { prepareRegistryPackage } from "../lib/registry-package.mjs"

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(SCRIPT_DIR, "../..")
const DEFAULT_REPORT = join(REPO_ROOT, "shennong-crash-agent", "artifacts", "online-package-report.json")
const DEFAULT_OUTPUT = join(REPO_ROOT, "ci-artifacts", "npm-publish-smoke-summary.json")
const POLL_ATTEMPTS = 24
const POLL_INTERVAL_MS = 5_000
const REGISTRY_PACKAGE_NAME = "witty-agent-shennong"

function parseArgs(argv) {
  const options = { report: DEFAULT_REPORT, output: DEFAULT_OUTPUT }
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]
    const [rawKey, inlineValue] = argument.split("=", 2)
    const key = rawKey.replace(/^--/, "")
    const value = inlineValue ?? argv[++index]
    if (key === "report") options.report = resolve(REPO_ROOT, value)
    else if (key === "output") options.output = resolve(REPO_ROOT, value)
    else throw new Error(`unknown argument: ${argument}`)
  }
  return options
}

function digest(path, algorithm, encoding = "hex") {
  return createHash(algorithm).update(readFileSync(path)).digest(encoding)
}

function sha512Integrity(path) {
  return `sha512-${digest(path, "sha512", "base64")}`
}

function normalizeArchitecture(value) {
  if (value === "x64" || value === "x86_64") return "x86_64"
  if (value === "arm64" || value === "aarch64") return "aarch64"
  return value
}

function npmResult(args, environment) {
  return spawnSync("npm", args, {
    cwd: REPO_ROOT,
    env: environment,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  })
}

function npmOutput(args, environment) {
  const result = npmResult(args, environment)
  if (result.status !== 0) {
    throw new Error(result.stderr.trim() || result.stdout.trim() || `npm ${args[0]} failed`)
  }
  return result.stdout.trim()
}

function queryIntegrity(coordinate, registry, environment) {
  const result = npmResult([
    "view", coordinate, "dist.integrity", "--prefer-online", "--registry", registry,
  ], environment)
  if (result.status === 0) return { state: "ready", integrity: result.stdout.trim() }
  const output = `${result.stderr}\n${result.stdout}`
  if (output.includes("E404")) return { state: "not-found", integrity: null }
  return { state: "retryable-error", integrity: null, detail: output.trim() }
}

function queryTagVersion(packageName, distTag, registry, environment) {
  const result = npmResult([
    "view", `${packageName}@${distTag}`, "version", "--prefer-online", "--registry", registry,
  ], environment)
  if (result.status === 0) return { state: "ready", version: result.stdout.trim() }
  const output = `${result.stderr}\n${result.stdout}`
  if (output.includes("E404")) return { state: "not-found", version: null }
  return { state: "retryable-error", version: null }
}

function sleep(milliseconds) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds))
}

async function waitForIntegrity(coordinate, expectedIntegrity, registry, environment) {
  let lastState = "not-queried"
  for (let attempt = 1; attempt <= POLL_ATTEMPTS; attempt += 1) {
    const result = queryIntegrity(coordinate, registry, environment)
    lastState = result.state
    if (result.state === "ready") {
      if (result.integrity !== expectedIntegrity) {
        throw new Error(`${coordinate}: registry contains different content`)
      }
      console.log(`PASS: registry metadata visible (${attempt}/${POLL_ATTEMPTS})`)
      return
    }
    if (attempt < POLL_ATTEMPTS) {
      console.log(`Waiting for registry metadata (${attempt}/${POLL_ATTEMPTS}, ${result.state})`)
      await sleep(POLL_INTERVAL_MS)
    }
  }
  throw new Error(`${coordinate}: registry metadata was not visible after ${POLL_ATTEMPTS} attempts (last state: ${lastState})`)
}

async function waitForTag(packageName, version, distTag, registry, environment) {
  let lastVersion = null
  for (let attempt = 1; attempt <= POLL_ATTEMPTS; attempt += 1) {
    const result = queryTagVersion(packageName, distTag, registry, environment)
    lastVersion = result.version
    if (result.state === "ready" && result.version === version) {
      console.log(`PASS: dist-tag ${distTag} -> ${version}`)
      return
    }
    if (attempt < POLL_ATTEMPTS) {
      const detail = result.version ? `currently ${result.version}` : result.state
      console.log(`Waiting for dist-tag ${distTag} (${attempt}/${POLL_ATTEMPTS}, ${detail})`)
      await sleep(POLL_INTERVAL_MS)
    }
  }
  throw new Error(`${packageName}: dist-tag ${distTag} did not point to ${version} after ${POLL_ATTEMPTS} attempts (last value: ${lastVersion || "unavailable"})`)
}

async function downloadAndVerify(coordinate, sourcePath, expectedIntegrity, registry, environment, workingRoot) {
  const downloadDir = join(workingRoot, "npm-download")
  const downloadCache = join(workingRoot, "npm-download-cache")
  mkdirSync(downloadDir, { recursive: true })
  mkdirSync(downloadCache, { recursive: true })

  let lastError = "not attempted"
  for (let attempt = 1; attempt <= POLL_ATTEMPTS; attempt += 1) {
    const result = npmResult([
      "pack",
      coordinate,
      "--json",
      "--ignore-scripts",
      "--prefer-online",
      "--registry", registry,
      "--cache", downloadCache,
      "--pack-destination", downloadDir,
    ], environment)
    if (result.status === 0) {
      const payload = JSON.parse(result.stdout)
      const filename = payload[0]?.filename
      if (!filename) throw new Error(`${coordinate}: npm pack did not report a filename`)
      const downloadedPath = join(downloadDir, filename)
      if (!existsSync(downloadedPath)) throw new Error(`${coordinate}: downloaded tgz is missing`)
      const downloadedIntegrity = sha512Integrity(downloadedPath)
      if (downloadedIntegrity !== expectedIntegrity) {
        throw new Error(`${coordinate}: downloaded package integrity does not match the built package`)
      }
      const sourceSha256 = digest(sourcePath, "sha256")
      const downloadedSha256 = digest(downloadedPath, "sha256")
      if (sourceSha256 !== downloadedSha256) {
        throw new Error(`${coordinate}: downloaded package SHA-256 does not match the built package`)
      }
      console.log(`PASS: downloaded package SHA-256=${downloadedSha256}`)
      return { filename, path: downloadedPath, sha256: downloadedSha256, integrity: downloadedIntegrity }
    }
    lastError = result.stderr.trim() || result.stdout.trim() || "npm pack failed"
    if (attempt < POLL_ATTEMPTS) {
      console.log(`Waiting to download published package (${attempt}/${POLL_ATTEMPTS})`)
      await sleep(POLL_INTERVAL_MS)
    }
  }
  throw new Error(`${coordinate}: npm download failed after ${POLL_ATTEMPTS} attempts: ${lastError}`)
}

function validateInputs(report, sourcePath, expectedArchitecture, distTag, registry) {
  const prereleaseSemver = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*$/
  if (report.variant !== "online") throw new Error("smoke publishing accepts only the online variant")
  if (report.packageStyle !== "plain") throw new Error("smoke publishing accepts only an unscoped plain package")
  if (report.packageName !== "openeuler-agent-shennong-crash-online") {
    throw new Error(`unexpected smoke package name: ${report.packageName}`)
  }
  if (!prereleaseSemver.test(report.version || "")) {
    throw new Error("smoke publishing requires a prerelease package version")
  }
  if (report.versionOverrideApplied !== true) {
    throw new Error("smoke publishing requires an explicit package version override")
  }
  if (process.env.PACKAGE_VERSION_OVERRIDE && report.version !== process.env.PACKAGE_VERSION_OVERRIDE) {
    throw new Error("artifact version does not match PACKAGE_VERSION_OVERRIDE")
  }
  if (!distTag || distTag === "latest") throw new Error("smoke publishing cannot use the latest dist-tag")
  if (!existsSync(sourcePath)) throw new Error(`package artifact is missing: ${sourcePath}`)
  const actualArchitecture = normalizeArchitecture(arch())
  if (expectedArchitecture && actualArchitecture !== expectedArchitecture) {
    throw new Error(`expected native ${expectedArchitecture}, current Node architecture is ${actualArchitecture}`)
  }
  const architectureId = actualArchitecture === "aarch64" ? "aarch64" : "x86-64"
  const expectedTag = actualArchitecture === "aarch64" ? "arm-test" : "x86-test"
  if (distTag !== expectedTag) {
    throw new Error(`smoke dist-tag must be ${expectedTag} on ${actualArchitecture}`)
  }
  if (!report.version.includes(`-ci.${architectureId}.`)) {
    throw new Error(`smoke version must contain -ci.${architectureId}. on ${actualArchitecture}`)
  }
  if (new URL(registry).href !== "https://registry.npmjs.org/") {
    throw new Error("smoke publishing is restricted to https://registry.npmjs.org/")
  }
  if (report.sha256 !== digest(sourcePath, "sha256")) {
    throw new Error("artifact SHA-256 does not match its package report")
  }
  return actualArchitecture
}

async function main() {
  const { report: reportPath, output } = parseArgs(process.argv.slice(2))
  const token = process.env.NPM_TOKEN
  const registry = process.env.NPM_REGISTRY || "https://registry.npmjs.org/"
  const distTag = process.env.NPM_DIST_TAG || ""
  const expectedArchitecture = process.env.TARGET_ARCH || ""
  if (!token) throw new Error("NPM_TOKEN is required")

  const report = JSON.parse(readFileSync(reportPath, "utf8"))
  const sourcePath = join(dirname(reportPath), report.filename)
  const actualArchitecture = validateInputs(report, sourcePath, expectedArchitecture, distTag, registry)
  const outputRoot = dirname(output)
  mkdirSync(outputRoot, { recursive: true })
  const workingRoot = mkdtempSync(join(tmpdir(), "witty-agents-npm-publish-"))
  const registryPackage = prepareRegistryPackage({
    sourcePath,
    registryPackageName: REGISTRY_PACKAGE_NAME,
    workingRoot,
  })
  if (registryPackage.version !== report.version) {
    throw new Error("registry package version does not match the validated source artifact")
  }
  const expectedIntegrity = sha512Integrity(registryPackage.path)
  const coordinate = `${registryPackage.packageName}@${registryPackage.version}`

  const registryUrl = new URL(registry)
  const registryPath = registryUrl.pathname.endsWith("/")
    ? registryUrl.pathname.slice(0, -1)
    : registryUrl.pathname
  const authKey = `//${registryUrl.host}${registryPath}/:_authToken`
  const npmrc = join(workingRoot, ".npmrc")
  writeFileSync(npmrc, `registry=${registryUrl.href}\n${authKey}=${token}\n`, { mode: 0o600 })
  chmodSync(npmrc, 0o600)
  const environment = {
    ...process.env,
    NPM_CONFIG_USERCONFIG: npmrc,
    NPM_CONFIG_CACHE: join(workingRoot, "npm-cache"),
  }

  try {
    const npmUser = npmOutput(["whoami", "--registry", registry], environment)
    console.log(`npm authenticated user: ${npmUser}`)
    const current = queryIntegrity(coordinate, registry, environment)
    let action = "published"
    if (current.state === "ready") {
      if (current.integrity !== expectedIntegrity) {
        throw new Error(`${coordinate} already exists with different content`)
      }
      action = "verified-existing"
      console.log(`PASS: ${coordinate} already exists with identical content`)
      npmOutput(["dist-tag", "add", coordinate, distTag, "--registry", registry], environment)
    } else if (current.state === "not-found") {
      const publishArgs = [
        "publish", registryPackage.path,
        "--ignore-scripts",
        "--tag", distTag,
        "--registry", registry,
      ]
      execFileSync("npm", publishArgs, { cwd: REPO_ROOT, env: environment, stdio: "inherit" })
    } else {
      throw new Error(`${coordinate}: registry preflight failed: ${current.detail}`)
    }

    await waitForIntegrity(coordinate, expectedIntegrity, registry, environment)
    await waitForTag(registryPackage.packageName, registryPackage.version, distTag, registry, environment)
    const download = await downloadAndVerify(
      coordinate,
      registryPackage.path,
      expectedIntegrity,
      registry,
      environment,
      workingRoot,
    )
    const archivedDownloadDir = join(outputRoot, "npm-download")
    rmSync(archivedDownloadDir, { recursive: true, force: true })
    mkdirSync(archivedDownloadDir, { recursive: true })
    copyFileSync(download.path, join(archivedDownloadDir, download.filename))
    const summary = {
      status: "passed",
      action,
      packageName: registryPackage.packageName,
      version: registryPackage.version,
      distTag,
      registry,
      builtOnArchitecture: actualArchitecture,
      sourcePackageName: report.packageName,
      sourceFilename: report.filename,
      sourceSha256: report.sha256,
      registryFilename: registryPackage.filename,
      registrySha256: registryPackage.sha256,
      integrity: expectedIntegrity,
      downloadedFilename: download.filename,
      downloadedSha256: download.sha256,
      verifiedAt: new Date().toISOString(),
    }
    writeFileSync(output, `${JSON.stringify(summary, null, 2)}\n`)
    console.log(JSON.stringify(summary, null, 2))
  } finally {
    rmSync(workingRoot, { recursive: true, force: true })
  }
}

main().catch((error) => {
  console.error(`[publish-smoke] ${error.message}`)
  process.exit(1)
})
