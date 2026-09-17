#!/usr/bin/env node
// 真实安装校验：临时 HOME/项目里 npm install 产物包，验证
// npm install 无副作用 → setup install/check 幂等 → configure install/remove 幂等 → setup stop → uninstall。
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
    ? execFileSync("find", [directory, "-maxdepth", "1", "-name", `${basename(configPath)}.kernel-dataset-backup-*`], { encoding: "utf8" })
        .trim().split("\n").filter(Boolean).sort()
    : []
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  const startedAt = Date.now()
  const workdir = mkdtempSync(join(tmpdir(), `kernel-dataset-real-${options.variant}-`))
  const projectDir = join(workdir, "consumer")
  const homeDir = join(workdir, "home")
  const dataRoot = join(workdir, "data")
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
  mkdirSync(dataRoot, { recursive: true })
  writeFileSync(join(projectDir, "package.json"), `${JSON.stringify({ name: `kernel-dataset-${options.variant}-consumer`, private: true }, null, 2)}\n`)
  writeFileSync(configPath, initialConfig)

  const environment = {
    ...process.env,
    HOME: homeDir,
    XDG_CONFIG_HOME: join(homeDir, ".config"),
    KERNEL_DATASET_OPENCODE_CONFIG: configPath,
    // 真实数据目录不在校验范围内：把落盘根目录钉在临时沙箱里
    KERNEL_DATASET_ROOT: dataRoot,
    KERNEL_DATASET_INTERVAL_MS: "3600000",
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
    assert(!existsSync(join(packageRoot, ".runtime")), "npm install produced runtime side effects")

    // setup：幂等准备 + 环境自检
    const setup = ["exec", "--offline", "--", "kernel-dataset-setup"]
    run("npm", [...setup, "install"], { cwd: projectDir, env: environment })
    assert(existsSync(join(packageRoot, ".runtime", "setup-complete.json")), "setup install did not write the marker file")
    run("npm", [...setup, "install"], { cwd: projectDir, env: environment })
    const checkOutput = run("npm", [...setup, "check"], { cwd: projectDir, env: environment, encoding: "utf8" })
    const checkReport = JSON.parse(checkOutput)
    assert(checkReport.status === "ready", `setup check did not report ready: ${checkOutput}`)
    assert(checkReport.dataRoot === dataRoot, "setup check ignored KERNEL_DATASET_ROOT")
    assert(checkReport.datasets.length === 5, `setup check reported ${checkReport.datasets.length} datasets, expected 5`)
    const statusOutput = run("npm", [...setup, "status"], { cwd: projectDir, env: environment, encoding: "utf8" })
    assert(JSON.parse(statusOutput).state === "stopped", `expected stopped service, got: ${statusOutput}`)
    run("npm", [...setup, "stop"], { cwd: projectDir, env: environment })

    // configure：注册 → 幂等 → 移除 → 幂等
    const configure = ["exec", "--offline", "--", "kernel-dataset-configure", "install"]
    run("npm", configure, { cwd: projectDir, env: environment })
    const configAfterFirst = readFileSync(configPath, "utf8")
    assert(listBackups(configPath).length === 1, "configure did not create exactly one backup")
    const parsed = parse(configAfterFirst, [], { allowTrailingComma: true, disallowComments: false })
    assert(parsed.theme === "system", "configure did not preserve unrelated settings")
    assert(configAfterFirst.includes("keep-me"), "configure removed an unrelated agent entry")
    assert(configAfterFirst.includes("// Existing settings must survive registration."), "configure removed a comment")
    // 插件机制：注册落在 config.plugin，而不是 config.agent
    const expectedPluginSpec = pathToFileURL(realpathSync(join(packageRoot, "dist", "index.js"))).href
    assert(Array.isArray(parsed.plugin), "configure did not write a plugin array")
    assert(parsed.plugin.includes(expectedPluginSpec), "configure did not register the kernel-dataset plugin")
    assert(!parsed.agent?.["kernel-dataset"], "configure must not write a direct config.agent entry (plugin mechanism)")
    assert(existsSync(join(packageRoot, "dist", "index.js")), "plugin entry dist/index.js is missing")

    // skill 以扁平符号链接暴露给 opencode
    const skillLink = join(dirname(configPath), "skills", "kernel-dataset")
    assert(lstatSync(skillLink).isSymbolicLink(), "configure did not link the kernel-dataset skill")
    const linkedSkillRoot = realpathSync(skillLink)
    assert(
      linkedSkillRoot === realpathSync(join(packageRoot, "skills", "kernel-dataset")),
      "kernel-dataset skill link does not point at the packaged skill",
    )
    assert(existsSync(join(linkedSkillRoot, "SKILL.md")), "linked kernel-dataset skill has no SKILL.md")

    const agentPromptPath = join(packageRoot, "agent", "agent.md")
    assert(
      existsSync(agentPromptPath) && readFileSync(agentPromptPath, "utf8").trim().length > 100,
      "agent/agent.md is missing or too short",
    )

    run("npm", configure, { cwd: projectDir, env: environment })
    assert(readFileSync(configPath, "utf8") === configAfterFirst, "repeated configure changed configuration")
    assert(listBackups(configPath).length === 1, "repeated configure created another backup")

    const remove = ["exec", "--offline", "--", "kernel-dataset-configure", "remove"]
    run("npm", remove, { cwd: projectDir, env: environment })
    const configAfterRemove = readFileSync(configPath, "utf8")
    assert(listBackups(configPath).length === 2, "remove did not create exactly one additional backup")
    const parsedAfterRemove = parse(configAfterRemove, [], { allowTrailingComma: true, disallowComments: false })
    assert(parsedAfterRemove.theme === "system", "remove did not preserve unrelated settings")
    assert(parsedAfterRemove.agent?.["other-agent"], "remove deleted an unrelated agent entry")
    assert(!parsedAfterRemove.agent?.["kernel-dataset"], "remove left a direct config.agent entry")
    assert(
      Array.isArray(parsedAfterRemove.plugin) && !parsedAfterRemove.plugin.includes(expectedPluginSpec),
      "remove left the kernel-dataset plugin registration",
    )
    assert(!existsSync(skillLink), "remove left the kernel-dataset skill link")

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
      networkIsolation: process.env.KERNEL_DATASET_NETWORK_ISOLATION || "none",
      npmInstallPreservedConfig: true,
      npmInstallSideEffectFree: true,
      setupCheckStatus: checkReport.status,
      serviceState: "stopped",
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