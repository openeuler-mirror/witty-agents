import {
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { dirname, join } from "node:path"

export function readManagedFile(path, {
  defaultContent = "",
  defaultMode = 0o600,
  label = "configuration",
} = {}) {
  if (!existsSync(path)) {
    return {
      existed: false,
      mode: defaultMode,
      raw: defaultContent,
    }
  }

  const file = lstatSync(path)
  if (file.isSymbolicLink() || !file.isFile()) {
    throw new Error(`refusing to modify non-regular ${label}: ${path}`)
  }
  return {
    existed: true,
    mode: file.mode & 0o777,
    raw: readFileSync(path, "utf8"),
  }
}

export function createConfigBackup(path, raw, mode, owner = "shennong") {
  const timestamp = new Date().toISOString().replace(/[-:.]/g, "")
  const basePath = `${path}.${owner}-backup-${timestamp}`
  for (let attempt = 0; attempt < 1000; attempt += 1) {
    const backupPath = attempt === 0 ? basePath : `${basePath}-${attempt}`
    let fileDescriptor = null
    try {
      fileDescriptor = openSync(backupPath, "wx", mode)
      writeFileSync(fileDescriptor, raw, "utf8")
      fsyncSync(fileDescriptor)
      closeSync(fileDescriptor)
      return backupPath
    } catch (error) {
      if (fileDescriptor !== null) {
        closeSync(fileDescriptor)
      }
      if (error.code !== "EEXIST") {
        rmSync(backupPath, { force: true })
        throw error
      }
    }
  }
  throw new Error(`unable to create a unique backup for ${path}`)
}

export function atomicWrite(path, content, mode, owner = "shennong") {
  const directory = dirname(path)
  mkdirSync(directory, { recursive: true, mode: 0o700 })
  const temporaryPath = join(directory, `.${owner}-${process.pid}-${Date.now()}`)
  let fileDescriptor = null
  try {
    fileDescriptor = openSync(temporaryPath, "wx", mode)
    writeFileSync(fileDescriptor, content, "utf8")
    fsyncSync(fileDescriptor)
    closeSync(fileDescriptor)
    fileDescriptor = null
    renameSync(temporaryPath, path)
  } finally {
    if (fileDescriptor !== null) {
      closeSync(fileDescriptor)
    }
    rmSync(temporaryPath, { force: true })
  }
}

export function writeManagedFile({
  path,
  before,
  after,
  mode,
  existed,
  owner = "shennong",
}) {
  if (before === after) {
    return { changed: false, backupPath: null }
  }
  const backupPath = existed ? createConfigBackup(path, before, mode, owner) : null
  atomicWrite(path, after, mode, owner)
  return { changed: true, backupPath }
}
