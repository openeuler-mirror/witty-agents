#!/usr/bin/env node
import { spawn } from "node:child_process"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const rootDir = join(__dirname, "..")
const COMMANDS = ["install", "check"]

function printUsage() {
  console.log(`Usage:
  openeuler-ops-setup install   # 通过 skillhub 在线安装/更新底层 Skills（默认，需要网络）
  openeuler-ops-setup check     # 只读检查安装完整性（agent.md / skills / 注册配置）

Notes:
  本 Agent 无 Python/后端服务，install 仅准备 skillhub 在线 Skills；
  skillhub 不可用时 install 会降级跳过，不影响 Agent 本体使用。
`)
}

function parseArgs(argv) {
  let command = "install"
  let commandSeen = false
  for (const arg of argv) {
    if (["-h", "--help", "help"].includes(arg)) {
      printUsage()
      process.exit(0)
    } else if (COMMANDS.includes(arg) && !commandSeen) {
      command = arg
      commandSeen = true
    } else {
      console.error(`[openeuler-ops-setup] unknown argument: ${arg}\n`)
      printUsage()
      process.exit(1)
    }
  }
  return command
}

const command = parseArgs(process.argv.slice(2))
const script = command === "check"
  ? join(rootDir, "scripts", "verify.sh")
  : join(rootDir, "install.sh")
const child = spawn("bash", [script], { stdio: "inherit" })
child.on("exit", (code) => process.exit(code || 0))
child.on("error", (error) => {
  console.error(`[openeuler-ops-setup] ${error.message}`)
  process.exit(1)
})
