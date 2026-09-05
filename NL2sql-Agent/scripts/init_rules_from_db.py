#!/usr/bin/env python3
"""从真实数据源生成规则包 JSON；确认后再 commit 到 rag-core。不启 Web 也可跑。"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nl2sql_core.rules.init import (  # noqa: E402
    commit_bundle,
    init_from_datasource,
    load_bundle,
    write_bundle,
)


async def main() -> None:
    p = argparse.ArgumentParser(description="从数据源初始化 NL2SQL 规则包")
    p.add_argument("--database-id", default="local-es")
    p.add_argument("--from-file", default="", help="已有规则包路径（与生成互斥，配合 --commit）")
    p.add_argument("--out", default="", help="规则包输出路径，默认 data/rules/init_bundles/")
    p.add_argument("--no-llm", action="store_true", help="不调用 LLM 生成 domain/example")
    p.add_argument("--commit", action="store_true", help="写入 rag-core")
    p.add_argument("--reuse-kb", action="store_true", help="不新建 KB，复用已有 kb_id/同名库")
    p.add_argument("--no-persist-kb", action="store_true", help="不回写 datasources.yaml 的 rules_kb_id")
    p.add_argument("--kb-name", default="", help="覆盖 KB 名")
    p.add_argument("--concurrency", type=int, default=8)
    args = p.parse_args()

    if args.commit and args.from_file:
        result = await commit_bundle(
            args.from_file,
            recreate_kb=not args.reuse_kb,
            persist_kb=not args.no_persist_kb,
            kb_name=args.kb_name or None,
            concurrency=args.concurrency,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get("ok"):
            raise SystemExit(2)
        return

    bundle = await init_from_datasource(
        args.database_id,
        include_llm_domain=not args.no_llm,
    )
    out = Path(args.out) if args.out else None
    path = write_bundle(bundle, out)
    summary = {
        "ok": bundle.get("ok"),
        "database_id": bundle.get("database_id"),
        "engine": bundle.get("engine"),
        "counts": bundle.get("counts"),
        "warnings": bundle.get("warnings"),
        "bundle_path": str(path),
        "hint": "检查 JSON 后执行: python3 scripts/init_rules_from_db.py --commit --from-file " + str(path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.commit:
        result = await commit_bundle(
            load_bundle(path),
            recreate_kb=not args.reuse_kb,
            persist_kb=not args.no_persist_kb,
            kb_name=args.kb_name or None,
            concurrency=args.concurrency,
        )
        print(json.dumps({"commit": result}, ensure_ascii=False, indent=2))
        if not result.get("ok"):
            raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
