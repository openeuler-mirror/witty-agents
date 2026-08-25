#!/usr/bin/env node

import { dirname } from "node:path"
import { fileURLToPath } from "node:url"
import { registerOpenCodePlugin } from "./lib/opencode-config.mjs"

const packageRoot = dirname(fileURLToPath(import.meta.url))

try {
  const result = registerOpenCodePlugin(packageRoot)
  if (result.skipped) {
    console.log(`[agent-shennong-crash] OpenCode registration skipped: ${result.reason}`)
  } else if (result.changed) {
    console.log(`[agent-shennong-crash] OpenCode plugin registered in ${result.configPath}`)
  } else {
    console.log(`[agent-shennong-crash] OpenCode plugin already registered in ${result.configPath}`)
  }
  console.log("[agent-shennong-crash] Python dependencies are not installed during npm install.")
  console.log("[agent-shennong-crash] Run: npm exec --offline -- shennong-setup install")
} catch (error) {
  console.error(`[agent-shennong-crash] OpenCode registration failed: ${error.message}`)
  console.error("[agent-shennong-crash] Fix the config or set SHENNONG_SKIP_CONFIG=1 and register later with shennong-setup register.")
  process.exit(1)
}
