#!/usr/bin/env node

import { existsSync, readFileSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { validatePlugin } from "../lib/validate-plugin.mjs"

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = resolve(SCRIPT_DIR, "..")
const PACKAGE_JSON = join(PROJECT_ROOT, "package.json")
const DIST_ENTRY = join(PROJECT_ROOT, "dist", "index.js")

if (!existsSync(DIST_ENTRY)) {
  throw new Error(`prebuilt plugin entry is missing: ${DIST_ENTRY}`)
}

const packageJson = JSON.parse(readFileSync(PACKAGE_JSON, "utf8"))
if (packageJson.main !== "dist/index.js" || packageJson.exports?.["."] !== "./dist/index.js") {
  throw new Error("package main/exports must point to dist/index.js")
}

validatePlugin(DIST_ENTRY, PROJECT_ROOT)
console.log("prebuilt dist validation: PASS")
