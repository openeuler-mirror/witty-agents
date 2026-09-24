#!/usr/bin/env node

import { execFileSync } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { validateSkills } from "../lib/validate-plugin.mjs"

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = resolve(SCRIPT_DIR, "..")
const REQUIRED_MANIFEST = join(PROJECT_ROOT, "packaging", "required-package-files.txt")

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const manifest = readFileSync(REQUIRED_MANIFEST, "utf8")
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter((line) => line && !line.startsWith("#"))

for (const path of manifest) {
  assert(existsSync(join(PROJECT_ROOT, path)), `required package file is missing: ${path}`)
}

for (const checkable of ["bin/configure.mjs", "bin/vllm-benchmark-setup.mjs", "lib/configure.mjs", "lib/validate-plugin.mjs", "scripts/validate-dist.mjs"]) {
  execFileSync(process.execPath, ["--check", join(PROJECT_ROOT, checkable)], { stdio: "inherit" })
}

validateSkills(join(PROJECT_ROOT, "skills"))
console.log("skills frontmatter: PASS")

execFileSync(process.execPath, [join(PROJECT_ROOT, "scripts/validate-dist.mjs")], { stdio: "inherit" })

const packageJson = JSON.parse(readFileSync(join(PROJECT_ROOT, "package.json"), "utf8"))
assert(
  !Object.hasOwn(packageJson.scripts ?? {}, "postinstall"),
  "package must not declare a postinstall script (npm install must be side-effect free)",
)

console.log("validate: PASS")