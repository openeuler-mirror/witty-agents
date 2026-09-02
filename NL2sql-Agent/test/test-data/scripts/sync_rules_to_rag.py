#!/usr/bin/env python3
"""将 rules_bundle/demo-es.json 同步到 rag-core JSON 知识库。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = ROOT / "rules_bundle" / "demo-es.json"


async def health(base_url: str, access_key: str, timeout: float) -> bool:
    url = f"{base_url.rstrip('/')}/kb/list"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_key}"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            r = await client.post(url, headers=headers, json={"page_num": 1, "page_size": 1})
            return r.status_code < 500
        except Exception:
            return False


async def create_json_kb(base_url: str, access_key: str, name: str, desc: str, timeout: float) -> str:
    url = f"{base_url.rstrip('/')}/kb"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_key}"}
    payload = {"name": name, "description": desc, "meta_data_type": "json"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        return data.get("result", {}).get("kb_id") or data.get("kb_id") or ""


async def upsert_rule(base_url: str, access_key: str, kb_id: str, name: str, content: dict, timeout: float) -> None:
    url = f"{base_url.rstrip('/')}/json/{kb_id}"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_key}"}
    payload = {"name": name, "content": content, "is_imediate": True}
    async with httpx.AsyncClient(timeout=max(timeout, 120)) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    p.add_argument("--kb-name", default="nl2sql-rules-demo-es")
    p.add_argument("--base-url", default=os.environ.get("RAG_BASE_URL", "http://127.0.0.1:19988"))
    p.add_argument("--access-key", default=os.environ.get("RAG_ACCESS_KEY", "nl2sql-local-key"))
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--timeout", type=float, default=60.0)
    args = p.parse_args()

    bundle_path = Path(args.bundle)
    rules = json.loads(bundle_path.read_text(encoding="utf-8"))
    if not await health(args.base_url, args.access_key, args.timeout):
        print(json.dumps({"ok": False, "error": f"rag-core 不可用: {args.base_url}"}, ensure_ascii=False))
        raise SystemExit(1)

    kb_id = await create_json_kb(
        args.base_url,
        args.access_key,
        args.kb_name,
        "NL2SQL 测试规则库 database_id=demo-es",
        args.timeout,
    )
    if not kb_id:
        print(json.dumps({"ok": False, "error": "未拿到 kb_id"}, ensure_ascii=False))
        raise SystemExit(2)

    sem = asyncio.Semaphore(max(1, args.concurrency))
    ok = 0
    errors: list[str] = []

    async def one(rule: dict) -> None:
        nonlocal ok
        name = str(rule.get("id") or rule.get("description") or "rule")[:120]
        async with sem:
            try:
                await upsert_rule(args.base_url, args.access_key, kb_id, name, rule, args.timeout)
                ok += 1
            except Exception as e:
                errors.append(f"{name}: {e}")

    await asyncio.gather(*(one(r) for r in rules))
    result = {
        "ok": not errors,
        "kb_id": kb_id,
        "kb_name": args.kb_name,
        "database_id": "demo-es",
        "synced": ok,
        "total": len(rules),
        "errors": errors[:8],
        "hint": "将 kb_id 写入 NL2SQL configs/datasources.yaml 中 demo-es.rules_kb_id",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
