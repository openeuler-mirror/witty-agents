#!/usr/bin/env python3
"""续传剩余未导入的知识库条目"""
import sys, os, json, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import requests
from crash_matcher.knowledge import RAGClient
from crash_matcher.models import CrashIssue
from crash_matcher.extractor.signature import compute_issue_signature
from crash_matcher.extractor.module import extract_dominant_modules
from crash_matcher.extractor.calltrace import parse_calltrace_functions, calltrace_similarity
from crash_matcher.matcher.classifier import BUG_KEY_TO_TYPE
from collections import defaultdict

OSCLINIC_URL = "https://osclinic.sankuai.com/v1/api/osclinic/query_panic_infos"
OSCLINIC_TOKEN = os.environ.get("OSCLINIC_TOKEN", "")
RAG_URL = "http://localhost:9988"
KB_ID = "94bdf5ea-afdf-478f-a473-d599c1e5a5e0"

def fetch_all():
    if not OSCLINIC_TOKEN:
        raise RuntimeError("OSCLINIC_TOKEN 环境变量未设置")
    headers = {"Content-Type": "application/json", "Token": OSCLINIC_TOKEN}
    r = requests.post(OSCLINIC_URL, json={"done":0,"limit":1,"offset":0,"filters":[]}, headers=headers, timeout=30); r.raise_for_status()
    total = r.json()["total"]
    rows, page, limit = [], 0, 100
    while len(rows) < total:
        r = requests.post(OSCLINIC_URL, json={"done":0,"limit":limit,"offset":page,"filters":[]}, headers=headers, timeout=30); r.raise_for_status()
        rows.extend(r.json()["table"]); print(f"Fetched page {page}: {len(rows)}/{total}"); page += 1
    return rows

def get_existing_ids():
    r = requests.post(f"{RAG_URL}/json/search", json={"search_json_configs":[{"kb_id":KB_ID,"query":"","top_k":200}]}, timeout=60)
    data = r.json()
    results = data.get("result",{}).get("jsons",[])
    ids = set()
    for item in results:
        content = item.get("content",{})
        if isinstance(content, dict) and content.get("source") == "issue":
            fp_list = content.get("fingerprints", [])
            if fp_list and fp_list[0]:
                ids.add(fp_list[0])
    return ids

def transform(row):
    rip = row.get("rip","") or ""
    bugkey = row.get("bugkey","") or ""
    bug_text = row.get("bug","") or ""
    ms = row.get("main_stack","") or ""
    hp_raw = row.get("HotPatch","") or ""

    rf = (rip.split("+0x")[0] if "+0x" in rip else rip).split("/0x")[0]
    ro = ("0x"+rip.split("+0x")[1].split("/")[0].split(" ")[0]) if "+0x" in rip else "0x0"

    bt = "unknown"
    for k,v in BUG_KEY_TO_TYPE.items():
        if k in bugkey or k in bug_text: bt = v; break

    dominant_mod, _qualified_modules = extract_dominant_modules(ms)
    mods = [] if dominant_mod == "kernel" else [dominant_mod]
    funcs = parse_calltrace_functions("Call Trace:\n" + ms)
    if not funcs:
        import re
        funcs = list(dict.fromkeys(re.findall(r"([a-zA-Z_][\w.]*)\+0x[0-9a-f]+", ms)))

    sig = compute_issue_signature(bt, mods, rf, ro)

    hp, sol = "", ""
    if hp_raw:
        is_hp = any(kw in hp_raw.lower() for kw in ("hotpatch","kpatch","cve-","livepatch",".ko"))
        is_sol = len(hp_raw)>40 or any(kw in hp_raw for kw in ("升级","修复","更新","config","echo","sysctl","modprobe"))
        hp, sol = (hp_raw if is_hp else ""), (hp_raw if is_sol else ("" if is_hp else hp_raw))

    return CrashIssue(
        knowledge_id=f"issue-{bt}-{rf[:25]}-tmp",
        fingerprints=[sig], bug_type=bt, bug_key=bugkey,
        bug_summary=bug_text[:200] if bug_text else bugkey,
        rip=rip, rip_function=rf, rip_offset=ro,
        related_modules=mods,
        call_trace_signature=funcs, call_trace_text=ms,
        kernel_versions=[row["kernel_version"]] if row.get("kernel_version","").strip() else [],
        history_wiki=row.get("history_wiki","") or "",
        hotpatch=hp, solution=sol,
        case_count=row.get("hitCounter",0) or 0,
        first_seen=row.get("create_time","") or "",
        last_seen=row.get("update_time","") or "",
    )

