import { execFileSync } from "node:child_process"
import { existsSync, readFileSync, readdirSync } from "node:fs"
import { join } from "node:path"
import { pathToFileURL } from "node:url"

// OpenCode skill discovery contract: each skill needs a SKILL.md whose YAML
// frontmatter `name` matches the directory name (lowercase alphanumeric + hyphens)
// and carries a description. Otherwise the skill is never sensed.
export function validateSkills(skillsRoot) {
  const namePattern = /^[a-z0-9]+(-[a-z0-9]+)*$/
  for (const entry of readdirSync(skillsRoot, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    const skillDir = entry.name
    const skillFile = join(skillsRoot, skillDir, "SKILL.md")
    if (!existsSync(skillFile)) throw new Error(`skill ${skillDir}: SKILL.md is missing`)
    const raw = readFileSync(skillFile, "utf8")
    const frontmatter = raw.match(/^---\r?\n([\s\S]*?)\r?\n---/)
    if (!frontmatter) throw new Error(`skill ${skillDir}: SKILL.md frontmatter is missing`)
    const name = (frontmatter[1].match(/^name:\s*(.+)\r?$/m) || [])[1]?.trim()
    if (name !== skillDir || !namePattern.test(name ?? "")) {
      throw new Error(`skill ${skillDir}: frontmatter name ${JSON.stringify(name)} must equal the directory name`)
    }
    if (!/^description:/m.test(frontmatter[1])) {
      throw new Error(`skill ${skillDir}: frontmatter description is missing`)
    }
  }
}

export function validatePlugin(pluginPath, cwd) {
  execFileSync(process.execPath, ["--check", pluginPath], {
    cwd,
    stdio: "inherit",
  })
  const script = `
    const module = await import(${JSON.stringify(pathToFileURL(pluginPath).href)});
    if (typeof module.default !== "function") throw new Error("default plugin export is missing");
    const hooks = await module.default({});
    if (!hooks || typeof hooks.config !== "function") throw new Error("plugin config hook is missing");
    const config = {};
    await hooks.config(config);
    if (config.agent?.["vllm-benchmark"]?.mode !== "primary") throw new Error("vllm-benchmark primary agent was not registered");
  `
  execFileSync(process.execPath, ["--input-type=module", "--eval", script], {
    cwd,
    stdio: "inherit",
  })
}