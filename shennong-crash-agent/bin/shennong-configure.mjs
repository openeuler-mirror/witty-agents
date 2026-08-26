#!/usr/bin/env node

import { dirname } from "node:path"
import { fileURLToPath } from "node:url"
import { registerOpenCodePlugin, removeOpenCodePlugin } from "../lib/opencode-config.mjs"

const BIN_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = dirname(BIN_DIR)
const action = process.argv[2] || "install"

if (["--help", "-h", "help"].includes(action)) {
  console.log(`Usage:
  shennong-configure [install]  Register this installed package in OpenCode
  shennong-configure remove     Remove Shennong registrations from OpenCode`)
  process.exit(0)
}

if (!["install", "remove"].includes(action)) {
  console.error(`[shennong-configure] unknown action: ${action}`)
  process.exit(2)
}

try {
  const result = action === "remove"
    ? removeOpenCodePlugin()
    : registerOpenCodePlugin(PROJECT_ROOT)
  if (result.skipped) {
    console.log(`[shennong-configure] OpenCode registration skipped: ${result.reason}`)
  } else if (action === "remove" && result.changed) {
    console.log(`[shennong-configure] Backup created: ${result.backupPath}`)
    console.log(`[shennong-configure] Removed ${result.removedPlugins.length} plugin and ${result.removedMcpNames.length} MCP registration(s) from ${result.configPath}`)
  } else if (action === "remove") {
    console.log(`[shennong-configure] No Shennong registration found in ${result.configPath}`)
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
} catch (error) {
  console.error(`[shennong-configure] ${error.message}`)
  process.exit(1)
}
