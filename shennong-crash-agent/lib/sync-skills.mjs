#!/usr/bin/env node
/**
 * 把安装包内 skills/<name> 强制同步到用户级 skill 目录 ~/.config/opencode/skills/<name>。
 *
 * 背景（历史踩坑）：OpenCode 对同名 skill 解析到用户级目录的副本，而不是安装包内的
 * skills/；仅升级 npm 包不会更新该副本，导致“改了源码/重装了包，行为仍是旧规则”。
 *
 * 策略（与用户约定）：强制覆盖 + 时间戳备份。
 * - 内容有差异才覆盖，覆盖前把旧副本整体备份到 <skill>.bak-<时间戳>/；
 * - 排除 __pycache__ / .venv 等运行期目录；
 * - 幂等：内容一致时零输出、不产生备份。
 */

import {
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  rmSync,
  statSync,
} from "node:fs"
import { join } from "node:path"
import { homedir } from "node:os"

const EXCLUDES = new Set(["__pycache__", ".venv", "node_modules"])

function listFiles(dir, base = dir, acc = []) {
  for (const name of readdirSync(dir)) {
    if (EXCLUDES.has(name)) continue
    const full = join(dir, name)
    const st = statSync(full)
    if (st.isDirectory()) listFiles(full, base, acc)
    else acc.push({ rel: full.slice(base.length + 1), mtime: st.mtimeMs, size: st.size })
  }
  return acc
}

function snapshot(root) {
  if (!existsSync(root)) return []
  return listFiles(root).sort((a, b) => a.rel.localeCompare(b.rel))
}

function sameSnapshot(a, b) {
  if (a.length !== b.length) return false
  return a.every((f, i) => f.rel === b[i].rel && f.size === b[i].size)
}

function copyTree(src, dst) {
  rmSync(dst, { recursive: true, force: true })
  mkdirSync(dst, { recursive: true })
  cpSync(src, dst, {
    recursive: true,
    filter: (s) => {
      const parts = String(s).split("/")
      return !EXCLUDES.has(parts[parts.length - 1])
    },
  })
}

/**
 * 同步单个 skill；返回 { skill, changed, backupPath?, files } 。
 */
export function syncSkill(packageRoot, skillName, userSkillsRoot) {
  const src = join(packageRoot, "skills", skillName)
  if (!existsSync(src)) {
    return { skill: skillName, changed: false, skipped: true, reason: "source missing" }
  }
  const dst = join(userSkillsRoot, skillName)
  const before = snapshot(dst)
  const incoming = snapshot(src)
  if (sameSnapshot(before, incoming)) {
    return { skill: skillName, changed: false, files: incoming.length }
  }
  let backupPath = ""
  if (existsSync(dst)) {
    const stamp = new Date().toISOString().replace(/[:.]/g, "-")
    backupPath = `${dst}.bak-${stamp}`
    copyTree(dst, backupPath)
  } else {
    mkdirSync(userSkillsRoot, { recursive: true })
  }
  copyTree(src, dst)
  return { skill: skillName, changed: true, backupPath, files: incoming.length }
}

/** 同步安装包内全部核心 skill；返回汇总（供 configure 打印）。 */
export function syncAllSkills(packageRoot, skillNames, userSkillsRoot) {
  const root = userSkillsRoot || join(homedir(), ".config", "opencode", "skills")
  const results = skillNames.map((name) => syncSkill(packageRoot, name, root))
  return { root, results }
}
