#!/usr/bin/env node

import { dirname } from "node:path"
import { fileURLToPath } from "node:url"
import { registerOpenCodePlugin } from "../lib/opencode-config.mjs"

const BIN_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = dirname(BIN_DIR)

try {
  const result = registerOpenCodePlugin(PROJECT_ROOT)
  if (result.skipped) {
    console.log(`[shennong-configure] OpenCode registration skipped: ${result.reason}`)
  } else if (result.changed) {
    if (result.backupPath) {
      console.log(`[shennong-configure] Backup created: ${result.backupPath}`)
    }
    console.log(`[shennong-configure] Plugin ${result.packageName} registered in ${result.configPath}`)
  } else {
    console.log(`[shennong-configure] Plugin ${result.packageName} is already registered in ${result.configPath}`)
  }
} catch (error) {
  console.error(`[shennong-configure] ${error.message}`)
  process.exit(1)
}
