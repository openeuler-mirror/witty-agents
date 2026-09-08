#!/usr/bin/env node

import { execFileSync } from "node:child_process"
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { prepareRegistryPackage } from "../lib/registry-package.mjs"

const REPO_ROOT = resolve(fileURLToPath(new URL("../..", import.meta.url)))
const REPORT_PATH = join(REPO_ROOT, "shennong-crash-agent", "artifacts", "online-package-report.json")
const report = JSON.parse(readFileSync(REPORT_PATH, "utf8"))
const sourcePath = join(REPO_ROOT, "shennong-crash-agent", "artifacts", report.filename)
const sandbox = mkdtempSync(join(tmpdir(), "witty-registry-package-test-"))

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

try {
  const candidate = prepareRegistryPackage({
    sourcePath,
    registryPackageName: "witty-agent-shennong",
    workingRoot: sandbox,
  })
  assert(candidate.packageName === "witty-agent-shennong", "registry package name was not rewritten")
  assert(candidate.sourcePackageName === report.packageName, "source package name was not recorded")
  assert(candidate.version === report.version, "registry package version changed")

  const extracted = join(sandbox, "inspect")
  mkdirSync(extracted)
  execFileSync("tar", ["-xzf", candidate.path, "-C", extracted])
  const packageJson = JSON.parse(readFileSync(join(extracted, "package", "package.json"), "utf8"))
  assert(packageJson.name === "witty-agent-shennong", "packed registry package has the wrong name")
  assert(packageJson.wittySourcePackageName === report.packageName, "packed registry package lost source identity")
  assert(packageJson.shennongVariant === "online", "registry candidate is not online")
  assert(packageJson.scripts?.postinstall === "node bin/postinstall.mjs", "postinstall hint is missing")

  const consumer = join(sandbox, "consumer")
  mkdirSync(consumer)
  writeFileSync(join(consumer, "package.json"), '{"name":"registry-candidate-test","private":true}\n')
  const output = execFileSync("npm", [
    "install", candidate.path, "--foreground-scripts", "--no-audit", "--no-fund",
  ], {
    cwd: consumer,
    encoding: "utf8",
    env: { ...process.env, NPM_CONFIG_CACHE: join(sandbox, "npm-cache") },
  })
  assert(output.includes("npm exec -- shennong-setup install"), "registry install did not show setup hint")
  console.log(output.trim())
  console.log("registry package contract: PASS")
} finally {
  rmSync(sandbox, { recursive: true, force: true })
}
