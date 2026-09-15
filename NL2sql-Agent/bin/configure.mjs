#!/usr/bin/env node
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { registerAgent, removeAgent, agentStatus, resolveConfigPath } from "../lib/configure.mjs"

const __dirname = dirname(fileURLToPath(import.meta.url))
const rootDir = join(__dirname, "..")
const arg = process.argv[2] || "configure"

function printUsage() {
  console.log(`Usage:
  nl2sql-agent configure   # 注册 nl2sql Agent 到 opencode 配置（幂等）
  nl2sql-agent remove      # 从 opencode 配置移除 nl2sql Agent（幂等）
  nl2sql-agent status      # 查看注册状态
`)
}

if (["-h", "--help", "help"].includes(arg)) {
  printUsage()
  process.exit(0)
} else if (arg === "configure" || arg === "register") {
  const result = registerAgent(rootDir, resolveConfigPath())
  console.log(result.changed
    ? `Agent 已注册到 ${result.configPath}`
    : `Agent 已存在，无需变更：${result.configPath}`)
  if (result.link?.alreadyLinked) {
    console.log(`Skill 已链接（存在）：${result.link.linkPath}`)
  } else if (result.link?.changed) {
    console.log(`Skill 已链接：${result.link.linkPath}`)
  } else if (result.link?.conflict) {
    console.error(`Skill 链接冲突（未覆盖）：${result.link.conflict}`)
    process.exitCode = 1
  }
  process.exit(0)
} else if (arg === "remove") {
  const result = removeAgent(resolveConfigPath())
  console.log(result.changed
    ? `Agent 已从 ${result.configPath} 移除`
    : `Agent 未注册，无需变更：${result.configPath}`)
  if (result.link?.changed) console.log(`Skill 链接已移除：${result.link.linkPath}`)
  process.exit(0)
} else if (arg === "status") {
  const result = agentStatus(resolveConfigPath())
  console.log(JSON.stringify(result, null, 2))
  process.exit(result.configured ? 0 : 1)
} else {
  printUsage()
  process.exit(1)
}