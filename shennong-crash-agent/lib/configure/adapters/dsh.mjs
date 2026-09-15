import { existsSync, readFileSync } from "node:fs"
import { homedir } from "node:os"
import { join, resolve } from "node:path"

const MANAGED_ENTRY_IDS = Object.freeze([
  "mcp-shennong-crash-feature-matcher",
  "mcp-shennong-witty-log-detection",
])

function getDshHome() {
  return process.env.DSH_HOME ? resolve(process.env.DSH_HOME) : join(homedir(), ".dsh")
}

function getDshPaths(profile) {
  const dshHome = getDshHome()
  const profileDir = join(dshHome, "profiles", profile)
  return {
    dshHome,
    profile,
    profileDir,
    packagePath: join(profileDir, "package.json"),
    patchPath: join(profileDir, "cordis.patch.yml"),
  }
}

function getTemplatePaths(packageRoot) {
  const templateDir = join(packageRoot, "frameworks", "dsh")
  return {
    templateDir,
    packageTemplate: join(templateDir, "package.json.template"),
    patchTemplate: join(templateDir, "cordis.patch.yml.template"),
    personaTemplate: join(templateDir, "shennong-persona.md"),
  }
}

function unsupported() {
  throw new Error(
    "DSH registration is intentionally gated: the official DSH MCP client supports "
    + "stdio and Streamable HTTP, while witty-log-detection currently exposes legacy "
    + "SSE at /sse. Add and verify a Streamable HTTP /mcp endpoint before enabling "
    + "DSH install/remove.",
  )
}

export function getDshStatus(packageRoot, profile = "web") {
  const paths = getDshPaths(profile)
  const templates = getTemplatePaths(packageRoot)
  const patch = existsSync(paths.patchPath) ? readFileSync(paths.patchPath, "utf8") : ""
  const managedEntries = MANAGED_ENTRY_IDS.filter((id) => patch.includes(`id: ${id}`))
  const templatesReady = Object.values(templates)
    .filter((path) => path !== templates.templateDir)
    .every((path) => existsSync(path))
  return {
    changed: false,
    configured: managedEntries.length > 0,
    supported: false,
    reason: "witty-log-detection Streamable HTTP /mcp endpoint is not implemented",
    managedEntries,
    templatesReady,
    ...paths,
    ...templates,
  }
}

export const dshAdapter = Object.freeze({
  id: "dsh",
  label: "DeepSeek Harness",
  capabilities: Object.freeze({
    install: false,
    remove: false,
    status: true,
    "sync-skills": false,
    reason: "witty-log-detection must expose and pass Streamable HTTP /mcp tests first",
  }),
  install: unsupported,
  remove: unsupported,
  "sync-skills": unsupported,
  status({ packageRoot, options }) {
    return getDshStatus(packageRoot, options.profile)
  },
})
