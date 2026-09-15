#!/usr/bin/env node

import { execFileSync } from "node:child_process"
import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { basename, dirname, join, resolve } from "node:path"
import { pathToFileURL } from "node:url"
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
    ? execFileSync("find", [directory, "-maxdepth", "1", "-name", `${basename(configPath)}.nl2sql-backup-*`], { encoding: "utf8" })
        .trim().split("\n").filter(Boolean).sort()
    : []
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  const startedAt = Date.now()
  const workdir = mkdtempSync(join(tmpdir(), `nl2sql-real-${options.variant}-`))
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
  writeFileSync(join(projectDir, "package.json"), `${JSON.stringify({ name: `nl2sql-${options.variant}-consumer`, private: true }, null, 2)}\n`)
  writeFileSync(configPath, initialConfig)

  const environment = {
    ...process.env,
    HOME: homeDir,
    XDG_CONFIG_HOME: join(homeDir, ".config"),
    NL2SQL_OPENCODE_CONFIG: configPath,
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

    const configure = ["exec", "--offline", "--", "nl2sql-agent", "configure"]
    run("npm", configure, { cwd: projectDir, env: environment })
    const configAfterFirst = readFileSync(configPath, "utf8")
    assert(listBackups(configPath).length === 1, "configure did not create exactly one backup")
    const parsed = parse(configAfterFirst, [], { allowTrailingComma: true, disallowComments: false })
    assert(parsed.theme === "system", "configure did not preserve unrelated settings")
    assert(configAfterFirst.includes("keep-me"), "configure removed an unrelated agent entry")
    assert(configAfterFirst.includes("// Existing settings must survive registration."), "configure removed a comment")
    // Plugin mechanism: registration lands in config.plugin, not config.agent.
    const expectedPluginSpec = pathToFileURL(realpathSync(join(packageRoot, "dist", "index.js"))).href
    assert(Array.isArray(parsed.plugin), "configure did not write a plugin array")
    assert(parsed.plugin.includes(expectedPluginSpec), "configure did not register the nl2sql plugin")
    assert(!parsed.agent?.nl2sql, "configure must not write a direct config.agent entry (plugin mechanism)")
    assert(existsSync(join(packageRoot, "dist", "index.js")), "plugin entry dist/index.js is missing")

    // Skill is exposed via a flat symlink under the opencode skills directory.
    const skillLink = join(dirname(configPath), "skills", "nl2sql")
    assert(lstatSync(skillLink).isSymbolicLink(), "configure did not link the nl2sql skill")
    const linkedSkillRoot = realpathSync(skillLink)
    assert(
      linkedSkillRoot === realpathSync(join(packageRoot, "opencode_plugin", "skills", "nl2sql")),
      "nl2sql skill link does not point at opencode_plugin/skills/nl2sql",
    )
    assert(existsSync(join(linkedSkillRoot, "SKILL.md")), "linked nl2sql skill has no SKILL.md")

    // The plugin loads its role prompt from opencode_plugin at runtime.
    const rolePromptPath = join(packageRoot, "opencode_plugin", "role-prompt.md")
    assert(
      existsSync(rolePromptPath) && readFileSync(rolePromptPath, "utf8").trim().length > 100,
      "opencode_plugin/role-prompt.md is missing or too short",
    )

    // Python backend ships in BOTH variants; only the wheelhouse is offline-only.
    for (const required of ["nl2sql_core", "apps", "requirements.txt", "configs", "fixtures", "scripts", ".env.example"]) {
      assert(existsSync(join(packageRoot, required)), `bundled backend path is missing: ${required}`)
    }
    assert(existsSync(join(packageRoot, "apps", "web", "main.py")), "web entry apps/web/main.py is missing")
    assert(existsSync(join(packageRoot, "scripts", "start_web.sh")), "scripts/start_web.sh is missing")
    const offline = options.variant === "offline"
    if (offline) {
      for (const required of ["python-wheels", "python-wheel-manifest.json"]) {
        assert(existsSync(join(packageRoot, required)), `offline wheelhouse path is missing: ${required}`)
      }
    }
    // setup must succeed in both variants: online pip-installs from PyPI, offline from the wheelhouse.
    const execSetup = (command) => run(
      "npm",
      ["exec", ...(offline ? ["--offline"] : []), "--", "nl2sql-setup", command],
      { cwd: projectDir, env: environment },
    )
    execSetup("install")
    execSetup("check")

    run("npm", configure, { cwd: projectDir, env: environment })
    assert(readFileSync(configPath, "utf8") === configAfterFirst, "repeated configure changed configuration")
    assert(listBackups(configPath).length === 1, "repeated configure created another backup")

    const remove = ["exec", "--offline", "--", "nl2sql-agent", "remove"]
    run("npm", remove, { cwd: projectDir, env: environment })
    const configAfterRemove = readFileSync(configPath, "utf8")
    assert(listBackups(configPath).length === 2, "remove did not create exactly one additional backup")
    const parsedAfterRemove = parse(configAfterRemove, [], { allowTrailingComma: true, disallowComments: false })
    assert(parsedAfterRemove.theme === "system", "remove did not preserve unrelated settings")
    assert(parsedAfterRemove.agent?.["other-agent"], "remove deleted an unrelated agent entry")
    assert(!parsedAfterRemove.agent?.nl2sql, "remove left a direct config.agent entry")
    assert(
      Array.isArray(parsedAfterRemove.plugin) && !parsedAfterRemove.plugin.includes(expectedPluginSpec),
      "remove left the nl2sql plugin registration",
    )
    assert(!existsSync(skillLink), "remove left the nl2sql skill link")

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
      networkIsolation: process.env.NL2SQL_NETWORK_ISOLATION || "none",
      npmInstallPreservedConfig: true,
      pythonBackendBundled: true,
      setupVerified: true,
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