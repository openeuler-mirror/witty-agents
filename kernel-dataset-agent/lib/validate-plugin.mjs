// 打包前的自检：OpenCode 只有在 skill 目录名与 frontmatter name 一致时才认这个 skill，
// 插件必须导出默认函数并在 config 钩子里注册 primary agent，否则装完根本不会被感知。
import { execFileSync } from "node:child_process"
import { existsSync, readFileSync, readdirSync } from "node:fs"
import { join } from "node:path"
import { pathToFileURL } from "node:url"

export function validateSkills(skillsRoot) {
  const namePattern = /^[a-z0-9]+(-[a-z0-9]+)*$/
  const found = []
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
    found.push(skillDir)
  }
  if (found.length === 0) throw new Error(`no skill found under ${skillsRoot}`)
  return found
}

export function validatePlugin(pluginPath, cwd, agentKey = "kernel-dataset") {
  execFileSync(process.execPath, ["--check", pluginPath], { cwd, stdio: "inherit" })
  const script = `
    const module = await import(${JSON.stringify(pathToFileURL(pluginPath).href)});
    if (typeof module.default !== "function") throw new Error("default plugin export is missing");
    const hooks = await module.default({});
    if (!hooks || typeof hooks.config !== "function") throw new Error("plugin config hook is missing");
    const config = {};
    await hooks.config(config);
    const agent = config.agent?.[${JSON.stringify(agentKey)}];
    if (!agent) throw new Error("${agentKey} agent was not registered");
    if (agent.mode !== "primary") throw new Error("${agentKey} agent mode must be primary");
    if (!Array.isArray(agent.skills) || agent.skills.length === 0) throw new Error("${agentKey} agent skills are missing");
  `
  execFileSync(process.execPath, ["--input-type=module", "--eval", script], { cwd, stdio: "inherit" })
}