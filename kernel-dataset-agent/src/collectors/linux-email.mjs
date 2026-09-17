// linux/email —— lkml MHonArc 归档采集器。
//
// 落盘形态与既有 <dataRoot>/linux/email/data-BNN 完全一致（默认 dataRoot=/home/data）：
//   indexes/<part>.html     上游 <part>/index.html 原文
//   raw/<part>/<page>.html  上游 <part>/<page>.html 原文（逐字节相同）
//   manifest.jsonl          每条一行 {"part","page","url","file","bytes","message_id","subject","from","date","in_reply_to"}
//   state.json              {"done_parts": [...]}
//   failures.jsonl          （可选）索引里有链接但页面已不存在的记录
//
// 分片策略（决策点1）：先追加到当前活动分片，分片写满后新建 data-B(n+1)。
// 分片切换只发生在 part 边界（收完一个 part 之后），因此同一个 part 不会被拆到两个分片。
import { closeSync, createReadStream, existsSync, fsyncSync, openSync, readFileSync, readdirSync, statSync, writeSync } from "node:fs"
import { join } from "node:path"
import { createInterface } from "node:readline"

import { requestText, probeText, sleep } from "../http.mjs"
import { datasetDir } from "../config.mjs"
import { atomicWriteFile, ensureDir } from "../store.mjs"

const PART_LINK = /href="(\d{4}\.\d)\/index\.html"/g
const PAGE_LINK = /href="(\d{1,6})\.html"/g
const PART_NAME = /^\d{4}\.\d$/

const INDEX_KEYS = ["part", "page", "url", "file", "bytes", "message_id", "subject", "from", "date", "in_reply_to"]

// ---------------------------------------------------------------------------
// HTML 解析
// ---------------------------------------------------------------------------

// MHonArc 头部把非 ASCII 与尖括号统一写成实体（&#xE1; / &#60;），
// 因此只需还原实体即可拿到原始头信息。
export function unescapeHtml(text) {
  if (!text.includes("&")) return text
  return text.replace(/&(#x[0-9a-fA-F]+|#\d+|[a-zA-Z]+);/g, (match, entity) => {
    if (entity[0] === "#") {
      const code = entity[1].toLowerCase() === "x"
        ? Number.parseInt(entity.slice(2), 16)
        : Number.parseInt(entity.slice(1), 10)
      return Number.isFinite(code) ? String.fromCodePoint(code) : match
    }
    const named = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " }
    return named[entity.toLowerCase()] ?? match
  })
}

function metaContent(html, names) {
  for (const name of names) {
    const matched = new RegExp(`<meta\\s+name="${name}"\\s+content="([^"]*)"`, "i").exec(html)
    if (matched) {
      const value = unescapeHtml(matched[1]).trim()
      if (value) return value
    }
  }
  return ""
}

function commentValue(html, name) {
  const matched = new RegExp(`<!--X-${name}: ([\\s\\S]*?) -->`).exec(html)
  return matched ? unescapeHtml(matched[1]).trim() : ""
}

// 上游归档在 2026 年前后改版：旧格式用 <meta NAME="Author" CONTENT="...">，
// 新格式改成小写 <meta name="author"> 且标题落在 description 上，两种都兼容。
export function parseMessageMeta(html) {
  return {
    from: metaContent(html, ["author"]),
    subject: metaContent(html, ["description", "subject"]) || commentValue(html, "Subject"),
    date: commentValue(html, "Date"),
    message_id: commentValue(html, "Message-Id"),
    // 当前 MHonArc 归档不再输出 X-In-Reply-To（只有更早的 hypermail 批次才有），
    // 与现有本地数据保持一致，恒为空串。
    in_reply_to: "",
  }
}

// 归档首页按“新 -> 旧”排列（2609.1 ... 9603.0），这里翻转为时间升序。
export function parseParts(listingHtml) {
  const parts = []
  const seen = new Set()
  for (const matched of listingHtml.matchAll(PART_LINK)) {
    if (seen.has(matched[1])) continue
    seen.add(matched[1])
    parts.push(matched[1])
  }
  return parts.reverse()
}

export function parsePages(indexHtml) {
  const pages = new Set()
  for (const matched of indexHtml.matchAll(PAGE_LINK)) pages.add(matched[1])
  return [...pages].sort((left, right) => Number(left) - Number(right))
}

