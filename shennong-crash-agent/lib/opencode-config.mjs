// Backward-compatible exports for code that imported the original module path.
// New framework integrations belong under lib/configure/adapters/.
export {
  getOpenCodeStatus,
  opencodeAdapter,
  registerOpenCodePlugin,
  removeOpenCodePlugin,
} from "./configure/adapters/opencode.mjs"
