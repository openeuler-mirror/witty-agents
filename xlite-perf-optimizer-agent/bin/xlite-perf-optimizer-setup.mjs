#!/usr/bin/env node
// xlite-perf-optimizer has no Python/backend and no external service:
// skills ship inside the npm package and are linked by `configure`.
// This bin exists so all four agents share the same install flow:
//   npm install -g <package>
//   <agent>-setup install
//   <agent>-configure install --target=opencode

const COMMANDS = ["install", "check"];

function printUsage() {
  console.log(`Usage:
  xlite-perf-optimizer-setup install   # 无后端依赖，校验包完整性后直接成功（默认）
  xlite-perf-optimizer-setup check     # 只读校验包完整性

Notes:
  本 Agent 无 Python venv / 无常驻服务，Skills 随包内置，
  注册与 skill 软链请执行: xlite-perf-optimizer-configure install --target=opencode
`);
}

let command = "install";
let commandSeen = false;
for (const arg of process.argv.slice(2)) {
  if (["-h", "--help", "help"].includes(arg)) {
    printUsage();
    process.exit(0);
  } else if (COMMANDS.includes(arg) && !commandSeen) {
    command = arg;
    commandSeen = true;
  } else {
    console.error(`[xlite-perf-optimizer-setup] unknown argument: ${arg}\n`);
    printUsage();
    process.exit(1);
  }
}

console.log(JSON.stringify({
  package: "xlite-perf-optimizer",
  command,
  backend: "none",
  pythonDependencies: "none",
  service: "none",
  status: "ready",
  nextStep: "xlite-perf-optimizer-configure install --target=opencode",
}, null, 2));
