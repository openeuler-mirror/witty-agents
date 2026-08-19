#!/usr/bin/env python3
"""OSClinic 知识库 → euler-copilot-rag 数据导入脚本

用法:
    cd /opt/zhaoxuedong/crash-feature-matcher
    PYTHONPATH=src python3 scripts/import_from_osclinic.py
"""

import sys
import os
import json
import asyncio
import logging
from collections import defaultdict
from typing import Optional

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from crash_matcher.models import CrashIssue
from crash_matcher.knowledge import RAGClient
from crash_matcher.extractor.signature import compute_issue_signature
from crash_matcher.extractor.module import extract_dominant_modules
from crash_matcher.extractor.calltrace import parse_calltrace_functions, calltrace_similarity
from crash_matcher.matcher.classifier import BUG_KEY_TO_TYPE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("import-osclinic")

# ============================================================
# OSClinic API 配置 (复用 query_crash_client.py)
# ============================================================
OSCLINIC_URL = "https://osclinic.sankuai.com/v1/api/osclinic/query_panic_infos"
OSCLINIC_TOKEN = os.environ.get("OSCLINIC_TOKEN", "")

# ============================================================
# 字段解析辅助
# ============================================================


def _extract_rip_function(rip: str) -> str:
    if not rip:
        return ""
    func = rip.split("+0x")[0] if "+0x" in rip else rip
    func = func.split("/0x")[0] if "/0x" in func else func
    return func


def _extract_rip_offset(rip: str) -> str:
    if "+0x" in rip:
        offset = rip.split("+0x")[1]
        return "0x" + offset.split("/")[0].split(" ")[0]
    return "0x0"


def classify_bug_type_from_key(bugkey: str, bug_text: str) -> str:
    """用 classifier 的映射表分类 bug_type"""
    for key, btype in BUG_KEY_TO_TYPE.items():
        if key in bugkey or key in bug_text:
            return btype
    return "unknown"


def split_hotpatch(raw: str) -> tuple[str, str]:
    """拆分 OSClinic HotPatch → (hotpatch, solution)"""
    if not raw or not raw.strip():
        return "", ""
    raw = raw.strip()
    is_hp = any(kw in raw.lower() for kw in ("hotpatch", "kpatch", "cve-", "livepatch", ".ko"))
    is_sol = len(raw) > 40 or any(kw in raw for kw in ("升级", "修复", "更新", "config", "echo", "sysctl", "modprobe", "rmmod"))
    hp = raw if is_hp else ""
    sol = raw if is_sol else ("" if is_hp else raw)
    return hp, sol


def make_knowledge_id(bug_type: str, rip_func: str, idx: int) -> str:
    """生成 knowledge_id: issue-{bug_type}-{rip_func_short}-{idx:03d}"""
    bt = bug_type.replace("_", "-")[:20]
    rf = rip_func.replace(".", "_")[:25].rstrip("_") if rip_func else "unknown"
    return f"issue-{bt}-{rf}-{idx:03d}"


# ============================================================
# OSClinic 数据拉取
# ============================================================


