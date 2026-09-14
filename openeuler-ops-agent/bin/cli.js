#!/usr/bin/env node
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { registerAgent, removeAgent, agentStatus, resolveConfigPath } from "../lib/configure.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = join(__dirname, "..");
const arg = process.argv[2] || "configure";

function printUsage() {
  console.log(`Usage:
  openeuler-ops-agent configure   # 注册 Agent 到 opencode 配置（幂等）
  openeuler-ops-agent remove      # 从 opencode 配置移除 Agent（幂等）
  openeuler-ops-agent status      # 查看注册状态
  openeuler-ops-agent install     # 安装底层 Skills（需要网络）
  openeuler-ops-agent verify      # 验证安装完整性
`);
}

function spawnShell(script) {
  const child = spawn("bash", [script], { stdio: "inherit" });
  child.on("exit", (code) => process.exit(code || 0));
}

if (["-h", "--help", "help"].includes(arg)) {
  printUsage();
  process.exit(0);
} else if (arg === "configure" || arg === "register") {
  const result = registerAgent(rootDir, resolveConfigPath());
  console.log(result.changed
    ? `Agent 已注册到 ${result.configPath}`
    : `Agent 已存在，无需变更：${result.configPath}`);
  process.exit(0);
} else if (arg === "remove") {
  const result = removeAgent(resolveConfigPath());
  console.log(result.changed
    ? `Agent 已从 ${result.configPath} 移除`
    : `Agent 未注册，无需变更：${result.configPath}`);
  process.exit(0);
} else if (arg === "status") {
  const result = agentStatus(resolveConfigPath());
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.configured ? 0 : 1);
} else if (arg === "install") {
  spawnShell(join(rootDir, "install.sh"));
} else if (arg === "verify") {
  spawnShell(join(rootDir, "scripts", "verify.sh"));
} else {
  printUsage();
  process.exit(1);
}