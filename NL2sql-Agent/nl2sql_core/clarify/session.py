from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field


class ClarifyMessage(BaseModel):
    role: str  # assistant | user
    content: str
    ts: float = Field(default_factory=time.time)


class ClarifySession(BaseModel):
    id: str
    original_query: str
    messages: list[ClarifyMessage] = Field(default_factory=list)
    resolved_query: Optional[str] = None
    done: bool = False
    round_count: int = 0
    max_rounds: int = 3


_SESSIONS: dict[str, ClarifySession] = {}

CLARIFY_SYSTEM = """你在做 NL2SQL 需求澄清（brainstorm 风格）。
规则：
- 一次只问一个问题。
- 优先用选择题降低负担。
- 把模糊词具体化（最近、高、一批人等）。
- 当信息足够生成目标库查询时，输出 JSON：{"done": true, "resolved_query": "完整清晰的中文查询"}。
- 否则输出 JSON：{"done": false, "question": "下一问"}。
只输出 JSON。
"""

AUTO_RESOLVE_SYSTEM = """你在做 NL2SQL 静默澄清：用户关闭了多轮追问，请你自行理解并改写问句。
规则：
- 不要向用户提问；禁止输出 question。
- 在不臆造关键业务事实的前提下，把模糊表述尽量具体化（时间范围、索引/业务对象、过滤条件）。
- 信息不足时，按最合理的默认理解补全，并在 resolved_query 里写清楚你的理解。
- 只输出 JSON：{"resolved_query": "完整清晰的中文查询", "notes": "可选：你做的假设，一句话"}。
"""


async def auto_resolve_query(original_query: str, llm) -> ClarifySession:
    """非交互：单次改写 query，永不 need_clarify。"""
    sid = str(uuid.uuid4())
    session = ClarifySession(
        id=sid,
        original_query=original_query,
        max_rounds=0,
        round_count=0,
        done=True,
    )
    raw = await llm.chat(
        AUTO_RESOLVE_SYSTEM,
        f"用户原始问题：{original_query}\n请输出改写后的 resolved_query。",
    )
    data = _parse(raw)
    resolved = (data.get("resolved_query") or "").strip() or original_query
    session.resolved_query = resolved
    notes = (data.get("notes") or "").strip()
    msg = f"已自动理解查询：{resolved}"
    if notes:
        msg += f"（假设：{notes}）"
    session.messages.append(ClarifyMessage(role="assistant", content=msg))
    _SESSIONS[sid] = session
    return session


async def start_clarify(original_query: str, llm, *, max_rounds: int = 3) -> ClarifySession:
    sid = str(uuid.uuid4())
    session = ClarifySession(id=sid, original_query=original_query, max_rounds=max_rounds)
    raw = await llm.chat(
        CLARIFY_SYSTEM,
        f"用户原始问题：{original_query}\n请开始澄清。信息已足够则直接 done。",
    )
    data = _parse(raw)
    if data.get("done"):
        session.done = True
        session.resolved_query = data.get("resolved_query") or original_query
        session.messages.append(
            ClarifyMessage(role="assistant", content=f"已确认查询：{session.resolved_query}")
        )
    else:
        session.round_count = 1
        q = data.get("question") or "请补充更具体的查询条件？"
        session.messages.append(ClarifyMessage(role="assistant", content=q))
    _SESSIONS[sid] = session
    return session


async def reply_clarify(session_id: str, user_text: str, llm) -> ClarifySession:
    session = _SESSIONS.get(session_id)
    if not session:
        raise KeyError("会话不存在")
    if session.done:
        return session
    session.messages.append(ClarifyMessage(role="user", content=user_text))
    history = "\n".join(f"{m.role}: {m.content}" for m in session.messages)
    # 达到轮数上限则强制收束
    force = session.round_count >= session.max_rounds
    hint = (
        "已达澄清轮数上限，必须输出 done=true 与 resolved_query（综合已有信息尽量完整）。"
        if force
        else "请继续；信息足够则 done=true。"
    )
    raw = await llm.chat(
        CLARIFY_SYSTEM,
        f"原始问题：{session.original_query}\n对话：\n{history}\n{hint}",
    )
    data = _parse(raw)
    if force:
        data["done"] = True
        data.setdefault("resolved_query", session.original_query)
    if data.get("done"):
        session.done = True
        session.resolved_query = data.get("resolved_query") or session.original_query
        session.messages.append(
            ClarifyMessage(role="assistant", content=f"已确认查询：{session.resolved_query}")
        )
    else:
        session.round_count += 1
        q = data.get("question") or "还有其他约束吗？"
        session.messages.append(ClarifyMessage(role="assistant", content=q))
        if session.round_count >= session.max_rounds:
            # 下一轮用户回复后强制 done；若本轮仍未 done，再追问最后一次
            pass
    _SESSIONS[session_id] = session
    return session


def get_session(session_id: str) -> Optional[ClarifySession]:
    return _SESSIONS.get(session_id)


def _parse(text: str) -> dict[str, Any]:
    import json
    import re

    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group(0))
        return {"done": False, "question": text}
