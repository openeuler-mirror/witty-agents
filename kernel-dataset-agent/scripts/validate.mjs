#!/usr/bin/env node
// CI 校验入口：必需文件、语法、skill frontmatter、dist 插件注册、无 postinstall 副作用。
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

const checkable = [
  "bin/kernel-dataset-setup.mjs",
  "bin/kernel-dataset-configure.mjs",
  "lib/configure.mjs",
  "lib/service.mjs",
  "lib/validate-plugin.mjs",
  "src/main.mjs",
  "src/daemon.mjs",
  "src/cycle.mjs",
  "src/config.mjs",
  "src/store.mjs",
  "src/http.mjs",
  "src/args.mjs",
  "src/log.mjs",
  "src/collectors/index.mjs",
  "src/collectors/shared.mjs",
  "src/collectors/linux-bugzilla.mjs",
  "src/collectors/linux-email.mjs",
  "src/collectors/commits.mjs",
  "src/collectors/openeuler-issue.mjs",
  "scripts/validate-dist.mjs",
]
for (const path of checkable) {
  assert(existsSync(join(PROJECT_ROOT, path)), `checkable file is missing: ${path}`)
  execFileSync(process.execPath, ["--check", join(PROJECT_ROOT, path)], { stdio: "inherit" })
}

validateSkills(join(PROJECT_ROOT, "skills"))
console.log("skills frontmatter: PASS")

execFileSync(process.execPath, [join(PROJECT_ROOT, "scripts/validate-dist.mjs")], { stdio: "inherit" })

const packageJson = JSON.parse(readFileSync(join(PROJECT_ROOT, "package.json"), "utf8"))
assert(
  !Object.hasOwn(packageJson.scripts ?? {}, "postinstall"),
  "package must not declare a postinstall script (npm install must be side-effect free)",
)
for (const bin of ["kernel-dataset-setup", "kernel-dataset-configure"]) {
  assert(packageJson.bin?.[bin], `package.json bin is missing: ${bin}`)
}

console.log("validate: PASS")