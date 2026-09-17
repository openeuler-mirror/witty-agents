// linux/commit 与 openEuler/commit —— 上游 commits 列表接口原样落盘
// commit_<sha>.json 的字段与上游 list 响应完全一致（GitHub 含 node_id；
// GitCode 含 co_authors），因此不做任何字段裁剪或加工。
import { remainingRateLimit, requestJson } from "../http.mjs"
import { storeItem, itemId, itemWatermark, maxIso, minIso, resolveWatermark } from "./shared.mjs"
import { pathExists } from "../store.mjs"
import { datasetPath } from "../config.mjs"

const PROVIDERS = {
  github: {
    label: "github",
    listUrl: ({ dataset, page, pageSize, since }) => {
      const params = new URLSearchParams({
        since,
        per_page: String(pageSize),
        page: String(page),
      })
      return `https://api.github.com/repos/${dataset.repo}/commits?${params.toString()}`
    },
    headers: (config) => {
      const headers = { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" }
      if (config.tokens.github) headers.Authorization = `Bearer ${config.tokens.github}`
      return headers
    },
  },
  gitcode: {
    label: "gitcode",
    listUrl: ({ dataset, page, pageSize, since }) => {
      const params = new URLSearchParams({
        since,
        per_page: String(pageSize),
        page: String(page),
      })
      return `https://api.gitcode.com/api/v5/repos/${dataset.repo}/commits?${params.toString()}`
    },
    headers: (config) => {
      const headers = { Accept: "application/json" }
      if (config.tokens.gitcode) headers["PRIVATE-TOKEN"] = config.tokens.gitcode
      return headers
    },
  },
}

const MIN_RATE_LIMIT_REMAINING = 5

export function makeCommitsCollector(providerName) {
  const provider = PROVIDERS[providerName]
  if (!provider) throw new Error(`未知 commits 上游: ${providerName}`)

  return async function collect({ config, dataset, state, logger, overrides = {} }) {
    const { since, source } = resolveWatermark({
      dataset,
      state,
      since: overrides.since,
      intervalMs: config.intervalMs,
      full: overrides.full,
    })
    const { timeoutMs, retries, backoffMs, pageSize } = config.request
    const options = { timeoutMs, retries, backoffMs, headers: provider.headers(config) }
    const maxPages = overrides.maxPages || 20
    // --limit：本轮最多处理的 commit 数（自检用）；被截断时水位退回窗口最旧一条，下一轮续传
    const maxItems = overrides.limit > 0 ? overrides.limit : 0

    const items = []
    let truncated = false
    for (let page = 1; page <= maxPages; page += 1) {
      const url = provider.listUrl({ dataset, page, pageSize, since })
      const { data, headers } = await requestJson(url, options)
      const batch = Array.isArray(data) ? data : []
      if (batch.length === 0) break
      items.push(...batch)
      const remaining = remainingRateLimit(headers)
      if (remaining !== null && remaining <= MIN_RATE_LIMIT_REMAINING) {
        truncated = true
        logger.warn(`上游剩余配额仅 ${remaining}，本轮提前结束，下轮从上一次水位续传`)
        break
      }
      if (batch.length < pageSize) break
      if (page === maxPages) truncated = true
    }

    let written = 0
    let skipped = 0
    let processed = 0
    let limited = false
    for (const item of items) {
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
      provider: provider.label,
    }
  }
}