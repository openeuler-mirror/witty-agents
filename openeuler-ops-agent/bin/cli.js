#!/usr/bin/env node
import { spawn, execSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = join(__dirname, "..");
const home = homedir();
const arg = process.argv[2] || "configure";

function jsoncParse(raw) {
  let result = "", inString = false, inComment = false;
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i], next = raw[i + 1];
    if (inComment) { if (ch === "\n") { inComment = false; result += ch; } continue; }
    if (inString) { result += ch; if (ch === "\\") { i++; result += next; continue; } if (ch === '"') inString = false; continue; }
    if (ch === '"') { inString = true; result += ch; continue; }
    if (ch === "/" && next === "/") { inComment = true; i++; continue; }
    if (ch === "/" && next === "*") { const end = raw.indexOf("*/", i + 2); if (end !== -1) { i = end + 1; continue; } }
    result += ch;
  }
  return JSON.parse(result.replace(/,(\s*[}\]])/g, "$1"));
}

function findConfig() {
  const paths = [join(home, ".config", "opencode", "opencode.jsonc"), join(home, ".opencode.jsonc")];
  for (const p of paths) if (existsSync(p)) return p;
  return null;
}

function configureAgent() {
  const cfgPath = findConfig();
  if (!cfgPath) { console.log("skip: no opencode config found"); return false; }
  const raw = readFileSync(cfgPath, "utf8");
  const config = jsoncParse(raw);
  if (config.mcp?.["openeuler-ops-agent"]) { delete config.mcp["openeuler-ops-agent"]; if (Object.keys(config.mcp).length === 0) delete config.mcp; }
  if (!config.agent) config.agent = {};
  config.agent["openeuler-ops"] = {
    description: "openEuler 运维助手 — 覆盖故障排查、巡检、CVE修复、安全加固、性能调优等16个场景",
    prompt: `{file:${join(rootDir, "agent.md")}}`,
    skills: ["agent-tools", "ssh-remote-skill", "ops-maintenance", "log-analyzer", "kubernetes", "docker-diag", "self-improvement", "skill-vetter", "summarize", "buddy-log-analyzer"],
  };
  writeFileSync(cfgPath, JSON.stringify(config, null, 2), "utf8");
  console.log(`Agent registered to ${cfgPath}`);
  return true;
}

if (arg === "configure") { configureAgent(); process.exit(0); }

if (arg === "install") {
  const sh = join(rootDir, "install.sh");
  const child = spawn("bash", [sh], { stdio: "inherit" });
  child.on("exit", (code) => {
    if (code === 0) configureAgent();
    process.exit(code || 0);
  });
}

if (arg === "verify") {
  spawn("bash", [join(rootDir, "scripts", "verify.sh")], { stdio: "inherit" }).on("exit", (c) => process.exit(c || 0));
}