// part 形如 YYMM.N：90~99 属于 19xx，00~89 属于 20xx。
// 返回 YYYYMM.序号，可直接与 monthKeyFromDate() 的结果比较大小。
export function partSortKey(part) {
  const [month, index] = part.split(".")
  const year = Number(month.slice(0, 2))
  const fullYear = year >= 90 ? 1900 + year : 2000 + year
  return fullYear * 100 + Number(month.slice(2, 4)) + Number(index) / 100
}

// ---------------------------------------------------------------------------
// manifest / state 序列化：与现有文件逐字节对齐（Python json.dumps 默认分隔符）
// ---------------------------------------------------------------------------

function encodeJson(value) {
  return JSON.stringify(value)
}

export function manifestLine(record) {
  return `{${INDEX_KEYS.map((key) => `${encodeJson(key)}: ${encodeJson(record[key] ?? "")}`).join(", ")}}`
}

function compactJson(value) {
  if (Array.isArray(value)) return `[${value.map(compactJson).join(", ")}]`
  if (value && typeof value === "object") {
    return `{${Object.entries(value).map(([key, item]) => `${encodeJson(key)}: ${compactJson(item)}`).join(", ")}}`
  }
  return encodeJson(value)
}

// manifest/failures 为追加写入：写完 fsync，避免进程被 kill 时丢尾部记录。
function appendLines(path, content) {
  const descriptor = openSync(path, "a")
  try {
    writeSync(descriptor, content)
    fsyncSync(descriptor)
  } finally {
    closeSync(descriptor)
  }
}

// ---------------------------------------------------------------------------
// 分片管理
// ---------------------------------------------------------------------------

function batchNumber(batch) {
  return Number(batch.slice("data-B".length))
}

export function listBatches(emailDir) {
  if (!existsSync(emailDir)) return []
  // 分片目录数量很少（十几个），同步读取不会造成内存压力。
  return readdirSync(emailDir)
    .filter((name) => /^data-B\d+$/.test(name))
    .sort((left, right) => batchNumber(left) - batchNumber(right))
}

function batchPaths(emailDir, batch) {
  const batchDir = join(emailDir, batch)
  return {
    batch,
    batchDir,
    indexesDir: join(batchDir, "indexes"),
    rawDir: join(batchDir, "raw"),
    manifestPath: join(batchDir, "manifest.jsonl"),
    statePath: join(batchDir, "state.json"),
    failuresPath: join(batchDir, "failures.jsonl"),
  }
}

function createBatch(emailDir, batch) {
  const paths = batchPaths(emailDir, batch)
  ensureDir(paths.indexesDir)
  ensureDir(paths.rawDir)
  if (!existsSync(paths.manifestPath)) atomicWriteFile(paths.manifestPath, "")
  if (!existsSync(paths.statePath)) atomicWriteFile(paths.statePath, compactJson({ done_parts: [] }))
  return paths
}

function nextBatchName(batches) {
  const highest = batches.reduce((max, name) => Math.max(max, batchNumber(name)), 0)
  return `data-B${String(highest + 1).padStart(2, "0")}`
}

function batchParts(rawDir) {
  if (!existsSync(rawDir)) return []
  return readdirSync(rawDir).filter((name) => PART_NAME.test(name))
}

// 已收 part -> 所属分片（分区目录本身就是权威的“收过哪些 part”记录，无需解析 manifest）
function collectPartOwners(emailDir, batches) {
  const owners = new Map()
  for (const batch of batches) {
    for (const part of batchParts(join(emailDir, batch, "raw"))) owners.set(part, batch)
  }
  return owners
}

function localPages(emailDir, owner, part) {
  const dir = join(emailDir, owner, "raw", part)
  if (!existsSync(dir)) return new Set()
  return new Set(readdirSync(dir).filter((name) => name.endsWith(".html")).map((name) => name.slice(0, -5)))
}

// 索引里有链接但上游已不存在的页：与既有 data-B03/failures.jsonl 一致，记录后不再重复请求。
function readFailedPages(failuresPath, part) {
  const failed = new Set()
  if (!existsSync(failuresPath)) return failed
  const content = readFileSync(failuresPath, "utf8")
  for (const line of content.split("\n")) {
    if (line.length === 0) continue
    try {
      const record = JSON.parse(line)
      if (record.part === part) failed.add(record.page)
    } catch {
      // 忽略损坏行
    }
  }
  return failed
}

function readDoneParts(statePath) {
  if (!existsSync(statePath)) return []
  try {
    const parsed = JSON.parse(readFileSync(statePath, "utf8"))
    return Array.isArray(parsed?.done_parts) ? parsed.done_parts : []
  } catch {
    return []
  }
}

