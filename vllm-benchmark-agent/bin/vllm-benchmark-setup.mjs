#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { packageRoot, venv, python } from '../lib/runtime.mjs';
const args = process.argv.slice(2);
if (args.length === 1 && ['--help', '-h', 'help'].includes(args[0])) {
  console.log('vllm-benchmark-setup [install|check]\nPython 3.10+; PYTHON_BIN selects the interpreter; VLLM_BENCHMARK_VENV selects the venv.');
  process.exit(0);
}
const command = args[0] || 'install';
if (args.length > 1 || !['install', 'check'].includes(command)) throw new Error('expected install or check');
const requirements = join(packageRoot, 'requirements.txt');
const pins = readFileSync(requirements, 'utf8').trim().split('\n').map(line => line.split('=='));
const check = 'import sys, importlib.metadata as m; assert sys.version_info >= (3,10); ' + pins.map(([name, version]) => `assert m.version(${JSON.stringify(name)}) == ${JSON.stringify(version)}`).join('; ') + '; import yaml, matplotlib';
function ready() {
  if (!existsSync(python)) return false;
  try { execFileSync(python, ['-c', check], {stdio: 'pipe'}); return true; } catch { return false; }
}
try {
  for (const file of ['agent/main.py', 'tools/config.py', 'workflow/benchmark.yaml', 'dist/index.js']) {
    if (!existsSync(join(packageRoot, file))) throw new Error(`missing package file: ${file}`);
  }
  if (!ready() && command === 'install') {
    const interpreter = process.env.PYTHON_BIN || 'python3';
    execFileSync(interpreter, ['-c', 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'], {stdio: 'inherit'});
    let hasPip = false;
    if (existsSync(python)) {
      try { execFileSync(python, ['-m', 'pip', '--version'], {stdio: 'pipe'}); hasPip = true; } catch {}
    }
    if (!hasPip) {
      try {
        execFileSync(interpreter, ['-c', 'import ensurepip'], {stdio: 'pipe'});
        execFileSync(interpreter, ['-m', 'venv', venv], {stdio: 'inherit'});
      } catch {
        try { execFileSync(interpreter, ['-m', 'virtualenv', venv], {stdio: 'inherit'}); }
        catch { throw new Error('Python needs venv/ensurepip or virtualenv; install your OS python3-venv package or select a prepared interpreter with PYTHON_BIN'); }
      }
    }
    execFileSync(python, ['-m', 'pip', 'install', '--disable-pip-version-check', '-r', requirements,
      ...(process.env.PYPI_INDEX_URL ? ['--index-url', process.env.PYPI_INDEX_URL] : [])], {stdio: 'inherit'});
  }
  if (!ready()) throw new Error('Python environment is not ready; run vllm-benchmark-setup install');
  console.log(JSON.stringify({package: 'vllm-benchmark', command, backend: 'python', venv, status: 'ready'}, null, 2));
} catch (error) { console.error(error.message); process.exit(1); }
