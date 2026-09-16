export const FRAMEWORK_TARGETS = Object.freeze(["opencode", "dsh"])
export const CONFIGURE_ACTIONS = Object.freeze(["install", "remove", "status", "sync-skills"])

export function configureUsage() {
  return `Usage:
  shennong-configure [install] [--target opencode]
  shennong-configure remove    [--target opencode]
  shennong-configure status    [--target opencode|dsh|all]
  shennong-configure sync-skills [--target opencode]

Options:
  --target <name>   Framework adapter: opencode, dsh, or all (default: opencode)
  --profile <name>  Framework profile name (used by DSH; default: web)

Notes:
  OpenCode install/remove is fully supported.
  install 同步会把安装包内核心 skill 强制同步到 ~/.config/opencode/skills/
  （内容有差异才覆盖，覆盖前自动做 <skill>.bak-<时间戳> 备份；幂等）。
  sync-skills 仅执行该同步，不改动插件/MCP 注册。
  DSH has a versioned adapter boundary and templates, but install/remove remains
  gated until witty-log-detection exposes Streamable HTTP at /mcp.`
}

export function parseConfigureArgs(argv) {
  const options = {
    action: "install",
    target: process.env.SHENNONG_FRAMEWORK || "opencode",
    profile: process.env.SHENNONG_DSH_PROFILE || "web",
    help: false,
  }
  let actionSeen = false

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (["--help", "-h", "help"].includes(arg)) {
      options.help = true
    } else if (CONFIGURE_ACTIONS.includes(arg) && !actionSeen) {
      options.action = arg
      actionSeen = true
    } else if (arg.startsWith("--target=")) {
      options.target = arg.slice("--target=".length)
    } else if (arg === "--target") {
      options.target = argv[++index]
    } else if (arg.startsWith("--profile=")) {
      options.profile = arg.slice("--profile=".length)
    } else if (arg === "--profile") {
      options.profile = argv[++index]
    } else {
      throw new Error(`unknown argument: ${arg}`)
    }
  }

  if (!options.target || ![...FRAMEWORK_TARGETS, "all"].includes(options.target)) {
    throw new Error(`--target must be one of: ${[...FRAMEWORK_TARGETS, "all"].join(", ")}`)
  }
  if (!options.profile || !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(options.profile)) {
    throw new Error("--profile must contain only letters, numbers, dot, underscore, or hyphen")
  }
  return options
}

export function assertAdapterContract(adapter) {
  if (!adapter || typeof adapter !== "object") {
    throw new Error("framework adapter must be an object")
  }
  if (!FRAMEWORK_TARGETS.includes(adapter.id)) {
    throw new Error(`framework adapter has an invalid id: ${adapter.id}`)
  }
  for (const action of CONFIGURE_ACTIONS) {
    if (typeof adapter[action] !== "function") {
      throw new Error(`framework adapter ${adapter.id} does not implement ${action}()`)
    }
  }
  return adapter
}

export function assertActionSupported(adapter, action) {
  if (adapter.capabilities?.[action] === false) {
    const reason = adapter.capabilities.reason || `${action} is not available`
    throw new Error(`${adapter.id} adapter does not support ${action}: ${reason}`)
  }
}
