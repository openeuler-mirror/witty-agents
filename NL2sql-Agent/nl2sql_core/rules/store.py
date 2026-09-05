from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any, Optional

import yaml

from nl2sql_core.config import CONFIGS, DATA_DIR, ensure_data_dir, load_datasources, load_rag_settings
from nl2sql_core.rag_client import RagClient
from nl2sql_core.rules.schema import Rule


def normalize_dialect(engine_type: str | None) -> str:
    t = (engine_type or "").lower().strip()
    if t in ("elasticsearch", "es"):
        return "elasticsearch"
    if t in ("opengauss", "postgres", "postgresql"):
        return "opengauss"
    if t == "hbase":
        return "hbase"
    return t or "shared"


class RuleStore:
    """本地 JSON = bootstrap 缓存；运行时检索以该数据源绑定的 rag-core KB 为准。"""

    def __init__(self, database_id: str = "local-es"):
        ensure_data_dir()
        self.database_id = database_id
        self.path = DATA_DIR / "rules" / f"{database_id}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rag = RagClient()

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, rules: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_rules(self, rule_type: Optional[str] = None) -> list[dict[str, Any]]:
        rules = self._load()
        if rule_type:
            rules = [r for r in rules if r.get("rule_type") == rule_type]
        return rules

    def upsert(self, rule: Rule | dict[str, Any]) -> dict[str, Any]:
        if isinstance(rule, Rule):
            content = rule.to_content()
        else:
            content = dict(rule)
        content.setdefault("database_id", self.database_id)
        content.setdefault("id", str(uuid.uuid4()))
        rules = self._load()
        replaced = False
        for i, r in enumerate(rules):
            if r.get("id") == content["id"]:
                rules[i] = content
                replaced = True
                break
        if not replaced:
            rules.append(content)
        self._save(rules)
        return content

    def bulk_upsert(self, rules: list[Rule | dict[str, Any]]) -> int:
        n = 0
        for r in rules:
            self.upsert(r)
            n += 1
        return n

    def search_local(
        self,
        query: str,
        *,
        top_k: int = 20,
        dialects: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """仅用于 bootstrap 调试或 rag 不可用时的显式降级。"""
        allowed = set(dialects or [])
        q = (query or "").strip().lower()
        scored: list[tuple[int, dict[str, Any]]] = []
        tokens = [t for t in re.split(r"[\s,，、]+", q) if t]
        if q and q not in tokens:
            tokens.append(q)
        if re.search(r"[\u4e00-\u9fff]", q):
            for i in range(len(q) - 1):
                bi = q[i : i + 2]
                if bi.strip() and bi not in tokens:
                    tokens.append(bi)
        for r in self._load():
            if allowed:
                d = str(r.get("dialect") or "shared")
                if d not in allowed and d != "shared":
                    continue
            blob = json.dumps(r, ensure_ascii=False).lower()
            score = 0
            for token in tokens:
                if token and token in blob:
                    score += 2 if len(token) >= 2 else 1
            if not q:
                score = 1
            if score > 0:
                scored.append((score, r))
        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored[:top_k]]

    def resolve_kb_id(self) -> str:
        """数据源 rules_kb_id > runtime 映射 > 全局 default_kb_id。"""
        ds = load_datasources().get(self.database_id) or {}
        kb = str(ds.get("rules_kb_id") or "").strip()
        if kb:
            return kb
        runtime_path = DATA_DIR / "runtime_settings.json"
        if runtime_path.exists():
            try:
                runtime = json.loads(runtime_path.read_text(encoding="utf-8")) or {}
                mapped = (runtime.get("rules_kb_by_datasource") or {}).get(self.database_id)
                if mapped:
                    return str(mapped).strip()
            except Exception:
                pass
        rag_s = load_rag_settings()
        return str(rag_s.default_kb_id or "").strip()

    def resolve_kb_name(self) -> str:
        ds = load_datasources().get(self.database_id) or {}
        return str(ds.get("rules_kb_name") or f"nl2sql-rules-{self.database_id}")

    async def search(
        self,
        query: str,
        *,
        dialect: str | None = None,
        kb_id: str | None = None,
        rule_type: Optional[str] = None,
        top_k: int = 30,
        allow_local_fallback: bool = False,
    ) -> list[dict[str, Any]]:
        """从当前数据源绑定的 rag-core KB 召回；固定注入 scope=dialect。"""
        rag_s = load_rag_settings()
        self.rag = RagClient(rag_s)
        resolved_kb = (kb_id or self.resolve_kb_id()).strip()
        if not resolved_kb:
            raise RuntimeError(
                f"未配置数据源 {self.database_id} 的 rules_kb_id：请先运行 scripts/sync_rules_to_rag.py"
            )

        eng = normalize_dialect(dialect) if dialect else normalize_dialect(
            (load_datasources().get(self.database_id) or {}).get("type")
        )
        dialects = [eng, "shared"] if eng and eng != "shared" else ["shared"]

        merged: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _add(items: list[dict[str, Any]]) -> None:
            for item in items:
                if rule_type and item.get("rule_type") != rule_type:
                    continue
                d = str(item.get("dialect") or "shared")
                if d not in dialects and d != "shared":
                    continue
                key = item.get("id") or json.dumps(item, ensure_ascii=False, sort_keys=True)
                if key in seen:
                    continue
                seen.add(str(key))
                merged.append(item)

        errors: list[str] = []

        # 1) 固定召回当前引擎的方言硬约束（不依赖问句语义）
        if not rule_type or rule_type == "experience":
            try:
                raw = await self.rag.search_rules(
                    resolved_kb,
                    f"dialect={eng} SQL dialect constraints LIMIT JOIN DISTINCT subquery",
                    database_id=self.database_id,
                    rule_type="experience",
                    scope="dialect",
                    dialects=dialects,
                    top_k=20,
                )
                _add(self._extract(raw))
            except Exception as e:
                errors.append(f"dialect: {e}")

        # 2) 按用户问句语义召回；query 显式带上当前方言，便于命中引擎相关规则
        for q in self._retrieval_queries(query, dialect=eng):
            try:
                raw = await self.rag.search_rules(
                    resolved_kb,
                    q,
                    database_id=self.database_id,
                    rule_type=rule_type,
                    dialects=dialects,
                    top_k=top_k,
                )
                _add(self._extract(raw))
            except Exception as e:
                errors.append(f"{q}: {e}")

        # 3) 分路补召：domain / schema（问句 + 方言标签），避免只撞到无关 mapping
        if not rule_type:
            for scope in ("domain", "schema"):
                for q in self._retrieval_queries(query, dialect=eng):
                    try:
                        raw = await self.rag.search_rules(
                            resolved_kb,
                            q,
                            database_id=self.database_id,
                            scope=scope,
                            dialects=dialects,
                            top_k=max(15, top_k // 2),
                        )
                        _add(self._extract(raw))
                    except Exception as e:
                        errors.append(f"{scope}:{q}: {e}")

        if merged:
            # 方言规则置顶，便于 LLM 先看到引擎约束
            dialect_rules = [r for r in merged if r.get("scope") == "dialect"]
            other = [r for r in merged if r.get("scope") != "dialect"]
            ordered = dialect_rules + other
            return ordered[: max(top_k, len(dialect_rules))]

        if allow_local_fallback:
            local = self.search_local(query, top_k=top_k, dialects=dialects)
            if rule_type:
                local = [r for r in local if r.get("rule_type") == rule_type]
            # 本地也固定带上 dialect scope
            local_dial = [
                r
                for r in self._load()
                if r.get("scope") == "dialect"
                and str(r.get("dialect") or "shared") in dialects
            ]
            for r in local_dial:
                if r not in local:
                    local.insert(0, r)
            if local:
                return local[:top_k]

        detail = "; ".join(errors[:3]) if errors else "召回结果为空"
        raise RuntimeError(
            f"rag-core 规则召回失败或为空（kb={resolved_kb}, dialect={eng}）: {detail}"
        )

    @staticmethod
    def _retrieval_queries(query: str, *, dialect: str | None = None) -> list[str]:
        """构造 rag 语义检索句：原问句 + 显式方言标签（过滤仍靠 logical dialect）。"""
        q = (query or "").strip()
        eng = (normalize_dialect(dialect) or "").strip()
        out: list[str] = []
        if q:
            out.append(q)
            if eng:
                out.append(f"[dialect={eng}] {q}")
                out.append(f"目标引擎/方言 {eng}；用户问题：{q}")
        elif eng:
            out.append(f"dialect={eng} rules")
        else:
            out.append("")
        # 去重保序
        seen: set[str] = set()
        uniq: list[str] = []
        for item in out:
            if item in seen:
                continue
            seen.add(item)
            uniq.append(item)
        return uniq

    async def sync_to_rag(
        self,
        *,
        kb_name: str | None = None,
        concurrency: int = 6,
        persist_kb: bool = True,
        recreate_kb: bool = True,
    ) -> dict[str, Any]:
        rag_s = load_rag_settings()
        self.rag = RagClient(rag_s)
        name = kb_name or self.resolve_kb_name()
        try:
            if recreate_kb:
                kb_id = await self.rag.create_json_kb(
                    name,
                    description=f"NL2SQL 规则库 database_id={self.database_id}",
                )
            else:
                kb_id = self.resolve_kb_id() or await self.rag.ensure_json_kb(
                    name,
                    description=f"NL2SQL 规则库 database_id={self.database_id}",
                )
        except Exception as e:
            return {"ok": False, "error": f"无法连接/创建 KB: {e}"}
        if not kb_id:
            return {"ok": False, "error": "未拿到 kb_id"}

        rules = self._load()
        sem = asyncio.Semaphore(max(1, concurrency))
        ok = 0
        errors: list[str] = []

        async def one(r: dict[str, Any]) -> None:
            nonlocal ok
            rule_name = str(r.get("id") or r.get("description") or "rule")[:120]
            async with sem:
                try:
                    await self.rag.upsert_rule(kb_id, name=rule_name, content=r, immediate=True)
                    ok += 1
                except Exception as e:
                    errors.append(f"{rule_name}: {e}")

        await asyncio.gather(*(one(r) for r in rules))
        if persist_kb:
            self._persist_kb_id(kb_id, rag_s.base_url, rag_s.access_key, self.database_id)
        return {
            "ok": not errors,
            "kb_id": kb_id,
            "kb_name": name,
            "database_id": self.database_id,
            "synced": ok,
            "total": len(rules),
            "errors": errors[:8],
        }

    @staticmethod
    def _persist_kb_id(kb_id: str, base_url: str, access_key: str, database_id: str) -> None:
        ensure_data_dir()
        # 全局 rag 连接仍写 yaml；default_kb_id 仅作无数据源 kb 时的回退
        yaml_path = CONFIGS / "rag_core.yaml"
        yaml_path.write_text(
            "\n".join(
                [
                    f'base_url: "{base_url}"',
                    f'access_key: "{access_key}"',
                    f'default_kb_id: "{kb_id}"',
                    "timeout_sec: 60",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        # 回写 datasources.yaml 中该源的 rules_kb_id
        ds_path = CONFIGS / "datasources.yaml"
        raw: dict[str, Any] = {}
        if ds_path.exists():
            raw = yaml.safe_load(ds_path.read_text(encoding="utf-8")) or {}
        datasources = raw.setdefault("datasources", {})
        entry = datasources.setdefault(database_id, {"id": database_id})
        if isinstance(entry, dict):
            entry["rules_kb_id"] = kb_id
            entry.setdefault("rules_kb_name", f"nl2sql-rules-{database_id}")
        ds_path.write_text(
            yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        runtime_path = DATA_DIR / "runtime_settings.json"
        runtime: dict[str, Any] = {}
        if runtime_path.exists():
            try:
                runtime = json.loads(runtime_path.read_text(encoding="utf-8")) or {}
            except Exception:
                runtime = {}
        runtime["rag_base_url"] = base_url
        runtime["rag_access_key"] = access_key
        runtime["rag_kb_id"] = kb_id
        kb_map = runtime.setdefault("rules_kb_by_datasource", {})
        if isinstance(kb_map, dict):
            kb_map[database_id] = kb_id
        runtime_path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _extract(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, dict):
            return []
        result = raw.get("result") or raw
        for key in ("jsons", "data", "items"):
            if isinstance(result, dict) and isinstance(result.get(key), list):
                out = []
                for item in result[key]:
                    content = item.get("content") if isinstance(item, dict) else None
                    if isinstance(content, dict):
                        out.append(content)
                    elif isinstance(item, dict):
                        out.append(item)
                return out
        return []
