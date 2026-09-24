// Entry point for the vllm-benchmark-view TUI plugin.
//
// This file intentionally contains no plugin logic. It only works around a
// Bun/opencode runtime quirk before dynamically importing the implementation:
//
//   solid-js publishes an export condition named "node" that resolves to its
//   non-reactive SSR build (dist/server.js). Bun matches "node" by default, so
//   createSignal/createEffect become silent no-ops and the sidebar never
//   updates. We delete that condition from the resolved package before any
//   solid-js module is evaluated.
//
// The same workaround (and the reasoning) comes from opencode-subagents-view,
// which is verified working against a real opencode instance.
import { existsSync, readFileSync, writeFileSync } from "node:fs"
import { createRequire } from "node:module"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

function patchSolidJsExports(fromDir: string): void {
  const require = createRequire(import.meta.url)
  let resolved: string
  try {
    resolved = require.resolve("solid-js", { paths: [fromDir] })
  } catch {
    return
  }

  let dir = dirname(resolved)
  for (;;) {
    const pkgPath = join(dir, "package.json")
    if (existsSync(pkgPath)) {
      try {
        const pkg = JSON.parse(readFileSync(pkgPath, "utf8"))
        if (pkg.name === "solid-js") {
          const mainExport = pkg.exports?.["."]
          if (mainExport && typeof mainExport === "object" && "node" in mainExport) {
            delete mainExport.node
            writeFileSync(pkgPath, `${JSON.stringify(pkg, null, 2)}\n`)
          }
          return
        }
      } catch {
        return
      }
    }
    const parent = dirname(dir)
    if (parent === dir) return
    dir = parent
  }
}

patchSolidJsExports(dirname(fileURLToPath(import.meta.url)))

// Loaded after the patch so the implementation gets the reactive solid-js.
const impl = (await import("./plugin.tsx")) as typeof import("./plugin.tsx")

export default impl.default
