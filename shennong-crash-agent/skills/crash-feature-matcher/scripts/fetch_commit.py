#!/usr/bin/env python3
"""Fetch first-hand upstream evidence for a community commit/issue.

This CLI exposes the same fetchers used internally by query_community_cases so
an agent can manually re-inspect a single commit diff / metadata / issue body
when the automatic verdict is ``unverified`` or ``same_area``.

Usage (run from the crash-feature-matcher skill directory):
  bash run_python.sh scripts/fetch_commit.py diff   <url>
  bash run_python.sh scripts/fetch_commit.py detail <url>
  bash run_python.sh scripts/fetch_commit.py issue  <url>
  bash run_python.sh scripts/fetch_commit.py search <owner/repo> <path> <keyword...>
                                        [--source gitcode|gitee] [--pages N]

NEVER `git clone` a kernel repository to find a fix commit — use `search`
(list commits touching a file, filtered by message keywords) followed by
`diff`/`detail` to verify the candidate.
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from crash_matcher.git_commit_fetcher import (
    fetch_commit_diff,
    fetch_commit_detail,
    fetch_issue_detail,
    search_commits,
)


async def _run(args: argparse.Namespace) -> None:
    if args.action == "diff":
        print((await fetch_commit_diff(args.url)) or "")
    elif args.action == "detail":
        data = await fetch_commit_detail(args.url)
        print(json.dumps(data, ensure_ascii=False, indent=2) if data else "{}")
    elif args.action == "issue":
        data = await fetch_issue_detail(args.url)
        print(json.dumps(data, ensure_ascii=False, indent=2) if data else "{}")
    else:  # search
        hits = await search_commits(
            repo=args.repo,
            path=args.path or "",
            keywords=args.keywords or [],
            source=args.source,
            max_pages=args.pages,
        )
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        print(f"\n# {len(hits)} matching commit(s); verify with: "
              f"fetch_commit.py diff <html_url>", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="fetch_commit.py",
        description="Fetch/search upstream community evidence without cloning repos",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    for name, helptext in (
        ("diff", "raw commit diff for a commit URL"),
        ("detail", "commit metadata (message/author/stats) for a commit URL"),
        ("issue", "issue/PR title and body for an issue URL"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("url", help="gitcode/gitee commit or issue URL")

    sp = sub.add_parser(
        "search",
        help="list commits touching a path whose message matches keywords (no clone)",
    )
    sp.add_argument("repo", help="owner/repo, e.g. openeuler/kernel")
    sp.add_argument("path", nargs="?", default="",
                    help="file path filter, e.g. net/netfilter/nf_tables_api.c")
    sp.add_argument("keywords", nargs="*",
                    help="keywords matched (case-insensitive) against commit message")
    sp.add_argument("--source", choices=["gitcode", "gitee"], default="gitcode")
    sp.add_argument("--pages", type=int, default=2,
                    help="number of 100-commit pages to scan (default 2)")

    args = parser.parse_args()
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())