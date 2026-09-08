#!/usr/bin/env node

import { createHash } from "node:crypto"
import { execFileSync, spawnSync } from "node:child_process"
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { prepareRegistryPackage } from "../lib/registry-package.mjs"

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(SCRIPT_DIR, "../..")
const DEFAULT_PLAN = join(REPO_ROOT, "ci-artifacts", "build-plan.json")
const PUBLISH_SUMMARY = join(REPO_ROOT, "ci-artifacts", "publish-summary.json")

function parseArgs(argv) {
  let planPath = DEFAULT_PLAN
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]
    if (argument.startsWith("--plan=")) planPath = resolve(REPO_ROOT, argument.slice("--plan=".length))
    else if (argument === "--plan") planPath = resolve(REPO_ROOT, argv[++index])
    else throw new Error(`unknown argument: ${argument}`)
  }
  return { planPath }
}

function npmOutput(args, environment) {
  return execFileSync("npm", args, {
    cwd: REPO_ROOT,
    env: environment,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim()
}

function sha512Integrity(path) {
  return `sha512-${createHash("sha512").update(readFileSync(path)).digest("base64")}`
}

function existingIntegrity(packageName, version, registry, environment) {
  const result = spawnSync("npm", ["view", `${packageName}@${version}`, "dist.integrity", "--registry", registry], {
    cwd: REPO_ROOT,
    env: environment,
    encoding: "utf8",
  })
  if (result.status === 0) return result.stdout.trim()
  if (`${result.stderr}\n${result.stdout}`.includes("E404")) return null
  throw new Error(`unable to query ${packageName}@${version}: ${result.stderr.trim() || result.stdout.trim()}`)
}

function main() {
  const { planPath } = parseArgs(process.argv.slice(2))
  const token = process.env.NPM_TOKEN
  const registry = process.env.NPM_REGISTRY || "https://registry.npmjs.org/"
  const distTag = process.env.NPM_DIST_TAG || "latest"
  if (!token) throw new Error("NPM_TOKEN is required")
  const plan = JSON.parse(readFileSync(planPath, "utf8"))
  if (plan.publish !== true) throw new Error("build plan was not resolved with PUBLISH=true")

  const registryUrl = new URL(registry)
  const registryPath = registryUrl.pathname.endsWith("/")
    ? registryUrl.pathname.slice(0, -1)
    : registryUrl.pathname
  const authKey = `//${registryUrl.host}${registryPath}/:_authToken`
  const npmrc = join(REPO_ROOT, "ci-artifacts", ".npmrc.publish")
  mkdirSync(dirname(npmrc), { recursive: true })
  writeFileSync(npmrc, `registry=${registryUrl.href}\n${authKey}=${token}\n`, { mode: 0o600 })
  chmodSync(npmrc, 0o600)
  const environment = { ...process.env, NPM_CONFIG_USERCONFIG: npmrc }
  const published = []
  const skipped = []
  const workingRoot = mkdtempSync(join(tmpdir(), "witty-agents-registry-package-"))

  try {
    npmOutput(["whoami", "--registry", registry], environment)
    for (const agent of plan.agents) {
      for (const variant of agent.variants) {
        const registryPackageName = agent.registryPackages?.[variant]
        if (agent.registryPackages && !registryPackageName) {
          skipped.push({ agent: agent.id, variant, reason: "not distributed through the npm registry" })
          console.log(`SKIP: ${agent.id}/${variant} is a local artifact and is not published to npm`)
          continue
        }
        const reportPath = join(REPO_ROOT, agent.directory, "artifacts", `${variant}-package-report.json`)
        const report = JSON.parse(readFileSync(reportPath, "utf8"))
        if (report.variant !== variant || report.packageStyle !== plan.packageStyle) {
          throw new Error(`${agent.id}/${variant}: artifact metadata does not match the build plan`)
        }
        const tgzPath = join(REPO_ROOT, agent.directory, "artifacts", report.filename)
        const target = registryPackageName
          ? prepareRegistryPackage({ sourcePath: tgzPath, registryPackageName, workingRoot })
          : { path: tgzPath, packageName: report.packageName, version: report.version, sourcePackageName: report.packageName }
        if (target.version !== report.version) {
          throw new Error(`${agent.id}/${variant}: registry candidate version mismatch`)
        }
        const expectedIntegrity = sha512Integrity(target.path)
        const currentIntegrity = existingIntegrity(target.packageName, target.version, registry, environment)
        let action = "published"
        if (currentIntegrity) {
          if (currentIntegrity !== expectedIntegrity) {
            throw new Error(`${target.packageName}@${target.version} already exists with different content`)
          }
          action = "verified-existing"
        } else {
          const args = ["publish", target.path, "--ignore-scripts", "--tag", distTag, "--registry", registry]
          if (target.packageName.startsWith("@")) args.push("--access", "public")
          execFileSync("npm", args, { cwd: REPO_ROOT, env: environment, stdio: "inherit" })
          const publishedIntegrity = npmOutput([
            "view", `${target.packageName}@${target.version}`, "dist.integrity", "--registry", registry,
          ], environment)
          if (publishedIntegrity !== expectedIntegrity) {
            throw new Error(`${target.packageName}@${target.version}: registry integrity verification failed`)
          }
        }
        published.push({
          agent: agent.id,
          variant,
          packageStyle: plan.packageStyle,
          packageName: target.packageName,
          version: target.version,
          filename: target.path.split("/").at(-1),
          sourcePackageName: report.packageName,
          sourceFilename: report.filename,
          integrity: expectedIntegrity,
          action,
        })
      }
    }
    writeFileSync(PUBLISH_SUMMARY, `${JSON.stringify({
      status: "passed",
      sourceCommit: plan.sourceCommit,
      registry,
      distTag,
      packages: published,
      skipped,
      publishedAt: new Date().toISOString(),
    }, null, 2)}\n`)
    console.log(`Published or verified ${published.length} package(s)`)
  } finally {
    rmSync(npmrc, { force: true })
    rmSync(workingRoot, { recursive: true, force: true })
  }
}

try {
  main()
} catch (error) {
  console.error(`[publish] ${error.message}`)
  process.exit(1)
}
