#!/usr/bin/env python3
"""
生成五表分片 JSON，并物化旧规则兼容的 ticket_sales。

- 五基表各 rows_per_table 行
- resident_population 带 zz/sjlysd/ywrksj（规则仍查主档住址）
- ticket_sales = ticket_trip ⋈ ticket_order（规则仍查 ticket_sales）
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from lib.vocab import (  # noqa: E402
    CITIES,
    ETHNICITIES,
    GIVEN,
    HOT_CITIES,
    HOT_TAGS,
    SEAT_TYPES,
    SURNAMES,
    TAG_NAMES,
    TICKET_TYPES,
    TRAIN_PREFIXES,
)
from lib.writers import ShardWriter  # noqa: E402

CSRQ_START = date(1956, 1, 1)
CSRQ_END = date(2008, 12, 31)
BASE_NOW = date(2026, 7, 20)

# 业务五表
BASE_TABLES = (
    "resident_population",
    "person_residence",
    "ticket_trip",
    "ticket_order",
    "tag_person",
)
# 规则兼容（由 trip+order 物化）
COMPAT_TABLES = ("ticket_sales",)

# 评测热点：覆盖旧 test_queries 高频 (标签, 到站[, 发站])；飞机/大巴/酒店仍无表，靠规则忽略
QUERY_PATTERNS: list[dict[str, Any]] = [
    {"tags": ["信访人员"], "to": "北京", "from": None, "train_prefix": "G"},
    {"tags": ["失信人员"], "to": "上海", "from": None, "train_prefix": None},
    {"tags": ["党员"], "to": "广州", "from": None, "train_prefix": None},
    {"tags": ["刑满释放"], "to": "深圳", "from": None, "train_prefix": "G"},
    {"tags": ["重点关注"], "to": "成都", "from": None, "train_prefix": None},
    {"tags": ["涉稳人员"], "to": "杭州", "from": None, "train_prefix": None},
    {"tags": ["信访人员", "党员"], "to": "北京", "from": None, "train_prefix": "K"},
    {"tags": ["信访人员", "失信人员"], "to": "北京", "from": None, "train_prefix": None},
    {"tags": ["信访人员", "刑满释放"], "to": "广州", "from": None, "train_prefix": None},
    {"tags": ["涉稳人员", "刑满释放"], "to": "北京", "from": None, "train_prefix": None},
    {"tags": ["重点关注"], "to": "北京", "from": "广州", "train_prefix": "G"},
    {"tags": ["信访人员"], "to": "武汉", "from": None, "train_prefix": "K"},
    {"tags": [], "to": "北京", "from": "南京", "train_prefix": None},  # 大巴类问句忽略交通后仍有 OD
    {"tags": [], "to": "上海", "from": "北京", "train_prefix": "G"},
    {"tags": [], "to": "北京", "from": "广州", "train_prefix": None},
    {"tags": [], "to": "武汉", "from": "深圳", "train_prefix": "G"},
    {"tags": [], "to": "成都", "from": "杭州", "train_prefix": None},
    {"tags": [], "to": "乌鲁木齐", "from": "西安", "train_prefix": "T"},
    {"tags": [], "to": "三亚", "from": None, "train_prefix": None},
    {"tags": ["信访人员"], "to": "北京", "from": "重庆", "train_prefix": "K"},
    {"tags": ["党员"], "to": "北京", "from": None, "train_prefix": None},
    {"tags": ["失信人员"], "to": "上海", "from": None, "train_prefix": "K"},
    {"tags": ["刑满释放"], "to": "北京", "from": None, "train_prefix": None},
    {"tags": ["重点关注", "涉稳人员"], "to": "北京", "from": None, "train_prefix": None},
]


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def random_date(rng: random.Random, start: date, end: date) -> date:
    days = (end - start).days
    return start + timedelta(days=rng.randint(0, max(0, days)))


def fmt_dt(d: date, with_tz: bool = False) -> str:
    if with_tz:
        return f"{d.isoformat()} 12:00:00.000000+08"
    return f"{d.isoformat()} 12:00:00"


def make_name(rng: random.Random) -> str:
    return rng.choice(SURNAMES) + rng.choice(GIVEN)


def make_idcard(seq: int, birth: date) -> str:
    high = (seq // 1000) % 1_000_000
    low = seq % 1000
    check = "0123456789X"[seq % 11]
    return f"{high:06d}{birth.strftime('%Y%m%d')}{low:03d}{check}"


def make_ticket_no(global_ticket_seq: int) -> str:
    return f"{global_ticket_seq:014d}"


def allocate_int(total: int, n_bins: int, rng: random.Random) -> list[int]:
    if n_bins <= 0:
        return []
    if total <= 0:
        return [0] * n_bins
    cuts = sorted(rng.randint(0, total) for _ in range(n_bins - 1))
    cuts = [0] + cuts + [total]
    return [cuts[i + 1] - cuts[i] for i in range(n_bins)]


def birth_for_age_band(rng: random.Random, band: str | None) -> date:
    """可选年龄段，便于 30-50 等 query 命中。"""
    # 基准 2026-07-20
    if band == "30-50":
        return random_date(rng, date(1976, 7, 20), date(1996, 7, 20))
    if band == "40-60":
        return random_date(rng, date(1966, 7, 20), date(1986, 7, 20))
    if band == "under30":
        return random_date(rng, date(1996, 7, 21), CSRQ_END)
    if band == "over50":
        return random_date(rng, CSRQ_START, date(1976, 7, 19))
    return random_date(rng, CSRQ_START, CSRQ_END)


def make_person(
    seq: int,
    rng: random.Random,
    *,
    hotspot: bool,
    query_pat: dict[str, Any] | None = None,
    age_band: str | None = None,
) -> dict[str, Any]:
    birth = birth_for_age_band(rng, age_band)
    city = rng.choice(CITIES)
    return {
        "id": f"P{seq:08d}",
        "idcardno": make_idcard(seq, birth),
        "xm": make_name(rng),
        "xb": rng.choice(["男", "女"]),
        "mz": rng.choice(ETHNICITIES),
        "csrq": birth.isoformat(),
        "_hotspot": hotspot,
        "_city": city,
        "_query_pat": query_pat,
    }


def make_residence(person: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    city = person.get("_city") or rng.choice(CITIES)
    return {
        "idcardno": person["idcardno"],
        "zz": f"{city}{rng.randint(1, 99)}路{rng.randint(1, 999)}号",
        "sjlysd": "北京",
        "ywrksj": fmt_dt(BASE_NOW, with_tz=True),
    }


def make_trip_and_order(
    person: dict[str, Any],
    rng: random.Random,
    *,
    ticket_seq: int,
    force_hot_city: bool = False,
    force_from: str | None = None,
    force_to: str | None = None,
    force_prefix: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    train_date = random_date(rng, date(2025, 1, 1), date(2026, 6, 25))
    if force_to:
        to_st = force_to
        from_st = force_from or rng.choice([c for c in CITIES if c != to_st])
    elif force_hot_city:
        to_st = rng.choice(HOT_CITIES)
        from_st = force_from or rng.choice([c for c in CITIES if c != to_st])
    else:
        from_st = force_from or rng.choice(CITIES)
        to_st = rng.choice([c for c in CITIES if c != from_st])
    hh, mm = rng.randint(0, 23), rng.randint(0, 59)
    sale = train_date - timedelta(days=rng.randint(1, 30))
    prefix = force_prefix or rng.choice(TRAIN_PREFIXES)
    ticket_no = make_ticket_no(ticket_seq)
    trip = {
        "ticket_no": ticket_no,
        "id_name": person["xm"],
        "id_kind_new": "身份证",
        "id_no": person["idcardno"],
        "train_date": train_date.isoformat(),
        "start_time": f"{hh:02d}:{mm:02d}",
        "board_train_code": f"{prefix}{rng.randint(1, 9999)}",
        "from_station_name": from_st,
        "to_station_name": to_st,
        "dt": train_date.strftime("%Y%m%d"),
    }
    order = {
        "ticket_no": ticket_no,
        "coach_no": str(rng.randint(1, 18)),
        "seat_no": str(rng.randint(1, 120)),
        "seat_type_code_new": rng.choice(SEAT_TYPES),
        "ticket_type_new": rng.choice(TICKET_TYPES),
        "office_no": f"OFF{rng.randint(1, 200):03d}",
        "window_no": str(rng.randint(1, 20)),
        "sale_time": f"{sale.isoformat()} 00:00:00",
        "ticket_price": str(rng.randint(50, 1200)),
        "sjlysd": rng.choice(CITIES),
        "ywrksj": fmt_dt(BASE_NOW),
    }
    # 旧规则索引：行程+售票合并
    sales = {
        "id_name": trip["id_name"],
        "id_kind_new": trip["id_kind_new"],
        "id_no": trip["id_no"],
        "train_date": trip["train_date"],
        "start_time": trip["start_time"],
        "board_train_code": trip["board_train_code"],
        "from_station_name": trip["from_station_name"],
        "to_station_name": trip["to_station_name"],
        "coach_no": order["coach_no"],
        "seat_no": order["seat_no"],
        "seat_type_code_new": order["seat_type_code_new"],
        "ticket_no": ticket_no,
        "ticket_type_new": order["ticket_type_new"],
        "office_no": order["office_no"],
        "window_no": order["window_no"],
        "sale_time": order["sale_time"],
        "ticket_price": order["ticket_price"],
        "sjlysd": order["sjlysd"],
        "ywrksj": order["ywrksj"],
        "dt": trip["dt"],
    }
    return trip, order, sales


def write_ticket_bundle(
    writers: dict[str, ShardWriter],
    person: dict[str, Any],
    rng: random.Random,
    ticket_seq: int,
    **kwargs: Any,
) -> int:
    trip, order, sales = make_trip_and_order(person, rng, ticket_seq=ticket_seq, **kwargs)
    writers["ticket_trip"].write(trip)
    writers["ticket_order"].write(order)
    writers["ticket_sales"].write(sales)
    return 1


def generate(cfg: dict[str, Any]) -> dict[str, Any]:
    n = int(cfg.get("rows_per_table") or 100000)
    n_person = n
    n_ticket = n
    n_tag = n
    shard_size = int(cfg.get("shard_size") or 100000)
    batch_size = int(cfg.get("batch_size") or 10000)
    hotspot_fraction = float(cfg.get("hotspot_fraction") or 0.0)
    query_hotspot_fraction = float(cfg.get("query_hotspot_fraction") or 0.0)
    seed = int(cfg.get("seed") or 42)
    out_root = Path(cfg.get("output_dir") or "./out")
    if not out_root.is_absolute():
        out_root = ROOT / out_root

    rng = random.Random(seed)
    n_query_hot = int(n_person * query_hotspot_fraction)
    print(
        f"[config] rows_per_table={n} base={list(BASE_TABLES)} "
        f"compat={list(COMPAT_TABLES)} hotspot={hotspot_fraction} "
        f"query_hotspot={query_hotspot_fraction}(~{n_query_hot}) out={out_root}"
    )

    all_tables = BASE_TABLES + COMPAT_TABLES
    writers = {name: ShardWriter(out_root / name, name, shard_size) for name in all_tables}

    tickets_left = n_ticket
    tags_left = n_tag
    seq = 0
    ticket_seq = 0
    query_hot_left = n_query_hot

    # 年龄段轮转，覆盖 30-50 / 40-60 等
    age_bands = ["30-50", "40-60", "under30", "over50", None]

    while seq < n_person:
        bsz = min(batch_size, n_person - seq)
        persons_left_after = n_person - seq - bsz

        if persons_left_after == 0:
            batch_tickets = tickets_left
            batch_tags = tags_left
        else:
            batch_tickets = tickets_left * bsz // (bsz + persons_left_after)
            batch_tags = tags_left * bsz // (bsz + persons_left_after)

        persons: list[dict[str, Any]] = []
        for i in range(bsz):
            seq += 1
            use_qh = query_hot_left > 0 and (
                persons_left_after == 0
                or rng.random() < (query_hot_left / max(1, n_person - seq + 1))
            )
            if use_qh:
                query_hot_left -= 1
                pat = QUERY_PATTERNS[seq % len(QUERY_PATTERNS)]
                band = age_bands[seq % len(age_bands)]
                persons.append(
                    make_person(seq, rng, hotspot=True, query_pat=pat, age_band=band)
                )
            else:
                hot = rng.random() < hotspot_fraction
                persons.append(make_person(seq, rng, hotspot=hot, age_band=None))

        # 住址表 + 主档冗余住址字段（兼容旧规则）
        for p in persons:
            res = make_residence(p, rng)
            writers["person_residence"].write(res)
            p["_zz"] = res["zz"]
            p["_sjlysd"] = res["sjlysd"]
            p["_ywrksj"] = res["ywrksj"]

        # 评测热点人：强制 1 张对应 OD 票 + 标签（占用本批配额）
        qh_persons = [p for p in persons if p.get("_query_pat")]
        reserved_t = min(len(qh_persons), batch_tickets)
        reserved_tag_slots = 0
        for p in qh_persons:
            reserved_tag_slots += max(1, len(p["_query_pat"].get("tags") or []) or 1)
        reserved_tag_slots = min(reserved_tag_slots, batch_tags)

        # 先写评测热点票
        written_t = 0
        for p in qh_persons:
            if written_t >= reserved_t:
                break
            pat = p["_query_pat"] or {}
            ticket_seq += 1
            write_ticket_bundle(
                writers,
                p,
                rng,
                ticket_seq,
                force_from=pat.get("from"),
                force_to=pat.get("to"),
                force_prefix=pat.get("train_prefix"),
            )
            written_t += 1

        remain_t = batch_tickets - written_t
        # 其余票分给本批（含普通热点）
        others = persons
        per_tickets = allocate_int(remain_t, len(others), rng)
        for i, p in enumerate(others):
            if p.get("_query_pat"):
                continue  # 已至少 1 张；额外票下面统一加
        # 重新：非 qh 配额已在 remain；qh 也可再分到额外票
        for i, p in enumerate(persons):
            if p["_hotspot"] and not p.get("_query_pat") and per_tickets[i] == 0:
                for j in range(len(persons)):
                    if not persons[j]["_hotspot"] and per_tickets[j] > 0:
                        per_tickets[j] -= 1
                        per_tickets[i] += 1
                        break

        for i, p in enumerate(persons):
            for k in range(per_tickets[i]):
                ticket_seq += 1
                write_ticket_bundle(
                    writers,
                    p,
                    rng,
                    ticket_seq,
                    force_hot_city=p["_hotspot"] and not p.get("_query_pat") and k == 0,
                )
                written_t += 1
        tickets_left -= written_t

        # 标签
        tag_rows = 0
        used: dict[str, set[str]] = {p["idcardno"]: set() for p in persons}

        def add_tag(p: dict[str, Any], tname: str) -> bool:
            nonlocal tag_rows
            if tag_rows >= batch_tags:
                return False
            s = used[p["idcardno"]]
            if tname in s:
                return False
            writers["tag_person"].write({"idcardno": p["idcardno"], "tag_name": tname})
            s.add(tname)
            tag_rows += 1
            return True

        for p in qh_persons:
            tags = list((p.get("_query_pat") or {}).get("tags") or [])
            if not tags:
                continue
            for t in tags:
                add_tag(p, t)

        for p in persons:
            if tag_rows >= batch_tags:
                break
            if p["_hotspot"] and not p.get("_query_pat"):
                add_tag(p, rng.choice(HOT_TAGS))

        guard = 0
        while tag_rows < batch_tags and guard < batch_tags * 5 + 10:
            guard += 1
            p = rng.choice(persons)
            candidates = [t for t in TAG_NAMES if t not in used[p["idcardno"]]]
            if not candidates:
                found = False
                for q in persons:
                    cand = [t for t in TAG_NAMES if t not in used[q["idcardno"]]]
                    if cand:
                        add_tag(q, rng.choice(cand))
                        found = True
                        break
                if not found:
                    break
                continue
            add_tag(p, rng.choice(candidates))

        tags_left -= tag_rows

        for p in persons:
            writers["resident_population"].write(
                {
                    "id": p["id"],
                    "idcardno": p["idcardno"],
                    "xm": p["xm"],
                    "xb": p["xb"],
                    "mz": p["mz"],
                    "csrq": p["csrq"],
                    "zz": p["_zz"],
                    "sjlysd": p["_sjlysd"],
                    "ywrksj": p["_ywrksj"],
                }
            )

        if seq % max(batch_size, 1) == 0 or seq == n_person:
            print(
                f"[progress] person={seq}/{n_person} "
                f"trip={writers['ticket_trip'].total} sales={writers['ticket_sales'].total} "
                f"tag={writers['tag_person'].total} qh_left={query_hot_left}"
            )

    for w in writers.values():
        w.close()

    counts_written = {name: writers[name].total for name in all_tables}
    base_ok = all(counts_written[name] == n for name in BASE_TABLES)
    compat_ok = counts_written["ticket_sales"] == counts_written["ticket_trip"] == n
    result = {
        "ok": base_ok and compat_ok,
        "rows_per_table_target": n,
        "counts_written": counts_written,
        "files": {name: [str(p) for p in writers[name].files] for name in all_tables},
        "output_dir": str(out_root),
        "relations": {
            "person_residence.idcardno": "resident_population.idcardno",
            "ticket_trip.id_no": "resident_population.idcardno",
            "ticket_order.ticket_no": "ticket_trip.ticket_no",
            "ticket_sales": "ticket_trip ⋈ ticket_order（规则兼容）",
            "tag_person.idcardno": "resident_population.idcardno",
        },
        "rule_compatible_indices": [
            "resident_population",
            "ticket_sales",
            "tag_person",
        ],
    }
    if not result["ok"]:
        result["error"] = "行数未对齐，请检查配额/标签种类"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="生成五表+ticket_sales 兼容视图")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--rows-per-table", type=int, default=None)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    if args.rows_per_table is not None:
        cfg["rows_per_table"] = args.rows_per_table
    if args.output_dir is not None:
        cfg["output_dir"] = args.output_dir

    t0 = datetime.now()
    generate(cfg)
    print(f"[done] elapsed={(datetime.now() - t0).total_seconds():.1f}s")


if __name__ == "__main__":
    main()
