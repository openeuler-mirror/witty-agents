#!/usr/bin/env node
// kernel-dataset-configure —— 把 kernel-dataset Agent 注册到 OpenCode（幂等）。
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { registerAgent, removeAgent, agentStatus, resolveConfigPath } from "../lib/configure.mjs"

const __dirname = dirname(fileURLToPath(import.meta.url))
const rootDir = join(__dirname, "..")
const ACTIONS = ["install", "remove", "status"]

function printUsage() {
  console.log(`Usage:
  kernel-dataset-configure [install] [--target opencode]   # 注册 kernel-dataset Agent（幂等，默认动作）
  kernel-dataset-configure remove    [--target opencode]   # 从 opencode 配置移除（幂等）
  kernel-dataset-configure status    [--target opencode]   # 查看注册状态（JSON）

Options:
  --target <name>   目标框架，仅支持 opencode（默认 opencode；all 等价于 opencode）
`)
}

function parseArgs(argv) {
  const options = { action: "install", target: "opencode" }
  let actionSeen = false
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (["-h", "--help", "help"].includes(arg)) {
      printUsage()
      process.exit(0)
    } else if (ACTIONS.includes(arg) && !actionSeen) {
      options.action = arg
      actionSeen = true
    } else if (arg.startsWith("--target=")) {
      options.target = arg.slice("--target=".length)
    } else if (arg === "--target") {
      options.target = argv[++index]
    } else {
      throw new Error(`unknown argument: ${arg}`)
    }
  }
  if (!["opencode", "all"].includes(options.target)) {
    throw new Error("--target must be one of: opencode, all")
  }
  return options
}

function reportLink(link) {
  for (const item of link?.linked || []) {
    if (item.alreadyLinked) console.log(`Skill 已链接（存在）：${item.linkPath}`)
    else if (item.changed) console.log(`Skill 已链接：${item.linkPath}`)
  }
  for (const conflict of link?.conflicts || []) {
    console.error(`Skill 链接冲突（未覆盖）：${conflict.linkPath}`)
    process.exitCode = 1
  }
}

try {
  const options = parseArgs(process.argv.slice(2))
  if (options.action === "install") {
    const result = registerAgent(rootDir, resolveConfigPath())
    console.log(result.changed
      ? `Agent 已注册到 ${result.configPath}`
      : `Agent 已存在，无需变更：${result.configPath}`)
    reportLink(result.link)
  } else if (options.action === "remove") {
    const result = removeAgent(resolveConfigPath())
    console.log(result.changed
      ? `Agent 已从 ${result.configPath} 移除`
      : `Agent 未注册，无需变更：${result.configPath}`)
    for (const item of result.link?.removed || []) console.log(`Skill 链接已移除：${item.linkPath}`)
  } else {
    const result = agentStatus(resolveConfigPath())
    console.log(JSON.stringify(result, null, 2))
    process.exit(result.configured ? 0 : 1)
  }
} catch (error) {
  console.error(`[kernel-dataset-configure] ${error.message}`)
  process.exit(1)
}