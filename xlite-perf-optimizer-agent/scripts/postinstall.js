#!/usr/bin/env node
// Dormant hint script (the package deliberately declares no npm postinstall
// hook; npm install stays side-effect free). Kept ESM-valid for manual use.
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pkgName = path.basename(path.dirname(__dirname));

console.log(`\n[${pkgName}] 已安装。\n`);
console.log(`统一安装流程（与其他 Agent 一致）：\n`);
console.log('  xlite-perf-optimizer-setup install');
console.log('  xlite-perf-optimizer-configure install --target=opencode\n');
console.log(`说明：`);
console.log(`  1. setup 无后端依赖，仅做包完整性校验`);
console.log(`  2. configure 以 plugin 方式注册并软链内置 Skills（幂等，可重复执行）`);
console.log(`  3. 反注册执行 xlite-perf-optimizer-configure remove\n`);
