#!/usr/bin/env python3
"""从 FIELD-GUIDE / mapping + fixtures/rules 生成规则写入本地 RuleStore。"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nl2sql_core.rules.bootstrap import bootstrap  # noqa: E402
from nl2sql_core.rules.store import RuleStore  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-id", default="local-es")
    parser.add_argument("--sync-rag", action="store_true", help="尝试同步到 rag-core")
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()
    result = bootstrap(args.database_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.sync_rag:
        store = RuleStore(args.database_id)
        print(
            json.dumps(
                await store.sync_to_rag(concurrency=args.concurrency),
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
