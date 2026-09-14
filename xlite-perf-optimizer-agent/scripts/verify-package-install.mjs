#!/usr/bin/env node

import { execFileSync } from "node:child_process"
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { basename, dirname, join, resolve } from "node:path"
import { parse } from "jsonc-parser"

function parseArgs(argv) {
  const options = { artifact: null, variant: null, report: null }
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === "--artifact") options.artifact = argv[++index]
    else if (arg.startsWith("--artifact=")) options.artifact = arg.slice("--artifact=".length)
    else if (arg === "--variant") options.variant = argv[++index]
    else if (arg.startsWith("--variant=")) options.variant = arg.slice("--variant=".length)
    else if (arg === "--report") options.report = argv[++index]
    else if (arg.startsWith("--report=")) options.report = arg.slice("--report=".length)
    else throw new Error(`unknown argument: ${arg}`)
  }
  if (!options.artifact || !["online", "offline"].includes(options.variant)) {
    throw new Error("--artifact and --variant=online|offline are required")
  }
  options.artifact = resolve(options.artifact)
  options.report = resolve(options.report || `install-flow-${options.variant}.json`)
  if (!existsSync(options.artifact)) throw new Error(`package artifact does not exist: ${options.artifact}`)
  return options
}

function run(command, args, options = {}) {
  return execFileSync(command, args, {
    cwd: options.cwd,
    env: options.env || process.env,
    encoding: options.encoding,
    stdio: options.encoding ? ["ignore", "pipe", "inherit"] : "inherit",
    maxBuffer: 64 * 1024 * 1024,
  })
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function listBackups(configPath) {
  const directory = dirname(configPath)
  return existsSync(directory)
    ? execFileSync("find", [directory, "-maxdepth", "1", "-name", `${basename(configPath)}.xlite-perf-optimizer-backup-*`], { encoding: "utf8" })
        .trim().split("\n").filter(Boolean).sort()
    : []
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  const startedAt = Date.now()
  const workdir = mkdtempSync(join(tmpdir(), `xlite-real-${options.variant}-`))
  const projectDir = join(workdir, "consumer")
  const homeDir = join(workdir, "home")
  const configPath = join(homeDir, ".config", "opencode", "opencode.jsonc")
  const initialConfig = `{
  // Existing settings must survive registration.
  "$schema": "https://opencode.ai/config.json",
  "agent": { "other-agent": { "description": "keep-me", "prompt": "{file:/tmp/other-agent.md}" } },
  "theme": "system"
}
`
  mkdirSync(projectDir, { recursive: true })
  mkdirSync(dirname(configPath), { recursive: true })
  writeFileSync(join(projectDir, "package.json"), `${JSON.stringify({ name: `xlite-${options.variant}-consumer`, private: true }, null, 2)}\n`)
  writeFileSync(configPath, initialConfig)

  const environment = {
    ...process.env,
    HOME: homeDir,
    XDG_CONFIG_HOME: join(homeDir, ".config"),
    XLITE_OPENCODE_CONFIG: configPath,
  }

  let succeeded = false
  try {
    const installArgs = [
      "install", "--no-audit", "--no-fund",
      ...(options.variant === "offline" ? ["--offline", "--cache", join(workdir, "empty-npm-cache")] : []),
      options.artifact,
    ]
    run("npm", installArgs, { cwd: projectDir, env: environment })
    assert(readFileSync(configPath, "utf8") === initialConfig, "npm install changed OpenCode configuration")

    const packageReport = JSON.parse(readFileSync(join(dirname(options.artifact), `${options.variant}-package-report.json`), "utf8"))
    const packageName = packageReport.packageName
    const packageRoot = join(projectDir, "node_modules", ...packageName.split("/"))
    assert(existsSync(packageRoot), `installed package is missing: ${packageRoot}`)

    const configure = ["exec", "--offline", "--", "xlite-perf-optimizer-configure", "register"]
    run("npm", configure, { cwd: projectDir, env: environment })
    const configAfterFirst = readFileSync(configPath, "utf8")
    assert(listBackups(configPath).length === 1, "configure did not create exactly one backup")
    const parsed = parse(configAfterFirst, [], { allowTrailingComma: true, disallowComments: false })
    assert(parsed.theme === "system", "configure did not preserve unrelated settings")
    assert(configAfterFirst.includes("keep-me"), "configure removed an unrelated agent entry")
    assert(configAfterFirst.includes("// Existing settings must survive registration."), "configure removed a comment")
    const entry = parsed.agent["xlite-perf-optimizer"]
    assert(entry, "configure did not register the xlite-perf-optimizer agent")
    assert(Array.isArray(entry.skills) && entry.skills.length > 0, "configure did not register skills")
    const promptMatch = entry.prompt?.match(/^\{file:(.+)\}$/)
    assert(promptMatch, "configure prompt is not a file reference")
    assert(promptMatch[1].endsWith("/agent/agent.md") && existsSync(promptMatch[1]), "configure prompt path does not resolve to agent/agent.md")

    run("npm", configure, { cwd: projectDir, env: environment })
    assert(readFileSync(configPath, "utf8") === configAfterFirst, "repeated configure changed configuration")
    assert(listBackups(configPath).length === 1, "repeated configure created another backup")

    const remove = ["exec", "--offline", "--", "xlite-perf-optimizer-configure", "remove"]
    run("npm", remove, { cwd: projectDir, env: environment })
    const configAfterRemove = readFileSync(configPath, "utf8")
    assert(listBackups(configPath).length === 2, "remove did not create exactly one additional backup")
    const parsedAfterRemove = parse(configAfterRemove, [], { allowTrailingComma: true, disallowComments: false })
    assert(parsedAfterRemove.theme === "system", "remove did not preserve unrelated settings")
    assert(parsedAfterRemove.agent["other-agent"], "remove deleted an unrelated agent entry")
    assert(!parsedAfterRemove.agent["xlite-perf-optimizer"], "remove left the xlite-perf-optimizer registration")

    run("npm", remove, { cwd: projectDir, env: environment })
    assert(readFileSync(configPath, "utf8") === configAfterRemove, "repeated remove changed configuration")
    assert(listBackups(configPath).length === 2, "repeated remove created another backup")

    run("npm", ["uninstall", packageName, "--no-audit", "--no-fund"], { cwd: projectDir, env: environment })
    assert(!existsSync(packageRoot), "npm uninstall left the package directory")

    const report = {
      status: "passed",
      variant: options.variant,
      artifact: options.artifact,
      packageName,
      networkIsolation: process.env.XLITE_NETWORK_ISOLATION || "none",
      npmInstallPreservedConfig: true,
      configureBackupCount: 1,
      configureIdempotent: true,
      removeBackupCount: 1,
      removeIdempotent: true,
      npmUninstallRemovedPackage: true,
      durationSeconds: Number(((Date.now() - startedAt) / 1000).toFixed(3)),
    }
    mkdirSync(dirname(options.report), { recursive: true })
    writeFileSync(options.report, `${JSON.stringify(report, null, 2)}\n`)
    succeeded = true
    console.log(JSON.stringify(report, null, 2))
  } finally {
    if (succeeded) rmSync(workdir, { recursive: true, force: true })
    else console.error(`[verify-install] Failed workspace retained at ${workdir}`)
  }
}

try {
  main()
} catch (error) {
  console.error(`[verify-install] ${error.message}`)
  process.exit(1)
}