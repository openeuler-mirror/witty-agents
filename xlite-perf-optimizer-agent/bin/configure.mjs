#!/usr/bin/env node
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { registerAgent, removeAgent, agentStatus, resolveConfigPath } from "../lib/configure.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = join(__dirname, "..");
const ACTIONS = ["install", "remove", "status"];

function printUsage() {
  console.log(`Usage:
  xlite-perf-optimizer-configure [install] [--target opencode]   # 注册 Agent 到 opencode 配置（幂等，默认动作）
  xlite-perf-optimizer-configure remove    [--target opencode]   # 从 opencode 配置移除 Agent（幂等）
  xlite-perf-optimizer-configure status    [--target opencode]   # 查看注册状态（JSON）

Options:
  --target <name>   目标框架，仅支持 opencode（默认 opencode；all 等价于 opencode）
`);
}

function parseArgs(argv) {
  const options = { action: "install", target: "opencode" };
  let actionSeen = false;
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (["-h", "--help", "help"].includes(arg)) {
      printUsage();
      process.exit(0);
    } else if (ACTIONS.includes(arg) && !actionSeen) {
      options.action = arg;
      actionSeen = true;
    } else if (arg.startsWith("--target=")) {
      options.target = arg.slice("--target=".length);
    } else if (arg === "--target") {
      options.target = argv[++index];
    } else {
      console.error(`[xlite-perf-optimizer-configure] unknown argument: ${arg}\n`);
      printUsage();
      process.exit(1);
    }
  }
  if (!["opencode", "all"].includes(options.target)) {
    console.error("[xlite-perf-optimizer-configure] --target must be one of: opencode, all");
    process.exit(1);
  }
  return options;
}

const options = parseArgs(process.argv.slice(2));

if (options.action === "install") {
  const result = registerAgent(rootDir, resolveConfigPath());
  console.log(result.changed
    ? `Agent 已注册到 ${result.configPath}`
    : `Agent 已存在，无需变更：${result.configPath}`);
  process.exit(0);
} else if (options.action === "remove") {
  const result = removeAgent(resolveConfigPath());
  console.log(result.changed
    ? `Agent 已从 ${result.configPath} 移除`
    : `Agent 未注册，无需变更：${result.configPath}`);
  process.exit(0);
} else {
  const result = agentStatus(resolveConfigPath());
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.configured ? 0 : 1);
}
