#!/usr/bin/env node

import { createHash } from "node:crypto"
import {
  copyFileSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
} from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = resolve(SCRIPT_DIR, "..")
const OCR_ROOT = join(
  PROJECT_ROOT,
  "skills",
  "witty-log-detection",
  "src",
  "model",
  "ocr",
)

const MODELS = Object.freeze([
  {
    path: "ch_PP-OCRv4_det_infer/inference.pdiparams",
    sha256: "49ee815e30cff43cb1057d33bf0d94193e4d4f1ae28451cad15b40be830df915",
  },
  {
    path: "ch_PP-OCRv4_rec_infer/inference.pdiparams",
    sha256: "a6dbfa63e7ee161688523c954e9e293f77dc24044db81e836ff9c7f103fd191a",
  },
  {
    path: "ch_ppocr_mobile_v2.0_cls_infer/inference.pdiparams",
    sha256: "d1efda1b80e174b4fcb168a035ac96c1af4938892bd86a55f300a6027105d08c",
  },
])

function parseArgs(argv) {
  let cacheDir = process.env.OCR_MODEL_CACHE_DIR || ""
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg.startsWith("--cache-dir=")) {
      cacheDir = arg.slice("--cache-dir=".length)
    } else if (arg === "--cache-dir") {
      cacheDir = argv[++index]
    } else {
      throw new Error(`unknown argument: ${arg}`)
    }
  }
  return { cacheDir: cacheDir ? resolve(cacheDir) : null }
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex")
}

function inspectRegularFile(path) {
  if (!existsSync(path)) {
    return { valid: false, reason: "missing" }
  }
  const metadata = lstatSync(path)
  if (metadata.isSymbolicLink() || !metadata.isFile()) {
    return { valid: false, reason: "not a regular file" }
  }
  const prefix = readFileSync(path).subarray(0, 128).toString("utf8")
  if (prefix.startsWith("version https://git-lfs.github.com/spec/v1")) {
    return { valid: false, reason: "Git LFS pointer" }
  }
  return { valid: true, sha256: sha256(path), size: metadata.size }
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  const results = []

  for (const model of MODELS) {
    const target = join(OCR_ROOT, model.path)
    let inspected = inspectRegularFile(target)
    let source = "checkout"

    if (!inspected.valid || inspected.sha256 !== model.sha256) {
      if (!options.cacheDir) {
        const actual = inspected.sha256 || inspected.reason
        throw new Error(
          `OCR model is unavailable or invalid: ${model.path} (${actual}); `
          + "run git lfs pull or set OCR_MODEL_CACHE_DIR",
        )
      }
      const cached = join(options.cacheDir, model.path)
      const cachedInspection = inspectRegularFile(cached)
      if (!cachedInspection.valid || cachedInspection.sha256 !== model.sha256) {
        const actual = cachedInspection.sha256 || cachedInspection.reason
        throw new Error(`OCR model cache is invalid: ${cached} (${actual})`)
      }
      mkdirSync(dirname(target), { recursive: true })
      copyFileSync(cached, target)
      inspected = inspectRegularFile(target)
      source = "cache"
    }

    if (!inspected.valid || inspected.sha256 !== model.sha256) {
      throw new Error(`OCR model verification failed after preparation: ${model.path}`)
    }
    results.push({
      path: model.path,
      source,
      size: inspected.size,
      sha256: inspected.sha256,
    })
  }

  console.log(JSON.stringify({
    status: "ready",
    modelCount: results.length,
    cacheDir: options.cacheDir,
    models: results,
  }, null, 2))
}

try {
  main()
} catch (error) {
  console.error(`[ocr-models] ${error.message}`)
  process.exit(1)
}
