#!/usr/bin/env node

import { createHash } from "node:crypto"
import { execFileSync, spawnSync } from "node:child_process"
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
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

// npm rejects a version that already exists with different content. Instead of
// failing the publish stage, bump the patch version, rebuild the agent artifacts
// and publish the new version automatically.
function bumpPatch(version) {
  const match = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/.exec(version)
  if (!match) throw new Error(`cannot auto-bump a non-semver version: ${version}`)
  return `${match[1]}.${match[2]}.${Number(match[3]) + 1}${match[4] ? `-${match[4]}` : ""}`
}

function readPackageReport(agent, variant, plan) {
  const reportPath = join(REPO_ROOT, agent.directory, "artifacts", `${variant}-package-report.json`)
  const report = JSON.parse(readFileSync(reportPath, "utf8"))
  if (report.variant !== variant || report.packageStyle !== plan.packageStyle) {
    throw new Error(`${agent.id}/${variant}: artifact metadata does not match the build plan`)
  }
  return report
}

function rebuildAgentPackages(agent, plan) {
  const directory = resolve(REPO_ROOT, agent.directory)
  console.log(`[publish] rebuilding artifacts for ${agent.id} after the version bump`)
  execFileSync(process.execPath, [
    resolve(directory, agent.driver),
    "--phase=build",
    `--variants=${agent.variants.join(",")}`,
    `--package-style=${plan.packageStyle}`,
    `--target-arch=${plan.targetArchitecture}`,
  ], { cwd: directory, env: process.env, stdio: "inherit" })
}

function buildRegistryTarget({ agent, report, registryPackageName, workingRoot }) {
  if (registryPackageName) {
    return prepareRegistryPackage({
      sourcePath: join(REPO_ROOT, agent.directory, "artifacts", report.filename),
      registryPackageName,
      workingRoot,
    })
  }
  return {
    path: join(REPO_ROOT, agent.directory, "artifacts", report.filename),
    packageName: report.packageName,
    version: report.version,
    sourcePackageName: report.packageName,
  }
}

