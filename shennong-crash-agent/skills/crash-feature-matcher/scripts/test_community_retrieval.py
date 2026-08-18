#!/usr/bin/env python3
"""crash-feature-matcher 社区案例检索测试脚本"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from crash_matcher.knowledge.client import RAGClient
from crash_matcher.matcher.community_retriever import retrieve_community_cases


QUERIES = [
    ("空指针解引用 内核崩溃", ""),
    ("3c59x 网卡 boomerang_start_xmit page_address pci_map_single", "2.6.32-491.el6"),
    ("KVM 虚拟化 内核崩溃", ""),
    ("selinux 未初始化变量 内核崩溃", ""),
    ("ext4 文件系统 内核崩溃", ""),
]


async def main():
    rag = RAGClient()
    print("=" * 80)
    print("crash-feature-matcher 社区案例检索测试")
    print("=" * 80)
    for query, kv in QUERIES:
        print(f"\nQuery: {query}")
        if kv:
            print(f"Kernel: {kv}")
        result = await retrieve_community_cases(query, kv, rag)
        print(f"Matched: {result.matched}")
        print(f"Stop reason: {result.stop_reason}")
        print(f"Total candidates: {result.total_candidates}")
        print(f"Top cases:")
        for i, c in enumerate(result.cases, 1):
            print(f"  {i}. [{c.match_level}] score={c.score:.1f} source={c.source} kv={c.kernel_version}")
            print(f"     title: {c.title[:80]}")
            print(f"     score_details: {c.score_details}")
        print("-" * 80)
    await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
