#!/usr/bin/env node
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { registerAgent, removeAgent, agentStatus, resolveConfigPath } from "../lib/configure.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = join(__dirname, "..");
const arg = process.argv[2] || "register";

function printUsage() {
  console.log(`Usage:
  xlite-perf-optimizer-configure register   # 注册 Agent 到 opencode 配置（幂等）
  xlite-perf-optimizer-configure remove     # 从 opencode 配置移除 Agent（幂等）
  xlite-perf-optimizer-configure status     # 查看注册状态
`);
}

if (["-h", "--help", "help"].includes(arg)) {
  printUsage();
  process.exit(0);
} else if (arg === "register" || arg === "configure") {
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
} else {
  printUsage();
  process.exit(1);
}