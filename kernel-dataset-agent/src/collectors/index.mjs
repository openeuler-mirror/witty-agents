// 采集器注册表：数据集 kind -> 采集函数。
import { collect as collectBugzilla } from "./linux-bugzilla.mjs"
import { makeCommitsCollector } from "./commits.mjs"
import { collect as collectEmail } from "./linux-email.mjs"
import { collect as collectIssues } from "./openeuler-issue.mjs"

const REGISTRY = {
  "bugzilla-rest": collectBugzilla,
  "github-commits": makeCommitsCollector("github"),
  "gitcode-commits": makeCommitsCollector("gitcode"),
  "gitcode-issues": collectIssues,
  "lkml-mhonarc": collectEmail,
}

export function collectorFor(kind) {
  const collector = REGISTRY[kind]
  if (!collector) throw new Error(`未注册的采集器类型: ${kind}`)
  return collector
}

export function knownKinds() {
  return Object.keys(REGISTRY)
}