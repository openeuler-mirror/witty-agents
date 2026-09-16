// openEuler/issue/issue_<number>.json —— gitcode v5 issues 原样落盘
// 与 commit 数据集一致：单条 issue 的接口响应即文件内容，不做字段裁剪。
import { requestJson } from "../http.mjs"
import { datasetPath } from "../config.mjs"
import { pathExists } from "../store.mjs"
import { itemId, itemWatermark, maxIso, minIso, resolveWatermark, storeItem } from "./shared.mjs"

const ISSUES_URL = "https://api.gitcode.com/api/v5/repos"

export async function collect({ config, dataset, state, logger, overrides = {} }) {
  const { since, source } = resolveWatermark({
    dataset,
    state,
    since: overrides.since,
    intervalMs: config.intervalMs,
    full: overrides.full,
  })
  const { timeoutMs, retries, backoffMs, pageSize } = config.request
  const headers = { Accept: "application/json" }
  if (config.tokens.gitcode) headers["PRIVATE-TOKEN"] = config.tokens.gitcode
  const options = { timeoutMs, retries, backoffMs, headers }
  const maxPages = overrides.maxPages || 20
  // --limit：本轮最多处理的 issue 数（自检用）；被截断时水位退回窗口最旧一条，下一轮续传
  const maxItems = overrides.limit > 0 ? overrides.limit : 0

  const items = []
  let truncated = false
  for (let page = 1; page <= maxPages; page += 1) {
    const params = new URLSearchParams({
      state: "all",
      since,
      per_page: String(pageSize),
      page: String(page),
    })
    const { data } = await requestJson(`${ISSUES_URL}/${dataset.repo}/issues?${params.toString()}`, options)
    const batch = Array.isArray(data) ? data : []
    if (batch.length === 0) break
    items.push(...batch)
    // 上游按时间倒序返回：本页全部水位 <= 起点时，说明窗口已覆盖完
    const reachedFrontier = batch.every((item) => {
      const watermark = itemWatermark(dataset, item)
      return watermark !== null && watermark <= since
    })
    if (reachedFrontier || batch.length < pageSize) break
    if (page === maxPages) truncated = true
  }

  const ordered = [...items].sort((left, right) => {
    const a = itemWatermark(dataset, left) || ""
    const b = itemWatermark(dataset, right) || ""
    return a.localeCompare(b)
  })

  let written = 0
  let skipped = 0
  let processed = 0
  let limited = false
  for (const item of ordered) {
    if (maxItems > 0 && processed >= maxItems) {
      limited = true
      break
    }
    processed += 1
    const id = itemId(dataset, item)
    if (!id) continue
    if (pathExists(datasetPath(config, dataset, id))) {
      skipped += 1
      continue
    }
    const result = storeItem(config, dataset, id, item)
    if (result.written) {
      written += 1
      logger.debug(`写入 ${dataset.filePrefix}${id}.json`)
    }
  }

  const dates = items.map((item) => itemWatermark(dataset, item)).filter(Boolean)
  return {
    fetched: items.length,
    written,
    skipped,
    watermark: truncated || limited ? minIso(dates) : maxIso(dates),
    watermarkFrom: source,
    since,
    truncated: truncated || limited,
  }
}