def fetch_all_kb() -> list[dict]:
    """分页拉取全量知识库"""
    if not OSCLINIC_TOKEN:
        raise RuntimeError("OSCLINIC_TOKEN 环境变量未设置")
    headers = {"Content-Type": "application/json", "Token": OSCLINIC_TOKEN}
    # 先查 total
    r = requests.post(
        OSCLINIC_URL,
        json={"done": 0, "limit": 1, "offset": 0, "filters": []},
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    total = r.json()["total"]
    logger.info(f"OSClinic 知识库总量: {total} 条")

    all_rows = []
    page, limit = 0, 100
    while len(all_rows) < total:
        r = requests.post(
            OSCLINIC_URL,
            json={"done": 0, "limit": limit, "offset": page, "filters": []},
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        rows = data.get("table", [])
        all_rows.extend(rows)
        logger.info(f"  第 {page} 页: 获取 {len(rows)} 条, 累计 {len(all_rows)}/{total}")
        page += 1

    return all_rows


# ============================================================
# 转换逻辑
# ============================================================


def transform_to_issue(row: dict) -> CrashIssue:
    """OSClinic kb row → CrashIssue"""
    rip = row.get("rip", "") or ""
    bugkey = row.get("bugkey", "") or ""
    bug_text = row.get("bug", "") or ""
    main_stack = row.get("main_stack", "") or ""
    hotpatch_raw = row.get("HotPatch", "") or ""

    rip_func = _extract_rip_function(rip)
    rip_off = _extract_rip_offset(rip)

    bug_type = classify_bug_type_from_key(bugkey, bug_text)
    dominant_mod, _qualified_modules = extract_dominant_modules(main_stack)
    related_mods = [] if dominant_mod == "kernel" else [dominant_mod]

    # main_stack 是换行分隔的函数调用
    calltrace_text = main_stack
    calltrace_funcs = parse_calltrace_functions(f"Call Trace:\n{main_stack}")
    if not calltrace_funcs:
        # 降级: 直接正则提取 all func+0x patterns
        import re
        calltrace_funcs = re.findall(r"([a-zA-Z_][\w.]*)\+0x[0-9a-f]+", main_stack)
        calltrace_funcs = list(dict.fromkeys(calltrace_funcs))  # 去重保序

    sig = compute_issue_signature(bug_type, related_mods, rip_func, rip_off)

    hotpatch, solution = split_hotpatch(hotpatch_raw)

    return CrashIssue(
        knowledge_id="pending",
        fingerprints=[sig],
        bug_type=bug_type,
        bug_key=bugkey,
        bug_summary=bug_text[:200] if bug_text else bugkey,
        rip=rip,
        rip_function=rip_func,
        rip_offset=rip_off,
        related_modules=related_mods,
        call_trace_signature=calltrace_funcs,
        call_trace_text=calltrace_text,
        kernel_versions=[row["kernel_version"]] if row.get("kernel_version", "").strip() else [],
        history_wiki=row.get("history_wiki", "") or "",
        hotpatch=hotpatch,
        solution=solution,
        case_count=row.get("hitCounter", 0) or 0,
        first_seen=row.get("create_time", "") or "",
        last_seen=row.get("update_time", "") or "",
    )


# ============================================================
# 去重合并 (使用 skill 匹配策略)
# ============================================================


def deduplicate_issues(issues: list[CrashIssue]) -> list[CrashIssue]:
    """按 skill 匹配策略去重合并
    策略:
      L1: signature 完全相同 → 一定是同一个问题
      L2: rip_function 相同 + bug_type 相同 → 很可能是同一个
      L3: calltrace_similarity > 0.75 → 大概率同一个
    """
    n_total = len(issues)
    # 按 bug_type 分组
    groups: dict[str, list[CrashIssue]] = defaultdict(list)
    for issue in issues:
        groups[issue.bug_type].append(issue)

    # Union-Find 合并
    parent = {i: i for i in range(n_total)}
    idx_map = {id(issue): i for i, issue in enumerate(issues)}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # 组内两两比对
    merge_count = 0
    for btype, group in groups.items():
        n = len(group)
        if n < 2:
            continue
        for i in range(n):
            for j in range(i + 1, n):
                ia, ib = group[i], group[j]
                idx_a, idx_b = idx_map[id(ia)], idx_map[id(ib)]
                if find(idx_a) == find(idx_b):
                    continue

                # L1: 签名相同
                if ia.fingerprints == ib.fingerprints:
                    union(idx_a, idx_b)
                    merge_count += 1
                    continue

                # L2: rip_function 相同 + bug_type 相同
                if ia.rip_function and ib.rip_function and ia.rip_function == ib.rip_function:
                    union(idx_a, idx_b)
                    merge_count += 1
                    continue

                # L3: 调用栈相似度
                if ia.call_trace_signature and ib.call_trace_signature:
                    sim = calltrace_similarity(ia.call_trace_signature, ib.call_trace_signature)
                    if sim > 0.75:
                        union(idx_a, idx_b)
                        merge_count += 1
                        continue

    logger.info(f"  去重合并: {n_total} → {n_total - merge_count} 条 (合并了 {merge_count} 对)")

    # 按根节点分组合并
    merged_groups: dict[int, list[CrashIssue]] = defaultdict(list)
    for i, issue in enumerate(issues):
        root = find(i)
        merged_groups[root].append(issue)

    result: list[CrashIssue] = []
    for g_items in merged_groups.values():
        if len(g_items) == 1:
            result.append(g_items[0])
        else:
            merged = _merge_issues(g_items)
            result.append(merged)

    # 排序: case_count 降序
    result.sort(key=lambda x: x.case_count, reverse=True)
    return result


def _merge_issues(items: list[CrashIssue]) -> CrashIssue:
    """合并多条同质 issue"""
    base = items[0]
    all_versions = set()
    total_cases = 0
    first_seen = base.first_seen
    last_seen = base.last_seen

    for item in items:
        all_versions.update(item.kernel_versions)
        total_cases += item.case_count
        # 优先保留有 hotpatch / solution / wiki 的
        if not base.hotpatch and item.hotpatch:
            base.hotpatch = item.hotpatch
        if not base.solution and item.solution:
            base.solution = item.solution
        if not base.history_wiki and item.history_wiki:
            base.history_wiki = item.history_wiki
        if item.first_seen and (not first_seen or item.first_seen < first_seen):
            first_seen = item.first_seen
        if item.last_seen and (not last_seen or item.last_seen > last_seen):
            last_seen = item.last_seen

    base.kernel_versions = sorted(all_versions)
    base.case_count = total_cases
    base.first_seen = first_seen
    base.last_seen = last_seen
    return base


# ============================================================
# 主流程
# ============================================================


async def main():
    # 1. 拉取
    logger.info("=" * 60)
    logger.info("步骤1: 从 OSClinic 拉取全量知识库")
    logger.info("=" * 60)
    rows = fetch_all_kb()
    logger.info(f"拉取完成: {len(rows)} 条原始记录")

    # 2. 转换
    logger.info("")
    logger.info("=" * 60)
    logger.info("步骤2: 转换字段 + 分类 bug_type")
    logger.info("=" * 60)
    issues = []
    stats = defaultdict(int)
    for row in rows:
        try:
            issue = transform_to_issue(row)
            issues.append(issue)
            stats[issue.bug_type] += 1
        except Exception as e:
            logger.warning(f"转换失败 row[{row.get('id')}]: {e}")

    logger.info(f"转换完成: {len(issues)} 条")
    logger.info("bug_type 分布:")
    for bt, cnt in sorted(stats.items(), key=lambda x: -x[1]):
        logger.info(f"  {bt}: {cnt}")

    # 3. 去重
    logger.info("")
    logger.info("=" * 60)
    logger.info("步骤3: 去重合并 (使用 skill 匹配策略)")
    logger.info("=" * 60)
    unique = deduplicate_issues(issues)
    logger.info(f"去重后: {len(unique)} 条")

    # 4. 分配 knowledge_id
    for idx, issue in enumerate(unique, 1):
        issue.knowledge_id = make_knowledge_id(issue.bug_type, issue.rip_function, idx)

    # 5. 上传 RAG
    logger.info("")
    logger.info("=" * 60)
    logger.info("步骤4: 上传到 euler-copilot-rag")
    logger.info("=" * 60)
    rag = RAGClient()
    success, failed = 0, 0
    for issue in unique:
        try:
            await rag.create_issue(issue)
            success += 1
            if success % 50 == 0:
                logger.info(f"  已上传 {success}/{len(unique)}")
        except Exception as e:
            logger.error(f"  上传失败 [{issue.knowledge_id}]: {e}")
            failed += 1

    await rag.close()
    logger.info(f"上传完成: 成功 {success}, 失败 {failed}")

    # 6. 输出示例
    logger.info("")
    logger.info("=" * 60)
    logger.info("导入完成! 样例数据 (前 5 条):")
    logger.info("=" * 60)
    for issue in unique[:5]:
        logger.info(f"  [{issue.knowledge_id}] {issue.bug_type}")
        logger.info(f"    rip: {issue.rip_function}+{issue.rip_offset}")
        logger.info(f"    fingerprints: {issue.fingerprints}")
        logger.info(f"    cases: {issue.case_count}")
        logger.info(f"    hotpatch: {issue.hotpatch or '(无)'}")
        logger.info(f"    solution: {issue.solution[:60] if issue.solution else '(无)'}")


if __name__ == "__main__":
    asyncio.run(main())
