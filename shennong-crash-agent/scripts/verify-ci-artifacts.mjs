#!/usr/bin/env node

import { createHash } from "node:crypto"
import {
  existsSync,
  readFileSync,
  statSync,
  writeFileSync,
} from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = resolve(SCRIPT_DIR, "..")
const ARTIFACT_DIR = join(PROJECT_ROOT, "artifacts")
const VALID_VARIANTS = new Set(["online", "offline"])

function parseArgs(argv) {
  let variants = process.env.SELECTED_VARIANTS || "online,offline"
  let packageStyle = process.env.PACKAGE_STYLE || "organization"
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg.startsWith("--variants=")) {
      variants = arg.slice("--variants=".length)
    } else if (arg === "--variants") {
      variants = argv[++index]
    } else if (arg.startsWith("--package-style=")) {
      packageStyle = arg.slice("--package-style=".length)
    } else if (arg === "--package-style") {
      packageStyle = argv[++index]
    } else {
      throw new Error(`unknown argument: ${arg}`)
    }
  }
  const selected = [...new Set(variants.split(",").map((item) => item.trim()).filter(Boolean))]
  if (selected.length === 0 || selected.some((item) => !VALID_VARIANTS.has(item))) {
    throw new Error("--variants must contain online and/or offline")
  }
  if (!["organization", "plain"].includes(packageStyle)) {
    throw new Error("--package-style must be organization or plain")
  }
  return { variants: selected, packageStyle }
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex")
}

function resolveExpectedPackageName(basePackage, variant, packageStyle) {
  const baseName = basePackage.wittyAgentDistribution?.packageNames?.[packageStyle]
  assert(typeof baseName === "string" && baseName.length > 0, `package style is not configured: ${packageStyle}`)
  return `${baseName}-${variant}`
}

function verifyVariant(variant, basePackage, packageStyle) {
  const reportPath = join(ARTIFACT_DIR, `${variant}-package-report.json`)
  assert(existsSync(reportPath), `${variant}: package report is missing`)
  const report = JSON.parse(readFileSync(reportPath, "utf8"))
  const tgzPath = join(ARTIFACT_DIR, report.filename || "")

  assert(report.variant === variant, `${variant}: report variant mismatch`)
  assert(report.packageStyle === packageStyle, `${variant}: report package style mismatch`)
  assert(
    report.packageName === resolveExpectedPackageName(basePackage, variant, packageStyle),
    `${variant}: package name mismatch: ${report.packageName}`,
  )
  const versionOverride = process.env.PACKAGE_VERSION_OVERRIDE || ""
  if (versionOverride) {
    assert(
      process.env.ALLOW_PACKAGE_VERSION_OVERRIDE === "true",
      `${variant}: package version override is not allowed in this build`,
    )
    assert(report.sourceVersion === basePackage.version, `${variant}: source version mismatch`)
    assert(report.versionOverrideApplied === true, `${variant}: version override was not recorded`)
  } else {
    assert(report.sourceVersion === basePackage.version, `${variant}: source version mismatch`)
    assert(report.versionOverrideApplied === false, `${variant}: unexpected version override metadata`)
  }
  const expectedVersion = versionOverride || basePackage.version
  assert(report.version === expectedVersion, `${variant}: package version mismatch`)
  assert(existsSync(tgzPath), `${variant}: tgz is missing: ${tgzPath}`)
  assert(statSync(tgzPath).size === report.size, `${variant}: tgz size does not match report`)
  assert(sha256(tgzPath) === report.sha256, `${variant}: tgz checksum does not match report`)
  assert(report.size > 0, `${variant}: package is empty`)
  assert(report.entryCount > 0, `${variant}: npm package has no entries`)
  assert(report.contentComplete === true, `${variant}: required content is incomplete`)
  assert(
    Array.isArray(report.lfsPointerWarnings) && report.lfsPointerWarnings.length === 0,
    `${variant}: package contains Git LFS pointers`,
  )
  assert(report.requiredFileCount > 0, `${variant}: required-file count is invalid`)
  assert(
    report.manifestedContentFileCount >= report.requiredFileCount,
    `${variant}: manifested content count is smaller than required-file count`,
  )

  if (variant === "online") {
    assert(report.onlineSizePassed === true, "online: 10 MiB size gate failed")
    assert(report.size <= report.onlineLimitBytes, "online: package exceeds configured limit")
    assert(report.pythonWheelCount === 0, "online: package unexpectedly contains Python wheels")
  } else {
    assert(report.pythonWheelCount > 0, "offline: wheelhouse is empty")
    assert(
      report.pythonDependencyClosureVerified === true,
      "offline: Python dependency closure was not verified",
    )
    assert(report.wheelPlatform?.system, "offline: wheel system metadata is missing")
    assert(report.wheelPlatform?.machine, "offline: wheel architecture metadata is missing")
    assert(report.wheelPlatform?.cache_tag, "offline: Python ABI metadata is missing")
  }

  return {
    variant,
    packageStyle,
    packageName: report.packageName,
    version: report.version,
    filename: report.filename,
    size: report.size,
    sha256: report.sha256,
    pythonWheelCount: report.pythonWheelCount,
    wheelPlatform: report.wheelPlatform,
    contentComplete: report.contentComplete,
  }
}

function main() {
  const { variants, packageStyle } = parseArgs(process.argv.slice(2))
  const basePackage = JSON.parse(readFileSync(join(PROJECT_ROOT, "package.json"), "utf8"))
  const packages = variants.map((variant) => verifyVariant(variant, basePackage, packageStyle))
  const summary = {
    status: "passed",
    sourceCommit: process.env.GIT_COMMIT || null,
    buildNumber: process.env.BUILD_NUMBER || null,
    generatedAt: new Date().toISOString(),
    variants,
    packageStyle,
    packages,
  }
  writeFileSync(join(ARTIFACT_DIR, "ci-summary.json"), `${JSON.stringify(summary, null, 2)}\n`)
  console.log(JSON.stringify(summary, null, 2))
}

try {
  main()
} catch (error) {
  console.error(`[ci-artifacts] ${error.message}`)
  process.exit(1)
}
