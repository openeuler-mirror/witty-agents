#!/usr/bin/env node

import { dirname } from "node:path"
import { fileURLToPath } from "node:url"
import { configureUsage, parseConfigureArgs } from "../lib/configure/common.mjs"
import { getFrameworkAdapters } from "../lib/configure/adapters/index.mjs"

const BIN_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = dirname(BIN_DIR)

function printOpenCodeResult(action, result) {
  if (result.skipped) {
    console.log(`[shennong-configure] OpenCode registration skipped: ${result.reason}`)
  } else if (action === "remove" && result.changed) {
    console.log(`[shennong-configure] Backup created: ${result.backupPath}`)
    console.log(`[shennong-configure] Removed ${result.removedPlugins.length} plugin and ${result.removedMcpNames.length} MCP registration(s) from ${result.configPath}`)
  } else if (action === "remove") {
    console.log(`[shennong-configure] No Shennong registration found in ${result.configPath}`)
  } else if (action === "status") {
    console.log(JSON.stringify({ framework: "opencode", ...result }, null, 2))
  } else if (result.changed) {
    if (result.backupPath) {
      console.log(`[shennong-configure] Backup created: ${result.backupPath}`)
    }
    console.log(`[shennong-configure] Plugin ${result.packageName} registered as ${result.pluginSpec} in ${result.configPath}`)
    console.log(`[shennong-configure] MCP servers registered: ${result.mcpNames.join(", ")}`)
  } else {
    console.log(`[shennong-configure] Plugin ${result.packageName} is already registered as ${result.pluginSpec} in ${result.configPath}`)
    console.log(`[shennong-configure] MCP servers already registered: ${result.mcpNames.join(", ")}`)
  }
}

function printResult(adapter, action, result) {
  if (adapter.id === "opencode" && action !== "sync-skills") {
    printOpenCodeResult(action, result)
    printSkillSync(result.skillSync)
    return
  }
  if (action === "sync-skills") {
    printSkillSync(result.skillSync)
    if (result.skillSync?.error) process.exitCode = 1
    return
  }
  console.log(JSON.stringify({ framework: adapter.id, ...result }, null, 2))
}

function printSkillSync(skillSync) {
  if (!skillSync || !Array.isArray(skillSync.results)) return
  if (skillSync.error) {
    console.warn(`[shennong-configure] skill 同步失败: ${skillSync.error}`)
    return
  }
  for (const r of skillSync.results) {
    if (r.skipped) {
      console.warn(`[shennong-configure] skill ${r.skill} 源目录缺失，跳过（${r.reason}）`)
    } else if (r.changed) {
      console.log(`[shennong-configure] skill ${r.skill} 已同步到 ${skillSync.root}/${r.skill}（${r.files} 个文件）${r.backupPath ? `；旧副本备份: ${r.backupPath}` : ""}`)
    } else {
      console.log(`[shennong-configure] skill ${r.skill} 已是最新（${r.files} 个文件一致），无需同步`)
    }
  }
}

try {
  const options = parseConfigureArgs(process.argv.slice(2))
  if (options.help) {
    console.log(configureUsage())
    process.exit(0)
  }

  const adapters = getFrameworkAdapters(options.target, options.action)
  for (const adapter of adapters) {
    const result = adapter[options.action]({
      packageRoot: PROJECT_ROOT,
      options,
    })
    printResult(adapter, options.action, result)
  }
} catch (error) {
  console.error(`[shennong-configure] ${error.message}`)
  process.exit(1)
}