function resolveSourceBranch() {
  const fromEnv = process.env.GIT_BRANCH || process.env.BRANCH_NAME
  if (fromEnv && fromEnv !== "HEAD" && fromEnv !== "detached") {
    return fromEnv.replace(/^origin\//, "")
  }
  const result = spawnSync("git", ["-C", REPO_ROOT, "rev-parse", "--abbrev-ref", "HEAD"], { encoding: "utf8" })
  const branch = (result.stdout || "").trim()
  if (result.status === 0 && branch && branch !== "HEAD") return branch
  return null
}

function commitAndPushVersionBumps(bumps) {
  const changedFiles = []
  for (const bump of bumps) {
    for (const file of ["package.json", "package-lock.json"]) {
      if (existsSync(join(REPO_ROOT, bump.directory, file))) changedFiles.push(join(bump.directory, file))
    }
  }
  if (changedFiles.length === 0) return { committed: false, pushed: false, branch: null }

  const detail = bumps.map((bump) => `- ${bump.agentId}: ${bump.from} -> ${bump.to}`).join("\n")
  const message = [
    "chore(ci): auto-bump package versions for npm publish",
    "",
    detail,
    "",
    "The npm registry already had a different build under the previous version,",
    "so the Publish stage bumped the patch version, rebuilt and republished.",
  ].join("\n")
  execFileSync("git", ["-C", REPO_ROOT, "add", "--", ...changedFiles], { stdio: "inherit" })
  execFileSync("git", [
    "-C", REPO_ROOT,
    "-c", "user.name=witty-agents-ci",
    "-c", "user.email=witty-agents-ci@users.noreply.atomgit.com",
    "commit", "-m", message,
  ], { stdio: "inherit" })
  console.log(`[publish] committed auto-bumped versions (${bumps.map((b) => `${b.agentId} ${b.from} -> ${b.to}`).join(", ")})`)

  const branch = resolveSourceBranch()
  if (!branch) {
    console.warn("[publish] source branch could not be determined; the version bump commit stays in the workspace only")
    return { committed: true, pushed: false, branch: null }
  }
  if (!process.env.GIT_AUTH_USER) {
    console.warn(`[publish] GIT_CREDENTIAL_ID is not configured; push the version bump commit to origin/${branch} manually`)
    return { committed: true, pushed: false, branch }
  }
  // Inline credential helper reads GIT_AUTH_USER / GIT_AUTH_PASS from the
  // environment, so the secret never lands on disk.
  const credentialArgs = [
    "-c", "credential.helper=!f() { echo \"username=${GIT_AUTH_USER}\"; echo \"password=${GIT_AUTH_PASS}\"; }; f",
  ]
  try {
    execFileSync("git", ["-C", REPO_ROOT, ...credentialArgs, "push", "origin", `HEAD:refs/heads/${branch}`], {
      stdio: "inherit",
    })
    console.log(`[publish] pushed the version bump commit to origin/${branch}`)
    return { committed: true, pushed: true, branch }
  } catch (error) {
    console.warn(`[publish] could not push the version bump commit to origin/${branch}: ${error.message}; the commit stays in the workspace`)
    return { committed: true, pushed: false, branch }
  }
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
  const versionBumps = []
  const workingRoot = mkdtempSync(join(tmpdir(), "witty-agents-registry-package-"))

  try {
    npmOutput(["whoami", "--registry", registry], environment)
    for (const agent of plan.agents) {
      // registryPackages maps plain-style tgz names to npm registry names;
      // organization-style tarballs already carry their scoped npm name.
      const registryPackageName = (variant) => (
        plan.packageStyle === "plain" ? agent.registryPackages?.[variant] : null
      )
      let bump = null
      for (const variant of agent.variants) {
        const registryName = registryPackageName(variant)
        if (plan.packageStyle === "plain" && agent.registryPackages && !registryName) {
          skipped.push({ agent: agent.id, variant, reason: "not distributed through the npm registry" })
          console.log(`SKIP: ${agent.id}/${variant} is a local artifact and is not published to npm`)
          continue
        }
        let report = readPackageReport(agent, variant, plan)
        let target = buildRegistryTarget({ agent, report, registryPackageName: registryName, workingRoot })
        if (target.version !== report.version) {
          throw new Error(`${agent.id}/${variant}: registry candidate version mismatch`)
        }
        let expectedIntegrity = sha512Integrity(target.path)
        // Manual publishes upload the raw build tarball; CI publishes the
        // repacked registry tarball. Accept either as "same content" so an
        // existing manual release does not consume an extra version number.
        const sourceIntegrity = sha512Integrity(join(REPO_ROOT, agent.directory, "artifacts", report.filename))
        let currentIntegrity = existingIntegrity(target.packageName, target.version, registry, environment)
        if (currentIntegrity && currentIntegrity !== expectedIntegrity && currentIntegrity !== sourceIntegrity) {
          if (bump) {
            throw new Error(`${agent.id}/${variant}: content still conflicts after this agent was already bumped to ${bump.to}`)
          }
          const nextVersion = bumpPatch(report.version)
          console.log(`[publish] ${target.packageName}@${report.version} already exists with different content; auto-bumping to ${nextVersion}`)
          const agentDirectory = resolve(REPO_ROOT, agent.directory)
          execFileSync("npm", ["version", nextVersion, "--no-git-tag-version", "--allow-same-version"], {
            cwd: agentDirectory,
            env: environment,
            stdio: "inherit",
          })
          rebuildAgentPackages(agent, plan)
          bump = { agentId: agent.id, directory: agent.directory, from: report.version, to: nextVersion }
          report = readPackageReport(agent, variant, plan)
          target = buildRegistryTarget({ agent, report, registryPackageName: registryName, workingRoot })
          if (target.version !== report.version) {
            throw new Error(`${agent.id}/${variant}: registry candidate version mismatch after the auto bump`)
          }
          expectedIntegrity = sha512Integrity(target.path)
          currentIntegrity = existingIntegrity(target.packageName, target.version, registry, environment)
          if (currentIntegrity) {
            throw new Error(`${target.packageName}@${target.version} already exists after the auto bump`)
          }
        }
        let action = "published"
        if (currentIntegrity) {
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
          autoBumpedFrom: bump ? bump.from : null,
          verifiedAgainst: currentIntegrity === sourceIntegrity ? "source-tarball" : "registry-package",
        })
      }
      if (bump) versionBumps.push(bump)
    }

    const pushBack = versionBumps.length > 0
      ? commitAndPushVersionBumps(versionBumps)
      : { committed: false, pushed: false, branch: null }

    writeFileSync(PUBLISH_SUMMARY, `${JSON.stringify({
      status: "passed",
      sourceCommit: plan.sourceCommit,
      registry,
      distTag,
      packages: published,
      skipped,
      versionBumps,
      versionBumpPushBack: pushBack,
      publishedAt: new Date().toISOString(),
    }, null, 2)}\n`)
    console.log(`Published or verified ${published.length} package(s)${versionBumps.length > 0 ? ` (auto-bumped ${versionBumps.length} agent(s))` : ""}`)
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
