#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { packageRoot, python } from '../lib/runtime.mjs';
if (!existsSync(python)) {
  console.error('Run vllm-benchmark-setup install first.');
  process.exit(1);
}
const child = spawn(python, [join(packageRoot, 'agent', 'main.py'), ...process.argv.slice(2)], {
  stdio: 'inherit', env: {...process.env, PYTHONDONTWRITEBYTECODE: '1'},
});
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', (code, signal) => { process.exitCode = code ?? (signal ? 1 : 0); });
