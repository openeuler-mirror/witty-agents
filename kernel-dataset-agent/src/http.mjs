// 上游 HTTP 访问：超时、指数退避重试、429/403 限流识别。
// 限流或重试耗尽时抛出 RateLimitedError，由调用方保留水位、下一轮续传。
export class RateLimitedError extends Error {
  constructor(message) {
    super(message)
    this.name = "RateLimitedError"
    this.rateLimited = true
  }
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

export function sleep(milliseconds) {
  return delay(milliseconds)
}

function isRetryableStatus(status) {
  return status === 408 || status === 429 || status >= 500
}

export function remainingRateLimit(headers) {
  const remaining = headers.get("x-ratelimit-remaining")
  return remaining === null ? null : Number(remaining)
}

async function requestOnce(url, { headers, timeoutMs, method }) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { method, headers, signal: controller.signal, redirect: "follow" })
  } finally {
    clearTimeout(timer)
  }
}

async function request(url, options = {}) {
  const {
    headers = {},
    timeoutMs = 30000,
    retries = 3,
    backoffMs = 1000,
    method = "GET",
  } = options
  let lastError = null
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const response = await requestOnce(url, { headers, timeoutMs, method })
      if (response.ok) return response
      const body = await response.text().catch(() => "")
      // 403 在 GitHub 上常用于限流，配合剩余配额判断是否可重试
      const quotaExhausted = response.headers.get("x-ratelimit-remaining") === "0"
      if (response.status === 403 && quotaExhausted) {
        throw new RateLimitedError(`${method} ${url} 触发上游限流（剩余配额 0）`)
      }
      if (response.status === 429) {
        const retryAfter = Number(response.headers.get("retry-after") || 0)
        if (attempt === retries) {
          throw new RateLimitedError(`${method} ${url} 触发上游限流（429）`)
        }
        await delay(Math.max(retryAfter * 1000, backoffMs * 2 ** attempt))
        continue
      }
      if (!isRetryableStatus(response.status) || attempt === retries) {
        const error = new Error(`${method} ${url} 返回 ${response.status}: ${body.slice(0, 300)}`)
        error.status = response.status
        throw error
      }
      lastError = new Error(`${method} ${url} 返回 ${response.status}`)
    } catch (error) {
      if (error.rateLimited) throw error
      lastError = error
      if (attempt === retries) break
    }
    await delay(backoffMs * 2 ** attempt)
  }
  if (lastError?.name === "AbortError") {
    throw new Error(`${method} ${url} 超时（${timeoutMs}ms）`)
  }
  throw lastError || new Error(`${method} ${url} 请求失败`)
}

export async function requestJson(url, options = {}) {
  const response = await request(url, {
    ...options,
    headers: { Accept: "application/json", ...options.headers },
  })
  return { data: await response.json(), headers: response.headers }
}

export async function requestText(url, options = {}) {
  const response = await request(url, options)
  return { text: await response.text(), headers: response.headers }
}

// 探测型请求：404 视为“不存在”，其它错误照常抛出（用于 email 归档分片探测）
export async function probeText(url, options = {}) {
  try {
    return await requestText(url, options)
  } catch (error) {
    if (error.status === 404) return null
    throw error
  }
}