def dedup(issues):
    n = len(issues)
    parent = list(range(n))
    def find(x):
        while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
        return x
    def union(a,b):
        ra,rb=find(a),find(b)
        if ra!=rb: parent[ra]=rb

    # Group by bug_type
    groups = defaultdict(list)
    for i,issue in enumerate(issues): groups[issue.bug_type].append((i,issue))

    merge = 0
    for bt,group in groups.items():
        for ii in range(len(group)):
            for jj in range(ii+1, len(group)):
                i1, ia = group[ii]; i2, ib = group[jj]
                if find(i1)==find(i2): continue
                if ia.fingerprints==ib.fingerprints: union(i1,i2); merge+=1; continue
                if ia.rip_function and ib.rip_function and ia.rip_function==ib.rip_function: union(i1,i2); merge+=1; continue
                if ia.call_trace_signature and ib.call_trace_signature:
                    sim = calltrace_similarity(ia.call_trace_signature, ib.call_trace_signature)
                    if sim>0.75: union(i1,i2); merge+=1; continue

    print(f"Dedup: {n} -> {n-merge} (merged {merge} pairs)")

    merged = defaultdict(list)
    for i, issue in enumerate(issues): merged[find(i)].append(issue)
    result = []
    for g in merged.values():
        if len(g)==1: result.append(g[0])
        else:
            base = g[0]; av=set(); tc=0; fs=base.first_seen; ls=base.last_seen
            for item in g:
                av.update(item.kernel_versions); tc+=item.case_count
                if not base.hotpatch and item.hotpatch: base.hotpatch=item.hotpatch
                if not base.solution and item.solution: base.solution=item.solution
                if not base.history_wiki and item.history_wiki: base.history_wiki=item.history_wiki
                if item.first_seen and (not fs or item.first_seen<fs): fs=item.first_seen
                if item.last_seen and (not ls or item.last_seen>ls): ls=item.last_seen
            base.kernel_versions=sorted(av); base.case_count=tc; base.first_seen=fs; base.last_seen=ls
            result.append(base)
    result.sort(key=lambda x:x.case_count, reverse=True)
    return result

async def main():
    print("Fetching existing signatures from RAG...")
    existing = get_existing_ids()
    print(f"Existing signatures in RAG: {len(existing)}")

    print("Fetching from OSClinic...")
    rows = fetch_all()
    print(f"Total rows: {len(rows)}")

    issues = [transform(r) for r in rows]
    unique = dedup(issues)

    # Assign IDs and filter already-uploaded
    to_upload = []
    for idx, issue in enumerate(unique, 1):
        bt = issue.bug_type.replace("_","-")[:20]
        rf = (issue.rip_function or "unknown").replace(".","_")[:25].rstrip("_")
        issue.knowledge_id = f"issue-{bt}-{rf}-{idx:03d}"
        if issue.fingerprints and issue.fingerprints[0] not in existing:
            to_upload.append(issue)

    print(f"To upload: {len(to_upload)} (already in RAG: {len(unique)-len(to_upload)})")

    # Upload with raw requests (faster than RAGClient)
    success, fail = 0, 0
    for issue in to_upload:
        try:
            r = requests.post(
                f"{RAG_URL}/json/{KB_ID}",
                json={"name": issue.knowledge_id, "content": issue.model_dump(), "is_imediate": True},
                timeout=120
            )
            if r.status_code==200:
                jid = r.json().get("result",{}).get("json_id","?")
                print(f"  OK [{success+fail+1}/{len(to_upload)}] {issue.knowledge_id} -> {jid}")
                success += 1
            else:
                print(f"  FAIL [{success+fail+1}] {issue.knowledge_id}: HTTP {r.status_code}")
                fail += 1
        except Exception as e:
            print(f"  ERR [{success+fail+1}] {issue.knowledge_id}: {e}")
            fail += 1

    print(f"\nDone: success={success}, fail={fail}")

if __name__ == "__main__":
    asyncio.run(main())
