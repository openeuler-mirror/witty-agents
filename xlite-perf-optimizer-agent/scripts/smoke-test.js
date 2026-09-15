#!/usr/bin/env node
/**
 * scripts/smoke-test.js
 * Basic structural smoke test for the xlite-perf-optimizer package.
 */
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const expectedSkills = [
  'xlite-analyzer',
  'xlite-ascend-runner',
  'xlite-atomic-journal',
  'xlite-complexity-estimator',
  'xlite-gitcode-runner',
  'xlite-html-reporter',
  'xlite-operator-dev',
  'xlite-profiler',
];

const checks = [];

function assert(cond, message) {
  checks.push({ ok: cond, message });
  if (!cond) {
    console.error(`FAIL: ${message}`);
  } else {
    console.log(`PASS: ${message}`);
  }
}

function exists(p) {
  return fs.existsSync(path.join(root, p));
}

// Package manifest
assert(exists('package.json'), 'package.json exists');
assert(exists('README.md'), 'README.md exists');

// Agent role prompt
assert(exists('agent/agent.md'), 'agent/agent.md exists');

// Skills
for (const skill of expectedSkills) {
  assert(exists(`skills/${skill}/SKILL.md`), `skill ${skill} has SKILL.md`);
}

// Helper scripts
assert(exists('helpers/ascend-container-test.sh'), 'helper ascend-container-test.sh exists');
assert(exists('helpers/parse-perf-log.py'), 'helper parse-perf-log.py exists');

// Unified CLI bins (shennong-style: <agent>-setup + <agent>-configure)
for (const bin of ['bin/xlite-perf-optimizer-setup.mjs', 'bin/configure.mjs']) {
  assert(exists(bin), `${bin} exists`);
  try {
    execFileSync(process.execPath, ['--check', path.join(root, bin)], { stdio: 'pipe' });
    assert(true, `${bin} has valid Node.js syntax`);
  } catch (e) {
    assert(false, `${bin} has valid Node.js syntax`);
  }
}

const failed = checks.filter((c) => !c.ok).length;
console.log(`\n${checks.length - failed}/${checks.length} checks passed`);
process.exit(failed ? 1 : 0);
