import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, symlinkSync, lstatSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import plugin from '../dist/index.js';
import { packageRoot, python } from '../lib/runtime.mjs';
import { registerAgent, removeAgent } from '../lib/configure.mjs';

test('plugin registers runtime, configuration agent and command, preserving other entries', async () => {
  const config = {agent: {existing: {prompt: 'keep'}}, command: {existing: {template: 'keep'}}};
  await (await plugin({})).config(config);
  assert.equal(config.agent.existing.prompt, 'keep');
  assert.equal(config.command.existing.template, 'keep');
  assert.equal(config.command.benchmark_config.agent, 'benchmark-config');
  assert.equal(config.agent['vllm-benchmark'].mode, 'primary');
  assert.ok(config.agent['vllm-benchmark'].prompt.includes(join(packageRoot, 'bin', 'vllm-benchmark.mjs')));
});

test('configuration conflicts preserve user files and unrelated plugin paths', () => {
  const root = mkdtempSync(join(tmpdir(), 'vllm-config-'));
  const path = join(root, 'opencode.jsonc');
  const previous = process.env.VLLM_BENCHMARK_OPENCODE_CONFIG;
  process.env.VLLM_BENCHMARK_OPENCODE_CONFIG = path;
  try {
    const raw = '{"plugin":["file:///tmp/other-vllm-benchmark-plugin/dist/index.js"]}';
    writeFileSync(path, raw);
    mkdirSync(join(root, 'skills', 'vllm-benchmark'), {recursive: true});
    assert.throws(() => registerAgent(packageRoot), /belongs to user/);
    assert.equal(readFileSync(path, 'utf8'), raw);
    rmSync(join(root, 'skills', 'vllm-benchmark'), {recursive: true});
    symlinkSync('/tmp/missing/agent-vllm-benchmark/skills/vllm-benchmark', join(root, 'skills', 'vllm-benchmark'));
    registerAgent(packageRoot);
    assert.ok(lstatSync(join(root, 'skills', 'vllm-benchmark')).isSymbolicLink());
    removeAgent();
    assert.deepEqual(JSON.parse(readFileSync(path, 'utf8')).plugin, JSON.parse(raw).plugin);
  } finally {
    if (previous === undefined) delete process.env.VLLM_BENCHMARK_OPENCODE_CONFIG;
    else process.env.VLLM_BENCHMARK_OPENCODE_CONFIG = previous;
    rmSync(root, {recursive: true, force: true});
  }
});

test('runner defaults use consumer config and XDG data, outside the package', () => {
  const root = mkdtempSync(join(tmpdir(), 'vllm-consumer-'));
  try {
    const env = {...process.env, HOME: root, XDG_DATA_HOME: join(root, 'data'), PYTHONDONTWRITEBYTECODE: '1'};
    delete env.VLLM_BENCHMARK_CONFIG;
    delete env.VLLM_BENCHMARK_DATA_DIR;
    const result = JSON.parse(execFileSync(python, ['-c', `import sys,json; sys.path.insert(0,${JSON.stringify(packageRoot)}); from agent import main; from tools import config; print(json.dumps([main.DEFAULT_CONFIG,config.DEFAULT_CONFIG_PATH,main.DATA_ROOT,main.UI_POINTER_PATH]))`], {cwd: root, env, encoding: 'utf8'}));
    assert.deepEqual(result, [join(root, 'benchmark.yaml'), join(root, 'benchmark.yaml'), join(root, 'data', 'witty-agents', 'vllm-benchmark'), join(root, '.vllm-benchmark', 'current.json')]);
  } finally { rmSync(root, {recursive: true, force: true}); }
});
