#!/usr/bin/env node

const path = require('path');

const initCmd = 'npx xlite-opt-init';
const pkgName = path.basename(path.dirname(__dirname));

console.log(`\n[${pkgName}] 已安装。\n`);
console.log(`请在需要使用的 xlite 项目根目录下执行初始化命令：\n`);
console.log(`  ${initCmd}\n`);
console.log(`该命令会：`);
console.log(`  1. 将 Agent role prompt 安装到 ~/.config/opencode/agents/xlite-perf-optimizer/`);
console.log(`  2. 将内置 skill 安装到 ~/.config/opencode/skills/`);
console.log(`  3. 在当前项目的 opencode.jsonc 中追加 agent 配置`);
console.log(`  4. 在当前项目创建 .xlite-opt/journal/ 与 .xlite-opt/reports/\n`);
