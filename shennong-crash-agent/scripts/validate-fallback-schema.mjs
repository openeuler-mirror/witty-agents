#!/usr/bin/env node
/**
 * 校验 dist/index.js 内嵌 fallback prompt 中的 DiagnoseReport JSON 结构示例
 * 与 skills/crash-report-generator/schemas/crash-report-schema.json 保持一致。
 *
 * 背景（历史实证）：agent.md 读取失败时 dist 内嵌 prompt 是唯一指导，若其中的
 * 字段结构示例过时（如曾出现 anomaly_features / root_cause_analysis.analysis[]），
 * 会诱导生成无法通过 schema 强校验的报告。agent.md 是权威源，但 fallback 不允许
 * 与 schema 背离——本脚本在 npm run build 阶段做键名级硬校验。
 */

import { readFileSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const DIST_ENTRY = resolve(SCRIPT_DIR, "..", "dist", "index.js")
const SCHEMA_PATH = resolve(
  SCRIPT_DIR,
  "..",
  "skills",
  "crash-report-generator",
  "schemas",
  "crash-report-schema.json",
)

/** 从 dist 内嵌 prompt 中抽出第一个 ```json 代码块并解析（兼容模板字符串转义围栏 \`\`\`json）。 */
export function extractEmbeddedReportExample(distSource) {
  const marker = "var SHENNONG_BEHAVIORAL_SUMMARY = "
  const start = distSource.indexOf(marker)
  if (start < 0) throw new Error("SHENNONG_BEHAVIORAL_SUMMARY not found in dist/index.js")
  const fenceOpen = distSource.indexOf("\\`\\`\\`json", start)
  const fenceCloseToken = "\\`\\`\\`"
  if (fenceOpen < 0) throw new Error("embedded ```json example not found in fallback prompt")
  const bodyStart = distSource.indexOf("{", fenceOpen)
  const fenceClose = distSource.indexOf(fenceCloseToken, bodyStart)
  if (bodyStart < 0 || fenceClose < 0) throw new Error("embedded JSON example is malformed")
  return JSON.parse(distSource.slice(bodyStart, fenceClose))
}

/** 键名级一致性：示例对象的键必须 ⊆ schema properties，且必须覆盖 required 键。 */
export function checkSection(exampleObj, schemaSection, sectionName, { requireRequired = true } = {}) {
  const problems = []
  if (!exampleObj || typeof exampleObj !== "object" || Array.isArray(exampleObj)) {
    return [`fallback 示例的 ${sectionName} 不是对象`]
  }
  const schemaProps = Object.keys(schemaSection.properties || {})
  for (const key of Object.keys(exampleObj)) {
    if (!schemaProps.includes(key)) {
      problems.push(`fallback 示例 ${sectionName} 含 schema 未定义字段 "${key}"`)
    }
  }
  if (requireRequired) {
    for (const key of schemaSection.required || []) {
      if (!(key in exampleObj)) {
        problems.push(`fallback 示例 ${sectionName} 缺 schema 必填字段 "${key}"`)
      }
    }
  }
  return problems
}

export function validateFallbackAgainstSchema() {
  const dist = readFileSync(DIST_ENTRY, "utf8")
  const schema = JSON.parse(readFileSync(SCHEMA_PATH, "utf8"))
  const example = extractEmbeddedReportExample(dist)

  const problems = [
    ...checkSection(
      example.crash_feature_info,
      schema.properties.crash_feature_info,
      "crash_feature_info",
      { requireRequired: false },
    ),
    ...checkSection(
      example.root_cause_analysis,
      schema.properties.root_cause_analysis,
      "root_cause_analysis",
    ),
    ...checkSection(
      example.diagnosis_repair_result,
      schema.properties.diagnosis_repair_result,
      "diagnosis_repair_result",
      { requireRequired: false },
    ),
  ]

  if (problems.length > 0) {
    throw new Error(
      "dist fallback prompt 与 crash-report-schema 不一致（agent.md 不可用时它会诱导生成非法报告）：\n"
        + problems.map((p) => `  - ${p}`).join("\n"),
    )
  }
  return true
}
