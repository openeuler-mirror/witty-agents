#!/usr/bin/env python3
"""bootstrap 本地规则缓存 → 同步到该数据源绑定的 rag-core KB。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nl2sql_core.config import load_datasources, load_rag_settings  # noqa: E402
from nl2sql_core.rag_client import RagClient  # noqa: E402
from nl2sql_core.rules.bootstrap import bootstrap  # noqa: E402
from nl2sql_core.rules.store import RuleStore  # noqa: E402


async def wait_healthy(base_url: str, timeout: float = 20.0) -> bool:
    client = RagClient(load_rag_settings())
    client.settings.base_url = base_url
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        h = await client.health()
        if h.get("ok"):
            return True
        await asyncio.sleep(0.5)
    return False


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-id", default="local-es")
    parser.add_argument("--kb-name", default="", help="默认取 datasources.rules_kb_name")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--base-url", default="", help="覆盖 rag-core 地址")
    parser.add_argument("--skip-start", action="store_true")
    parser.add_argument("--skip-bootstrap", action="store_true")
    parser.add_argument("--reuse-kb", action="store_true", help="不新建 KB，复用已有 kb_id/同名库")
    args = parser.parse_args()

    ds = load_datasources().get(args.database_id) or {}
    kb_name = args.kb_name or str(ds.get("rules_kb_name") or f"nl2sql-rules-{args.database_id}")

    if not args.skip_bootstrap:
        boot = bootstrap(args.database_id)
        print(json.dumps({"bootstrap": boot}, ensure_ascii=False, indent=2))

    if not args.skip_start:
        subprocess.run(["bash", str(ROOT / "scripts" / "start_rag_core.sh")], check=False)

    rag_s = load_rag_settings()
    if args.base_url:
        rag_s.base_url = args.base_url
        os.environ["NL2SQL_RAG_BASE_URL"] = args.base_url

    if not await wait_healthy(rag_s.base_url):
        fallback = "http://127.0.0.1:9988"
        if rag_s.base_url != fallback and await wait_healthy(fallback):
            rag_s.base_url = fallback
            os.environ["NL2SQL_RAG_BASE_URL"] = fallback
        else:
            print(json.dumps({"ok": False, "error": f"rag-core 不可用: {rag_s.base_url}"}, ensure_ascii=False))
            sys.exit(1)

    store = RuleStore(args.database_id)
    store.rag = RagClient(rag_s)
    result = await store.sync_to_rag(
        kb_name=kb_name,
        concurrency=args.concurrency,
        recreate_kb=not args.reuse_kb,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
