#!/usr/bin/env node
/**
 * scripts/smoke-test.js
 * Basic structural smoke test for the xlite-perf-optimizer package.
 */
const fs = require('fs');
const path = require('path');

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

// Init script
assert(exists('bin/xlite-opt-init.js'), 'bin/xlite-opt-init.js exists');

// Init script syntax: run node --check
const initFile = path.join(root, 'bin/xlite-opt-init.js');
try {
  require('child_process').execFileSync(process.execPath, ['--check', initFile], { stdio: 'pipe' });
  assert(true, 'xlite-opt-init.js has valid Node.js syntax');
} catch (e) {
  assert(false, 'xlite-opt-init.js has valid Node.js syntax');
}

// Local opencode config has the agent (if present)
const opencodePath = path.join(process.cwd(), 'opencode.jsonc');
if (fs.existsSync(opencodePath)) {
  const configText = fs.readFileSync(opencodePath, 'utf-8');
  assert(configText.includes('xlite-perf-optimizer'), 'opencode.jsonc references xlite-perf-optimizer');
  const promptMatch = configText.match(/"xlite-perf-optimizer"[\s\S]*?"prompt"\s*:\s*"\{file:([^}]+)\}"/);
  if (promptMatch) {
    const promptFile = promptMatch[1];
    assert(fs.existsSync(promptFile), `agent prompt file exists: ${promptFile}`);
  } else {
    assert(false, 'agent prompt file reference is parseable');
  }
} else {
  assert(false, 'opencode.jsonc exists in current working directory');
}

const failed = checks.filter((c) => !c.ok).length;
console.log(`\n${checks.length - failed}/${checks.length} checks passed`);
process.exit(failed ? 1 : 0);
