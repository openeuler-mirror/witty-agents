import { execFileSync } from "node:child_process"
import { pathToFileURL } from "node:url"

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
    if (config.agent?.nl2sql?.mode !== "primary") throw new Error("nl2sql primary agent was not registered");
  `
  execFileSync(process.execPath, ["--input-type=module", "--eval", script], {
    cwd,
    stdio: "inherit",
  })
}