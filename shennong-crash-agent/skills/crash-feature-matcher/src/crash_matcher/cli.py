"""CLI — 命令行宕机分析入口, 输出与 analyze_crash MCP 工具一致"""

import asyncio
import json
import sys
import logging
from pathlib import Path

import click

from .extractor import parse_dmesg, compute_signature, run_crash_analysis
from .matcher import match_crash
from .matcher.community_retriever import retrieve_community_cases
from .knowledge import RAGClient
from .config import Config

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("crash-matcher")


def _build_crash_dict(feature, host, sig):
    return {
        "crash_time": feature.crash_time,
        "signature": sig,
        "bug_type": feature.bug_type,
        "bug_key": feature.bug_key,
        "bug_summary": feature.bug_summary,
        "rip": feature.rip,
        "rip_function": feature.rip_function,
        "rip_offset": feature.rip_offset,
        "related_modules": feature.related_modules,
        "call_trace_signature": feature.call_trace_signature,
        "call_trace_text": feature.call_trace_text,
        "kernel_version": host.kernel_version,
    }


def _build_host_dict(host):
    return {
        "host_name": host.host_name,
        "kernel_version": host.kernel_version,
        "cpu_model": host.cpu_model,
        "machine_model": host.machine_model,
        "cpu_num": host.cpu_num,
        "memory_size": host.memory_size,
        "modules": host.modules,
    }


def _build_match_result(match_result):
    return {
        "matched": match_result.matched,
        "fingerprint_match": match_result.fingerprint_match,
        "knowledge": match_result.knowledge.model_dump() if match_result.knowledge else None,
        "similar_cases_count": len(match_result.similar_cases),
        "suggestions": match_result.suggestions,
    }


def _get_rag_cli(no_rag):
    if no_rag:
        return None
    rag_cfg = Config().get().rag
    if not rag_cfg.knowledge_kb_id:
        click.echo("error: RAG knowledge base not configured")
        sys.exit(1)
    return RAGClient()


@click.group()
def main():
    """Crash feature extraction and known-issue matching tool"""
    pass


@main.command()
@click.option("-f", "--file", "filepath", help="dmesg log file path")
@click.option("-t", "--text", "text", help="dmesg text passed via command line")
@click.option("--no-rag", is_flag=True, help="skip RAG, local feature extraction only")
def analyze(filepath, text, no_rag):
    """Analyze dmesg log, extract features and match known issues."""
    if filepath:
        content = Path(filepath).read_text(errors="replace")
    elif text:
        content = text
    else:
        click.echo("error: provide -f <file> or -t <text>")
        sys.exit(1)

    feature, host, _has_hw = parse_dmesg(content)
    sig = compute_signature(feature)
    rag = _get_rag_cli(no_rag)

    async def _run():
        try:
            return await match_crash(feature, host, rag)
        finally:
            if rag:
                await rag.close()

    match_result = asyncio.run(_run())

    click.echo(json.dumps({
        "signature": sig,
        "crash_features": _build_crash_dict(feature, host, sig),
        "host_features": _build_host_dict(host),
        "match_result": _build_match_result(match_result),
        "missing_fields": match_result.missing_fields,
    }, indent=2, ensure_ascii=False))


@main.command()
@click.option("--vmcore", required=True, help="vmcore file path")
@click.option("--vmlinux", required=True, help="vmlinux file path")
def analyze_vmcore(vmcore, vmlinux):
    """Analyze vmcore + vmlinux via crash command (local extraction only)."""
    feature, host, _has_hw = run_crash_analysis(vmcore, vmlinux)
    if feature is None:
        click.echo(json.dumps({"error": "crash command failed"}))
        sys.exit(1)

    sig = compute_signature(feature) if feature.rip else ""

    click.echo(json.dumps({
        "signature": sig,
        "crash_features": _build_crash_dict(feature, host, sig),
        "host_features": _build_host_dict(host),
    }, indent=2, ensure_ascii=False))


@main.command()
@click.option("--bug-type", "bug_type", help="filter by bug type")
@click.option("--rip-func", "rip_function", help="filter by RIP function")
@click.option("-k", "--keyword", help="semantic search keyword")
@click.option("-n", "--limit", default=5, help="max results")
def query(bug_type, rip_function, keyword, limit):
    """Query internal knowledge base."""
    rag = RAGClient()

    async def _query():
        if keyword:
            return await rag.search_issues_semantic(keyword, bug_type or "", limit)
        elif rip_function:
            return await rag.search_issues_by_rip_function(rip_function, bug_type or "", limit)
        else:
            return await rag.search_issues_semantic("", bug_type or "", limit)

    async def _run_query():
        try:
            return await _query()
        finally:
            await rag.close()

    issues = asyncio.run(_run_query())
    click.echo(json.dumps({
        "total": len(issues),
        "issues": [i.model_dump() for i in issues],
    }, indent=2, ensure_ascii=False))


@main.command()
@click.option("-f", "--file", "filepath", help="seed data JSON file path")
def import_seed(filepath):
    """Import seed knowledge base data."""
    if not filepath:
        click.echo(json.dumps({"error": "provide -f <json_file>"}))
        return

    data = json.loads(Path(filepath).read_text())
    issues = data.get("issues", [])
    rag = RAGClient()

    async def _import():
        count = 0
        for item in issues:
            from .models import CrashIssue
            if "signature" in item and "fingerprints" not in item:
                item["fingerprints"] = [item.pop("signature")]
            issue = CrashIssue(**item)
            await rag.create_issue(issue)
            count += 1
        return count

    async def _run_import():
        try:
            return await _import()
        finally:
            await rag.close()

    count = asyncio.run(_run_import())
    click.echo(json.dumps({"imported_count": count}, ensure_ascii=False))


@main.command()
@click.option("-q", "--query", "query_text", required=True, help="query text / crash keywords")
@click.option("-k", "--kernel-version", "kernel_version", default="", help="kernel version")
def query_community(query_text, kernel_version):
    """L1/L2/L3 community case retrieval (Linux/openEuler)."""
    rag = RAGClient()

    async def _run():
        try:
            result = await retrieve_community_cases(query_text, kernel_version, rag)
            click.echo(json.dumps({
                "matched": result.matched,
                "stop_reason": result.stop_reason,
                "total_candidates": result.total_candidates,
                "cases": [c.model_dump() for c in result.cases],
            }, indent=2, ensure_ascii=False))
        finally:
            await rag.close()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
