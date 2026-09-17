// linux/bugzilla/bugzilla_<id>.json —— bugzilla.kernel.org REST 原样落盘
// 文件形态与本地既有样本一致：{"bug": {...}, "comments": [...]}
import { requestJson } from "../http.mjs"
import { datasetPath } from "../config.mjs"
import { pathExists } from "../store.mjs"
import {
  itemWatermark,
  maxIso,
  minIso,
  resolveWatermark,
  storeItem,
} from "./shared.mjs"

function requestOptions(config) {
  const { timeoutMs, retries, backoffMs } = config.request
  return { timeoutMs, retries, backoffMs }
}

async function fetchComments(dataset, bugId, options) {
  const url = `${dataset.bugzillaUrl}/rest/bug/${bugId}/comment`
  const { data } = await requestJson(url, options)
  const entry = data?.bugs?.[String(bugId)] || data?.bugs?.[bugId]
  return Array.isArray(entry?.comments) ? entry.comments : []
}

export async function collect({ config, dataset, state, logger, overrides = {} }) {
  const { since, source } = resolveWatermark({
    dataset,
    state,
    since: overrides.since,
    intervalMs: config.intervalMs,
    full: overrides.full,
  })
  const options = requestOptions(config)
  const pageSize = config.request.pageSize
  const maxPages = overrides.maxPages || 20
  // --limit：本轮最多处理的 bug 数（自检用）；被截断时水位退回窗口最旧一条，下一轮续传
  const maxItems = overrides.limit > 0 ? overrides.limit : 0

  const bugs = []
  let truncated = false
  for (let page = 0; page < maxPages; page += 1) {
    const offset = page * pageSize
    // include_fields: 默认字段集 + tags/duplicates —— 本地既有样本含这两个字段，
    // 而 Bugzilla 的 list 接口默认不返回它们，必须显式追加。
    const url = `${dataset.bugzillaUrl}/rest/bug`
      + `?last_change_time=${encodeURIComponent(since)}`
      + `&include_fields=_default,tags,duplicates`
      + `&limit=${pageSize}&offset=${offset}`
    const { data } = await requestJson(url, options)
    const batch = Array.isArray(data?.bugs) ? data.bugs : []
    if (batch.length === 0) break
    bugs.push(...batch)
    if (batch.length < pageSize) break
    if (page === maxPages - 1) truncated = true
  }

  const ordered = [...bugs].sort((left, right) => {
    const a = itemWatermark(dataset, left) || ""
    const b = itemWatermark(dataset, right) || ""
    return a.localeCompare(b)
  })

  let written = 0
  let skipped = 0
  let processed = 0
  let limited = false
  for (const bug of ordered) {
    if (maxItems > 0 && processed >= maxItems) {
      limited = true
      break
    }
    processed += 1
    const id = String(bug.id)
    const target = datasetPath(config, dataset, id)
    if (pathExists(target)) {
      skipped += 1
      continue
    }
    const comments = await fetchComments(dataset, bug.id, options)
    const result = storeItem(config, dataset, id, { bug, comments })
    if (result.written) {
      written += 1
      logger.debug(`写入 ${dataset.filePrefix}${id}.json`)
    }
  }

  const dates = bugs.map((bug) => itemWatermark(dataset, bug)).filter(Boolean)
  const watermark = truncated || limited ? minIso(dates) : maxIso(dates)
  return {
    fetched: bugs.length,
    written,
    skipped,
    watermark,
    watermarkFrom: source,
    since,
    truncated: truncated || limited,
  }
}