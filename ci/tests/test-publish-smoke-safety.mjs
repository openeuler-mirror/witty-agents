#!/usr/bin/env node

import { decideLatestTagAction } from "../scripts/publish-smoke-package.mjs"

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, got ${actual}`)
  }
}

const publishedVersion = "0.10.5-ci.aarch64.1"

assertEqual(
  decideLatestTagAction(
    { state: "ready", version: "0.10.5" },
    { state: "ready", version: "0.10.5" },
    publishedVersion,
  ),
  "preserved",
  "an existing latest tag should remain unchanged",
)

assertEqual(
  decideLatestTagAction(
    { state: "ready", version: "0.10.5" },
    { state: "ready", version: publishedVersion },
    publishedVersion,
  ),
  "restore-previous",
  "a changed latest tag should be restored",
)

assertEqual(
  decideLatestTagAction(
    { state: "not-found", version: null },
    { state: "ready", version: publishedVersion },
    publishedVersion,
  ),
  "remove-auto-created",
  "a first publish should remove npm's automatically created latest tag",
)

assertEqual(
  decideLatestTagAction(
    { state: "not-found", version: null },
    { state: "not-found", version: null },
    publishedVersion,
  ),
  "absent",
  "an absent latest tag should remain absent",
)

let unsafeChangeRejected = false
try {
  decideLatestTagAction(
    { state: "not-found", version: null },
    { state: "ready", version: "9.9.9" },
    publishedVersion,
  )
} catch {
  unsafeChangeRejected = true
}
if (!unsafeChangeRejected) throw new Error("an unrelated latest tag must never be removed")

console.log("npm smoke latest-tag safety: PASS")
