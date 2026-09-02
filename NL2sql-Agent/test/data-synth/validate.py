#!/usr/bin/env python3
"""校验 data-synth 五表分片：行数、必填字段、日期、跨表关联抽样。"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent

TABLES = (
    "resident_population",
    "person_residence",
    "ticket_trip",
    "ticket_order",
    "tag_person",
    "ticket_sales",  # 规则兼容视图
)

REQUIRED = {
    "resident_population": ("id", "idcardno", "xm", "xb", "mz", "csrq", "zz"),
    "person_residence": ("idcardno", "zz", "sjlysd", "ywrksj"),
    "ticket_trip": (
        "ticket_no",
        "id_no",
        "id_name",
        "train_date",
        "from_station_name",
        "to_station_name",
        "board_train_code",
    ),
    "ticket_order": ("ticket_no", "sale_time", "ticket_price", "coach_no", "seat_no"),
    "tag_person": ("idcardno", "tag_name"),
    "ticket_sales": (
        "ticket_no",
        "id_no",
        "from_station_name",
        "to_station_name",
        "train_date",
        "coach_no",
        "ticket_price",
    ),
}


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def iter_docs(data_dir: Path, table: str):
    d = data_dir / table
    for fp in sorted(d.glob(f"{table}_*.json")):
        docs = json.loads(fp.read_text(encoding="utf-8"))
        if not isinstance(docs, list):
            raise ValueError(f"非数组: {fp}")
        for doc in docs:
            yield doc


def count_docs(data_dir: Path, table: str) -> int:
    n = 0
    for _ in iter_docs(data_dir, table):
        n += 1
    return n


def sample_keys(data_dir: Path, table: str, field: str, limit: int, rng: random.Random) -> set[str]:
    """蓄水池抽样字段值。"""
    reservoir: list[str] = []
    seen = 0
    for doc in iter_docs(data_dir, table):
        v = doc.get(field)
        if v is None:
            continue
        seen += 1
        s = str(v)
        if len(reservoir) < limit:
            reservoir.append(s)
        else:
            j = rng.randint(1, seen)
            if j <= limit:
                reservoir[j - 1] = s
    return set(reservoir)


def load_key_set(data_dir: Path, table: str, field: str, keys: set[str]) -> set[str]:
    """加载指定 key 是否存在（扫表，仅匹配 keys）。"""
    found: set[str] = set()
    if not keys:
        return found
    for doc in iter_docs(data_dir, table):
        v = doc.get(field)
        if v is not None and str(v) in keys:
            found.add(str(v))
            if len(found) >= len(keys):
                break
    return found


def parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def validate(data_dir: Path, *, expect_rows: int | None, sample_size: int, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    errors: list[str] = []
    warnings: list[str] = []
    counts: dict[str, int] = {}

    for table in TABLES:
        shard_dir = data_dir / table
        if not shard_dir.is_dir():
            errors.append(f"缺少目录: {shard_dir}")
            continue
        files = list(shard_dir.glob(f"{table}_*.json"))
        if not files:
            errors.append(f"无分片: {shard_dir}")
            continue

        n = 0
        req = REQUIRED[table]
        checked = 0
        for doc in iter_docs(data_dir, table):
            n += 1
            if checked < sample_size:
                for f in req:
                    if doc.get(f) in (None, ""):
                        errors.append(f"{table}: 缺字段 {f} @row≈{n}")
                if table == "resident_population":
                    d = parse_date(str(doc.get("csrq") or ""))
                    if d is None or d.year < 1900 or d.year > 2026:
                        errors.append(f"resident_population: 非法 csrq={doc.get('csrq')}")
                if table == "ticket_trip":
                    d = parse_date(str(doc.get("train_date") or ""))
                    if d is None:
                        errors.append(f"ticket_trip: 非法 train_date={doc.get('train_date')}")
                checked += 1
            if len(errors) > 50:
                break
        counts[table] = n
        if expect_rows is not None and n != expect_rows:
            errors.append(f"{table}: 行数 {n} != 期望 {expect_rows}")

    # 关联抽样：residence / tag / trip → person；order → trip
    if "resident_population" in counts and counts["resident_population"] > 0:
        person_sample = sample_keys(data_dir, "resident_population", "idcardno", sample_size, rng)
        # 反向：从子表抽样，检查父表存在
        for child, fk, parent, pf in (
            ("person_residence", "idcardno", "resident_population", "idcardno"),
            ("tag_person", "idcardno", "resident_population", "idcardno"),
            ("ticket_trip", "id_no", "resident_population", "idcardno"),
        ):
            if child not in counts or counts[child] == 0:
                continue
            child_keys = sample_keys(data_dir, child, fk, sample_size, rng)
            found = load_key_set(data_dir, parent, pf, child_keys)
            missing = child_keys - found
            if missing:
                errors.append(f"关联失败 {child}.{fk} → {parent}.{pf}: 抽样缺失 {len(missing)} 例，如 {next(iter(missing))}")
            else:
                warnings.append(f"关联OK {child}.{fk}→{parent}.{pf}（抽样 {len(child_keys)}）")

        # order / sales → trip
        if counts.get("ticket_order") and counts.get("ticket_trip"):
            order_keys = sample_keys(data_dir, "ticket_order", "ticket_no", sample_size, rng)
            found = load_key_set(data_dir, "ticket_trip", "ticket_no", order_keys)
            missing = order_keys - found
            if missing:
                errors.append(
                    f"关联失败 ticket_order.ticket_no → ticket_trip.ticket_no: "
                    f"抽样缺失 {len(missing)}，如 {next(iter(missing))}"
                )
            else:
                warnings.append(f"关联OK ticket_order.ticket_no→ticket_trip.ticket_no（抽样 {len(order_keys)}）")

        if counts.get("ticket_sales") and counts.get("ticket_trip"):
            sales_keys = sample_keys(data_dir, "ticket_sales", "ticket_no", sample_size, rng)
            found = load_key_set(data_dir, "ticket_trip", "ticket_no", sales_keys)
            missing = sales_keys - found
            if missing:
                errors.append(
                    f"关联失败 ticket_sales.ticket_no → ticket_trip.ticket_no: "
                    f"抽样缺失 {len(missing)}"
                )
            else:
                warnings.append(f"关联OK ticket_sales↔ticket_trip（抽样 {len(sales_keys)}）")
            if counts.get("ticket_sales") != counts.get("ticket_trip"):
                errors.append(
                    f"ticket_sales({counts.get('ticket_sales')}) 与 "
                    f"ticket_trip({counts.get('ticket_trip')}) 行数应一致"
                )

        # residence 与 person 行数应一致（1:1）
        if counts.get("person_residence") != counts.get("resident_population"):
            warnings.append(
                f"person_residence({counts.get('person_residence')}) 与 "
                f"resident_population({counts.get('resident_population')}) 行数不同（期望 1:1）"
            )

        # 基表期望行数；ticket_sales 也应 = expect
        base = (
            "resident_population",
            "person_residence",
            "ticket_trip",
            "ticket_order",
            "tag_person",
            "ticket_sales",
        )
        if expect_rows is not None:
            for table in base:
                if table in counts and counts[table] != expect_rows:
                    # 上面循环已对 TABLES 做过 expect 检查，此处不重复
                    pass

    ok = not errors
    return {
        "ok": ok,
        "data_dir": str(data_dir),
        "counts": counts,
        "expect_rows": expect_rows,
        "errors": errors[:30],
        "warnings": warnings[:30],
        "error_count": len(errors),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="校验 data-synth 五表数据")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--expect-rows", type=int, default=None, help="期望每表行数；默认读 config")
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    data_dir = Path(args.data_dir or cfg.get("output_dir") or "./out")
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    expect = args.expect_rows
    if expect is None:
        expect = int(cfg.get("rows_per_table") or 0) or None

    result = validate(data_dir, expect_rows=expect, sample_size=args.sample_size, seed=args.seed)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
