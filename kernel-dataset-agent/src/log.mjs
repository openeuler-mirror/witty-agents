// 统一日志：时间戳 + 级别 + 数据集标记；常驻服务把 stdout/stderr 落到 .runtime/kernel-dataset.log。
const LEVELS = ["debug", "info", "warn", "error"]

export function createLogger({ level = "info", stream = process.stdout } = {}) {
  const threshold = LEVELS.indexOf(level)
  const write = (entryLevel, scope, message, extra) => {
    if (LEVELS.indexOf(entryLevel) < threshold) return
    const parts = [new Date().toISOString(), entryLevel.toUpperCase().padEnd(5)]
    if (scope) parts.push(`[${scope}]`)
    parts.push(message)
    if (extra !== undefined) {
      parts.push(typeof extra === "string" ? extra : JSON.stringify(extra))
    }
    stream.write(`${parts.join(" ")}\n`)
  }
  return {
    level,
    debug: (message, extra, scope) => write("debug", scope, message, extra),
    info: (message, extra, scope) => write("info", scope, message, extra),
    warn: (message, extra, scope) => write("warn", scope, message, extra),
    error: (message, extra, scope) => write("error", scope, message, extra),
    child: (scope) => ({
      debug: (message, extra) => write("debug", scope, message, extra),
      info: (message, extra) => write("info", scope, message, extra),
      warn: (message, extra) => write("warn", scope, message, extra),
      error: (message, extra) => write("error", scope, message, extra),
    }),
  }
}