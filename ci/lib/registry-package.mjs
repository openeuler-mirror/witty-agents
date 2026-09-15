import { execFileSync } from "node:child_process"
import { createHash } from "node:crypto"
import {
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { basename, join } from "node:path"

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex")
}

export function prepareRegistryPackage({ sourcePath, registryPackageName, workingRoot }) {
  if (!existsSync(sourcePath)) {
    throw new Error(`source package is missing: ${sourcePath}`)
  }
  if (!/^[a-z0-9][a-z0-9._-]*$/.test(registryPackageName || "")) {
    throw new Error(`registry package name must be a lowercase unscoped npm name: ${registryPackageName}`)
  }

  const extractRoot = join(workingRoot, "registry-package-source")
  const outputRoot = join(workingRoot, "registry-package-output")
  rmSync(extractRoot, { recursive: true, force: true })
  rmSync(outputRoot, { recursive: true, force: true })
  mkdirSync(extractRoot, { recursive: true })
  mkdirSync(outputRoot, { recursive: true })

  execFileSync("tar", ["-xzf", sourcePath, "-C", extractRoot], { stdio: "inherit" })
  const packageRoot = join(extractRoot, "package")
  const packageJsonPath = join(packageRoot, "package.json")
  if (!existsSync(packageJsonPath)) {
    throw new Error(`${basename(sourcePath)} does not contain package/package.json`)
  }
  const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf8"))
  const sourcePackageName = packageJson.name
  const variant = packageJson.shennongVariant
    ?? (packageJson.name === registryPackageName ? "online" : null)
  if (variant !== "online") {
    throw new Error(`only online packages may be prepared for npm; got ${packageJson.shennongVariant ?? packageJson.name}`)
  }
  packageJson.name = registryPackageName
  packageJson.wittySourcePackageName = sourcePackageName
  writeFileSync(packageJsonPath, `${JSON.stringify(packageJson, null, 2)}\n`)

  const packed = JSON.parse(execFileSync("npm", [
    "pack", packageRoot,
    "--ignore-scripts",
    "--json",
    "--pack-destination", outputRoot,
  ], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "inherit"],
    maxBuffer: 64 * 1024 * 1024,
  }))[0]
  const path = join(outputRoot, packed.filename)
  if (packed.name !== registryPackageName || !existsSync(path)) {
    throw new Error(`failed to prepare npm registry package ${registryPackageName}`)
  }
  return {
    path,
    filename: packed.filename,
    packageName: packed.name,
    version: packed.version,
    sourcePackageName,
    sha256: sha256(path),
  }
}
