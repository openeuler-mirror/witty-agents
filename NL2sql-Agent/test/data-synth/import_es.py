#!/usr/bin/env python3
"""将 data-synth 五表分片 JSON 导入 Elasticsearch。"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

import yaml

ROOT = Path(__file__).resolve().parent

INDEX_SPECS: dict[str, dict[str, Any]] = {
    "resident_population": {
        "dir": "resident_population",
        "id_fields": ("idcardno", "id"),
        "mappings": {
            "properties": {
                "id": {"type": "keyword"},
                "idcardno": {"type": "keyword"},
                "xm": {"type": "keyword"},
                "xb": {"type": "keyword"},
                "mz": {"type": "keyword"},
                "csrq": {"type": "keyword"},
                "zz": {"type": "keyword"},
                "sjlysd": {"type": "keyword"},
                "ywrksj": {"type": "keyword"},
            }
        },
    },
    "person_residence": {
        "dir": "person_residence",
        "id_fields": ("idcardno",),
        "mappings": {
            "properties": {
                "idcardno": {"type": "keyword"},
                "zz": {"type": "keyword"},
                "sjlysd": {"type": "keyword"},
                "ywrksj": {"type": "keyword"},
            }
        },
    },
    "ticket_trip": {
        "dir": "ticket_trip",
        "id_fields": ("ticket_no",),
        "mappings": {
            "properties": {
                "ticket_no": {"type": "keyword"},
                "id_name": {"type": "keyword"},
                "id_kind_new": {"type": "keyword"},
                "id_no": {"type": "keyword"},
                "train_date": {"type": "keyword"},
                "start_time": {"type": "keyword"},
                "board_train_code": {"type": "keyword"},
                "from_station_name": {"type": "keyword"},
                "to_station_name": {"type": "keyword"},
                "dt": {"type": "keyword"},
            }
        },
    },
    "ticket_order": {
        "dir": "ticket_order",
        "id_fields": ("ticket_no",),
        "mappings": {
            "properties": {
                "ticket_no": {"type": "keyword"},
                "coach_no": {"type": "keyword"},
                "seat_no": {"type": "keyword"},
                "seat_type_code_new": {"type": "keyword"},
                "ticket_type_new": {"type": "keyword"},
                "office_no": {"type": "keyword"},
                "window_no": {"type": "keyword"},
                "sale_time": {"type": "keyword"},
                "ticket_price": {"type": "keyword"},
                "sjlysd": {"type": "keyword"},
                "ywrksj": {"type": "keyword"},
            }
        },
    },
    "tag_person": {
        "dir": "tag_person",
        "id_fields": ("idcardno", "tag_name"),
        "mappings": {
            "properties": {
                "idcardno": {"type": "keyword"},
                "tag_name": {"type": "keyword"},
            }
        },
    },
    # 旧规则兼容：trip ⋈ order
    "ticket_sales": {
        "dir": "ticket_sales",
        "id_fields": ("ticket_no",),
        "mappings": {
            "properties": {
                "id_name": {"type": "keyword"},
                "id_kind_new": {"type": "keyword"},
                "id_no": {"type": "keyword"},
                "train_date": {"type": "keyword"},
                "start_time": {"type": "keyword"},
                "board_train_code": {"type": "keyword"},
                "from_station_name": {"type": "keyword"},
                "to_station_name": {"type": "keyword"},
                "coach_no": {"type": "keyword"},
                "seat_no": {"type": "keyword"},
                "seat_type_code_new": {"type": "keyword"},
                "ticket_no": {"type": "keyword"},
                "ticket_type_new": {"type": "keyword"},
                "office_no": {"type": "keyword"},
                "window_no": {"type": "keyword"},
                "sale_time": {"type": "keyword"},
                "ticket_price": {"type": "keyword"},
                "sjlysd": {"type": "keyword"},
                "ywrksj": {"type": "keyword"},
                "dt": {"type": "keyword"},
            }
        },
    },
}


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def es_request(
    host: str,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    content_type: str = "application/json",
    timeout: float = 120,
) -> tuple[int, Any]:
    url = host.rstrip("/") + path
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        code = e.code
    text = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {"raw": text[:500]}
    return code, data


def ensure_index(host: str, index: str, mappings: dict, *, recreate: bool, timeout: float) -> None:
    code, _ = es_request(host, "HEAD", f"/{index}", timeout=timeout)
    if code == 200:
        if recreate:
            print(f"[{index}] 已存在，删除后重建")
            es_request(host, "DELETE", f"/{index}", timeout=timeout)
        else:
            print(f"[{index}] 已存在，跳过创建")
            return
    body = json.dumps(
        {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "30s"},
            "mappings": mappings,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    code, data = es_request(host, "PUT", f"/{index}", body=body, timeout=timeout)
    if code >= 300:
        raise RuntimeError(f"创建索引失败 {index}: {code} {data}")
    print(f"[{index}] 已创建")


def iter_shard_docs(path: Path) -> Iterator[dict[str, Any]]:
    docs = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(docs, list):
        raise ValueError(f"期望 JSON 数组: {path}")
    for doc in docs:
        if isinstance(doc, dict):
            yield doc


def doc_id(index: str, doc: dict[str, Any], i: int) -> str:
    fields = INDEX_SPECS[index].get("id_fields") or ()
    if len(fields) == 1:
        return str(doc.get(fields[0]) or i)
    if fields:
        return "-".join(str(doc.get(f) or "") for f in fields) or str(i)
    return str(i)


def bulk_import(
    host: str,
    index: str,
    files: list[Path],
    *,
    bulk_size: int,
    timeout: float,
) -> dict[str, Any]:
    imported = 0
    errors = 0
    buf: list[str] = []
    n_in_buf = 0

    def flush() -> None:
        nonlocal imported, errors, buf, n_in_buf
        if not buf:
            return
        payload = ("\n".join(buf) + "\n").encode("utf-8")
        code, data = es_request(
            host,
            "POST",
            "/_bulk",
            body=payload,
            content_type="application/x-ndjson",
            timeout=timeout,
        )
        if code >= 300:
            raise RuntimeError(f"bulk 失败: {code} {data}")
        if data.get("errors"):
            for item in data.get("items") or []:
                act = item.get("index") or item.get("create") or {}
                if act.get("error"):
                    errors += 1
                    if errors <= 3:
                        print(f"  bulk item error: {act.get('error')}")
        imported += n_in_buf
        buf = []
        n_in_buf = 0

    for fp in files:
        print(f"[{index}] 导入 {fp.name} ...")
        for i, doc in enumerate(iter_shard_docs(fp)):
            meta = {"index": {"_index": index, "_id": doc_id(index, doc, i)}}
            buf.append(json.dumps(meta, ensure_ascii=False))
            buf.append(json.dumps(doc, ensure_ascii=False))
            n_in_buf += 1
            if n_in_buf >= bulk_size:
                flush()
        flush()
        print(f"[{index}] 累计导入 {imported}（errors={errors}）")

    es_request(host, "POST", f"/{index}/_refresh", timeout=timeout)
    code, cnt = es_request(host, "GET", f"/{index}/_count", timeout=timeout)
    count = (cnt or {}).get("count") if code < 300 else None
    return {"imported_approx": imported, "errors": errors, "es_count": count}


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 data-synth 五表到 Elasticsearch")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--data-dir", default=None, help="分片根目录，默认 config.output_dir")
    parser.add_argument("--host", default=None, help="覆盖 ES host")
    parser.add_argument("--indices", default="all", help="all 或逗号分隔索引名")
    parser.add_argument("--no-recreate", action="store_true", help="不删除已有索引")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    es_cfg = cfg.get("es") or {}
    host = (args.host or (es_cfg.get("hosts") or ["http://127.0.0.1:9200"])[0]).rstrip("/")
    bulk_size = int(es_cfg.get("bulk_size") or 2000)
    timeout = float(es_cfg.get("timeout_sec") or 120)
    recreate = (not args.no_recreate) and bool(es_cfg.get("recreate", True))

    data_dir = Path(args.data_dir or cfg.get("output_dir") or "./out")
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir

    try:
        code, _ = es_request(host, "GET", "/", timeout=10)
        if code >= 300:
            raise RuntimeError(f"ES 不可用: {code}")
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"无法连接 ES {host}: {e}"}, ensure_ascii=False))
        sys.exit(1)

    if args.indices.strip() == "all":
        names = list(INDEX_SPECS.keys())
    else:
        names = [x.strip() for x in args.indices.split(",") if x.strip()]

    summary = {}
    t0 = time.time()
    for name in names:
        if name not in INDEX_SPECS:
            summary[name] = {"ok": False, "error": "unknown index"}
            continue
        spec = INDEX_SPECS[name]
        shard_dir = data_dir / spec["dir"]
        files = sorted(shard_dir.glob(f"{spec['dir']}_*.json"))
        if not files:
            print(f"[{name}] 未找到分片: {shard_dir}")
            summary[name] = {"ok": False, "error": "no shards"}
            continue
        ensure_index(host, name, spec["mappings"], recreate=recreate, timeout=timeout)
        summary[name] = bulk_import(host, name, files, bulk_size=bulk_size, timeout=timeout)

    for name in names:
        if name not in INDEX_SPECS:
            continue
        es_request(
            host,
            "PUT",
            f"/{name}/_settings",
            body=json.dumps({"index": {"refresh_interval": "1s"}}).encode(),
            timeout=timeout,
        )

    print(
        json.dumps(
            {"ok": True, "host": host, "elapsed_sec": round(time.time() - t0, 1), "summary": summary},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
