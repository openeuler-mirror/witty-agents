#!/usr/bin/env node

/**
 * xlite-opt-init
 *
 * 在当前 xlite 项目初始化 xlite-perf-optimizer Agent：
 * 1. 将 agent.md 安装到 ~/.config/opencode/agents/xlite-perf-optimizer/
 * 2. 将内置 skill 安装到 ~/.config/opencode/skills/
 * 3. 在当前项目 opencode.jsonc 中追加 agent 配置
 * 4. 在当前项目创建 .xlite-opt/journal/ 与 .xlite-opt/reports/
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const PACKAGE_ROOT = path.resolve(__dirname, '..');
const AGENT_NAME = 'xlite-perf-optimizer';
const GLOBAL_CONFIG_DIR = path.join(os.homedir(), '.config', 'opencode');
const GLOBAL_AGENT_DIR = path.join(GLOBAL_CONFIG_DIR, 'agents', AGENT_NAME);
const GLOBAL_SKILLS_DIR = path.join(GLOBAL_CONFIG_DIR, 'skills');

function mkdirp(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function copyFile(src, dst) {
  mkdirp(path.dirname(dst));
  fs.copyFileSync(src, dst);
}

function copyDir(srcDir, dstDir) {
  mkdirp(dstDir);
  const entries = fs.readdirSync(srcDir, { withFileTypes: true });
  for (const entry of entries) {
    const src = path.join(srcDir, entry.name);
    const dst = path.join(dstDir, entry.name);
    if (entry.isDirectory()) {
      copyDir(src, dst);
    } else {
      copyFile(src, dst);
    }
  }
}

function findProjectRoot() {
  let dir = process.cwd();
  while (dir !== path.dirname(dir)) {
    if (fs.existsSync(path.join(dir, 'opencode.jsonc')) ||
        fs.existsSync(path.join(dir, 'package.json')) ||
        fs.existsSync(path.join(dir, 'csrc')) ||
        fs.existsSync(path.join(dir, 'xlite'))) {
      return dir;
    }
    dir = path.dirname(dir);
  }
  return process.cwd();
}

function stripJsoncComments(text) {
  let result = '';
  let inString = false;
  let inLineComment = false;
  let inBlockComment = false;
  let escaped = false;

  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    const next = text[i + 1];

    if (inLineComment) {
      if (c === '\n') {
        inLineComment = false;
        result += c;
      }
      continue;
    }

    if (inBlockComment) {
      if (c === '*' && next === '/') {
        inBlockComment = false;
        i++;
      }
      continue;
    }

    if (inString) {
      result += c;
      if (escaped) {
        escaped = false;
      } else if (c === '\\') {
        escaped = true;
      } else if (c === '"') {
        inString = false;
      }
      continue;
    }

    if (c === '"') {
      inString = true;
      result += c;
    } else if (c === '/' && next === '/') {
      inLineComment = true;
      i++;
    } else if (c === '/' && next === '*') {
      inBlockComment = true;
      i++;
    } else {
      result += c;
    }
  }

  return result;
}

function readJsonc(filePath) {
  const raw = fs.readFileSync(filePath, 'utf-8');
  return JSON.parse(stripJsoncComments(raw));
}

function agentEntryExists(config) {
  return config && config.agent && config.agent[AGENT_NAME] !== undefined;
}

function backupProjectJsonc(projectJsoncPath) {
  if (!fs.existsSync(projectJsoncPath)) return;
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  const backupPath = `${projectJsoncPath}.bak-${ts}`;
  fs.copyFileSync(projectJsoncPath, backupPath);
  console.log(`  ✓ 已备份原配置 -> ${backupPath}`);
}

function mergeAgentConfig(projectJsoncPath, force = false) {
  const snippet = readJsonc(path.join(PACKAGE_ROOT, 'agent', 'opencode-agent.jsonc'));
  let config = {};
  const existed = fs.existsSync(projectJsoncPath);

  if (existed) {
    try {
      config = readJsonc(projectJsoncPath);
    } catch (err) {
      console.error(`[${AGENT_NAME}] 解析 ${projectJsoncPath} 失败：${err.message}`);
      console.error(`请手动将 agent 配置合并到该文件。`);
      process.exit(1);
    }
  }

  if (agentEntryExists(config)) {
    if (!force) {
      console.log(`[${AGENT_NAME}] agent 配置已存在于 ${projectJsoncPath}，跳过写入。`);
      console.log(`        如需强制更新 skill 列表或 prompt 路径，请使用 --force。`);
      return;
    }
    console.log(`[${AGENT_NAME}] --force 已开启，将覆盖已有 agent 配置。`);
  }

  if (!config.agent) {
    config.agent = {};
  }

  // 使用全局绝对路径作为 prompt 引用
  const agentMdPath = path.join(GLOBAL_AGENT_DIR, 'agent.md');
  const entry = JSON.parse(JSON.stringify(snippet.agent[AGENT_NAME]));
  entry.prompt = `{file:${agentMdPath}}`;
  config.agent[AGENT_NAME] = entry;

  backupProjectJsonc(projectJsoncPath);
  const newRaw = JSON.stringify(config, null, 2) + '\n';
  fs.writeFileSync(projectJsoncPath, newRaw, 'utf-8');
  console.log(`[${AGENT_NAME}] 已${force ? '覆盖' : '追加'} agent 配置到 ${projectJsoncPath}`);
  if (existed) {
    console.log(`  提示：JSONC 回写为纯 JSON，原文件中的注释已丢失；如需恢复，请使用上方生成的 .bak 备份。`);
  }
}

function main() {
  const force = process.argv.includes('--force');
  if (force) {
    console.log(`[${AGENT_NAME}] 检测到 --force 标志，将强制更新 agent 配置。`);
  }
  console.log(`\n[${AGENT_NAME}] 正在初始化...\n`);

  // 1. 安装 agent.md 到全局
  mkdirp(GLOBAL_AGENT_DIR);
  copyFile(
    path.join(PACKAGE_ROOT, 'agent', 'agent.md'),
    path.join(GLOBAL_AGENT_DIR, 'agent.md')
  );
  console.log(`  ✓ agent.md -> ${GLOBAL_AGENT_DIR}`);

  // 2. 安装 skill 到全局
  const srcSkillsDir = path.join(PACKAGE_ROOT, 'skills');
  const skillNames = fs.readdirSync(srcSkillsDir, { withFileTypes: true })
    .filter(e => e.isDirectory())
    .map(e => e.name);

  for (const skillName of skillNames) {
    const src = path.join(srcSkillsDir, skillName);
    const dst = path.join(GLOBAL_SKILLS_DIR, skillName);
    copyDir(src, dst);
    console.log(`  ✓ skill ${skillName} -> ${dst}`);
  }

  // 3. 合并 opencode.jsonc
  const projectRoot = findProjectRoot();
  const projectJsoncPath = path.join(projectRoot, 'opencode.jsonc');
  mergeAgentConfig(projectJsoncPath, force);

  // 4. 创建项目级工作目录
  const journalDir = path.join(projectRoot, '.xlite-opt', 'journal');
  const reportsDir = path.join(projectRoot, '.xlite-opt', 'reports');
  mkdirp(journalDir);
  mkdirp(reportsDir);
  console.log(`  ✓ 原子记录目录 -> ${journalDir}`);
  console.log(`  ✓ 报告输出目录 -> ${reportsDir}`);

  console.log(`\n[${AGENT_NAME}] 初始化完成。`);
  console.log(`\n下一步：在 opencode 中选择 agent '${AGENT_NAME}'，然后输入优化任务。\n`);
}

main();