// 流式统计 manifest 记录数，用于分片容量判断（首轮才需要，之后走状态缓存）
async function countManifestRecords(manifestPath) {
  if (!existsSync(manifestPath)) return 0
  const stream = createReadStream(manifestPath, { encoding: "utf8", highWaterMark: 1 << 20 })
  const lines = createInterface({ input: stream, crlfDelay: Infinity })
  let total = 0
  for await (const line of lines) if (line.length > 0) total += 1
  return total
}

// ---------------------------------------------------------------------------
// 日期 -> part
// ---------------------------------------------------------------------------

function monthKeyFromDate(iso) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  return date.getUTCFullYear() * 100 + (date.getUTCMonth() + 1)
}

function monthsAgoIso(months) {
  const date = new Date()
  date.setUTCMonth(date.getUTCMonth() - months)
  return date.toISOString()
}

// ---------------------------------------------------------------------------

export async function collect({ config, dataset, state, logger, overrides = {} }) {
  const emailDir = datasetDir(config, dataset)
  ensureDir(emailDir)

  const previous = state.email && typeof state.email === "object" ? state.email : {}
  const { timeoutMs, retries, backoffMs } = config.request
  const requestOptions = { timeoutMs, retries, backoffMs }
  const maxPagesPerPart = overrides.limit > 0 ? overrides.limit : 0

  // 1) 选定活动分片：状态里记录的分片优先，其次取编号最大的分片
  let batches = listBatches(emailDir)
  if (batches.length === 0) {
    createBatch(emailDir, "data-B01")
    batches = ["data-B01"]
  }
  let activeBatch = previous.batch && batches.includes(previous.batch) ? previous.batch : batches[batches.length - 1]
  let paths = batchPaths(emailDir, activeBatch)

  let batchFiles = Number(previous.batchFiles)
  if (!Number.isFinite(batchFiles) || previous.batch !== activeBatch) {
    batchFiles = await countManifestRecords(paths.manifestPath)
  }
  let batchBytes = existsSync(paths.manifestPath) ? statSync(paths.manifestPath).size : 0

  // 2) 本地已收 part（跨全部分片）
  const owners = collectPartOwners(emailDir, batches)
  const activeBatchParts = batchParts(paths.rawDir).sort((left, right) => partSortKey(left) - partSortKey(right))
  const coveredParts = new Set(owners.keys())

  // 3) 上游 part 列表
  const listing = await requestText(`${dataset.archiveUrl}/`, requestOptions)
  const allParts = parseParts(listing.text)
  if (allParts.length === 0) throw new Error(`未能从归档首页解析出任何 part: ${dataset.archiveUrl}/`)
  const newestPart = allParts[allParts.length - 1]
  logger.info(`上游最新 part ${newestPart}，本地已收 ${coveredParts.size} 个 part，当前分片 ${activeBatch}`)

  // 4) 目标 part = 本地缺失的 part（回补）∪ 上游最新的 part（增量）
  //    归档只会往“最新 part”追加新邮件，所以它每轮都必须重扫索引取增量；
  //    其余 part 一旦收齐就不会再变，除非发现空洞才回补。
  //    时间下限取活动分片覆盖的最早 part，避免把历史上的空洞塞进新分片。
  const growingPart = newestPart
  const floor = activeBatchParts.length > 0
    ? partSortKey(activeBatchParts[0])
    : (coveredParts.size > 0
      ? Math.max(...[...coveredParts].map(partSortKey))
      : null)
  let targets = allParts.filter((part) => !coveredParts.has(part) || part === growingPart)
  if (overrides.since) {
    const sinceKey = monthKeyFromDate(overrides.since)
    if (sinceKey) targets = targets.filter((part) => partSortKey(part) >= sinceKey)
  } else if (coveredParts.size === 0) {
    // 本地没有任何数据：默认只回补最近几个月，避免一上来就拉全量归档
    const sinceKey = monthKeyFromDate(monthsAgoIso(dataset.monthsBack || 2))
    if (sinceKey) targets = targets.filter((part) => partSortKey(part) >= sinceKey)
  } else if (floor !== null) {
    targets = targets.filter((part) => partSortKey(part) >= floor)
  }
  if (overrides.full) targets = allParts

  const maxPartsPerCycle = overrides.maxParts || 4
  let skippedParts = 0
  if (targets.length > maxPartsPerCycle) {
    skippedParts = targets.length - maxPartsPerCycle
    // 回补历史从最旧的 part 开始，但最新 part 每轮都要扫，不能被截断掉
    const selected = new Set(targets.slice(0, maxPartsPerCycle))
    if (!selected.has(growingPart)) {
      selected.delete(targets[maxPartsPerCycle - 1])
      selected.add(growingPart)
    }
    targets = targets.filter((part) => selected.has(part))
  }

  // 5) 逐个 part 抓取
  let written = 0
  let failed = 0
  let fetched = 0
  let skipped = 0
  const completedParts = []

  for (const part of targets) {
    let indexHtml
    try {
      indexHtml = (await requestText(`${dataset.archiveUrl}/${part}/index.html`, requestOptions)).text
    } catch (error) {
      logger.warn(`part ${part} 的 index.html 获取失败：${error.message}`)
      failed += 1
      continue
    }
    atomicWriteFile(join(paths.indexesDir, `${part}.html`), indexHtml)

    const pages = parsePages(indexHtml)
    const already = localPages(emailDir, owners.get(part) || activeBatch, part)
    const failedPages = readFailedPages(paths.failuresPath, part)
    for (const page of failedPages) already.add(page)

    const fresh = pages.filter((page) => !already.has(page))
    skipped += pages.length - fresh.length
    const limited = maxPagesPerPart > 0 ? fresh.slice(0, maxPagesPerPart) : fresh
    const records = []
    const pageDir = join(paths.rawDir, part)

    for (const page of limited) {
      const url = `${dataset.archiveUrl}/${part}/${page}.html`
      let body
      try {
        const response = await probeText(url, requestOptions)
        if (response === null) {
          appendLines(paths.failuresPath, `${manifestLine({ part, page, url, ts: new Date().toISOString() })}\n`)
          already.add(page)
          failed += 1
          continue
        }
        body = response.text
      } catch (error) {
        logger.warn(`page ${part}/${page} 获取失败：${error.message}`)
        failed += 1
        continue
      }
      const relativeFile = `raw/${part}/${page}.html`
      atomicWriteFile(join(paths.batchDir, relativeFile), body)
      records.push({
        part,
        page,
        url,
        file: relativeFile,
        bytes: Buffer.byteLength(body),
        ...parseMessageMeta(body),
      })
      already.add(page)
      fetched += 1
    }

    if (records.length > 0) {
      appendLines(paths.manifestPath, `${records.map(manifestLine).join("\n")}\n`)
      batchFiles += records.length
      batchBytes = statSync(paths.manifestPath).size
      written += records.length
      logger.info(`part ${part} 新增 ${records.length} 封（分片 ${activeBatch} 累计 ${batchFiles} 条 / ${batchBytes} 字节）`)
    }

    // 索引已全部覆盖，且它不是仍在增长的最新 part，才算这个 part 收完
    const complete = pages.every((page) => already.has(page))
    if (complete && part !== growingPart) {
      const done = new Set([...readDoneParts(paths.statePath), part])
      atomicWriteFile(
        paths.statePath,
        compactJson({ done_parts: [...done].sort((left, right) => partSortKey(left) - partSortKey(right)) }),
      )
      completedParts.push(part)

      // 分片切换只发生在 part 边界：当前分片写满后，后续 part 落到新分片
      if (batchFiles >= dataset.maxBatchFiles || batchBytes >= dataset.maxBatchBytes) {
        const next = nextBatchName(listBatches(emailDir))
        paths = createBatch(emailDir, next)
        activeBatch = next
        batchFiles = 0
        batchBytes = 0
        logger.info(`分片已达上限（${dataset.maxBatchFiles} 条 / ${dataset.maxBatchBytes} 字节），新建分片 ${next}`)
      }
    }

    if (maxPagesPerPart > 0 && limited.length < fresh.length) break
    await sleep(50)
  }

  return {
    fetched,
    written,
    skipped,
    failed,
    truncated: skippedParts > 0,
    pendingParts: skippedParts,
    // email 的进度以 part 为单位，这里不写 ISO 水位，避免污染通用 watermark 字段
    watermark: null,
    watermarkFrom: "mhonarc",
    latestPart: growingPart || newestPart,
    since: targets[0] || null,
    batch: activeBatch,
    batchFiles,
    completedParts,
    statePatch: {
      email: { batch: activeBatch, batchFiles, batchBytes },
    },
  }
}

export { batchPaths, nextBatchName, compactJson, localPages, collectPartOwners }