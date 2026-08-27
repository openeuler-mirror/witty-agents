import { assertActionSupported, assertAdapterContract } from "../common.mjs"
import { dshAdapter } from "./dsh.mjs"
import { opencodeAdapter } from "./opencode.mjs"

const ADAPTERS = new Map(
  [opencodeAdapter, dshAdapter]
    .map(assertAdapterContract)
    .map((adapter) => [adapter.id, adapter]),
)

export function getFrameworkAdapters(target, action) {
  const ids = target === "all" ? [...ADAPTERS.keys()] : [target]
  const adapters = ids.map((id) => {
    const adapter = ADAPTERS.get(id)
    if (!adapter) {
      throw new Error(`unknown framework adapter: ${id}`)
    }
    return adapter
  })

  // Preflight all targets before modifying any framework configuration.
  for (const adapter of adapters) {
    assertActionSupported(adapter, action)
  }
  return adapters
}

export function listFrameworkAdapters() {
  return [...ADAPTERS.values()]
}
