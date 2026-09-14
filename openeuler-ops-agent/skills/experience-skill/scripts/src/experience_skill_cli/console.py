"""CLI 控制台输出工具 —— 统一所有 print 调用，提供语义化、美观的输出。"""

from __future__ import annotations

import sys
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from experience_skill_cli.schema.exprience import Experience
    from experience_skill_cli.service.experience_service import HybridSearchResult

# ---------------------------------------------------------------------------
# Enum 值 -> 可读文本的映射
# ---------------------------------------------------------------------------

# 延迟导入以避免循环依赖，模块加载时通过 _build_enum_display_map() 填充
_ENUM_DISPLAY_MAP: dict[Enum, str] = {}


def _build_enum_display_map() -> None:
    """构建 Enum 成员到可读文本的映射。"""
    if _ENUM_DISPLAY_MAP:
        return  # 已初始化

    from experience_skill_cli.schema.enum import (  # noqa: PLC0415
        ExperienceStatus,
        ExperienceType,
    )

    _ENUM_DISPLAY_MAP.update(
        {
            ExperienceType.SKILL: "SKILL",
            ExperienceType.WIKI: "WIKI",
            ExperienceStatus.EXISTED: "存在",
            ExperienceStatus.DELETED: "已删除",
        },
    )


def _format_value(value: Any) -> str:
    """将字段值格式化为可读文本，特别处理 Enum 类型。"""
    if isinstance(value, Enum):
        _build_enum_display_map()
        return _ENUM_DISPLAY_MAP.get(value, value.value)
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value) if value is not None else ""


# ---------------------------------------------------------------------------
# 内部基础函数
# ---------------------------------------------------------------------------


def echo(*args: Any, **kwargs: Any) -> None:
    """通用输出，等价于 print。"""
    print(*args, **kwargs)  # noqa: T201


# ---------------------------------------------------------------------------
# 语义化输出
# ---------------------------------------------------------------------------


def success(msg: str) -> None:
    """✅ 成功消息。"""
    echo(f"✅ {msg}")


def info(msg: str) -> None:
    """📋 信息消息。"""
    echo(f"📋 {msg}")


def warn(msg: str) -> None:
    """⚠️  警告消息（输出到 stderr）。"""
    echo(f"⚠️  {msg}", file=sys.stderr)


def error(msg: str) -> None:
    """❌ 错误消息（输出到 stderr）。"""
    echo(f"❌ {msg}", file=sys.stderr)


def deleted(msg: str) -> None:
    """🗑️  删除确认消息。"""
    echo(f"🗑️  {msg}")


def search_result(msg: str) -> None:
    """🔍 搜索结果标题。"""
    echo(f"🔍 {msg}")


def launch(msg: str) -> None:
    """🌐 浏览器启动消息。"""
    echo(f"🌐 {msg}")


def link(msg: str) -> None:
    """🔗 链接提示消息。"""
    echo(f"🔗 {msg}")


def rocket(msg: str) -> None:
    """🚀 服务启动横幅。"""
    echo(f"🚀 {msg}")


def blank() -> None:
    """输出一个空行。"""
    echo()


def section(title: str) -> None:
    """输出章节标题。"""
    echo(f"===== {title} =====")


# ---------------------------------------------------------------------------
# 经验打印
# ---------------------------------------------------------------------------

_EXPERIENCE_FIELDS = [
    ("ID", "id"),
    ("类型", "type"),
    ("名称", "name"),
    ("状态", "status"),
    ("描述", "description"),
    ("关键词", "keywords"),
    ("来源", "source"),
    ("是否热门", "is_hot"),
    ("创建时间", "created_at"),
    ("更新时间", "updated_at"),
]


def print_experience(exp: Experience, index: int | None = None) -> None:
    """格式化打印一条经验的所有字段。"""
    if index is not None:
        section(f"第 {index} 条经验")
    else:
        section("经验详情")
    for label, attr in _EXPERIENCE_FIELDS:
        echo(f"{label:<12}: {_format_value(getattr(exp, attr, ''))}")


def print_experience_list(exps: list[Experience], total: int | None = None) -> None:
    """批量打印经验列表。"""
    if total is not None:
        info(f"总计：{total} 条")
    elif exps:
        info(f"共 {len(exps)} 条")
    for idx, exp in enumerate(exps, 1):
        if idx > 1:
            blank()
        print_experience(exp, idx)


# ---------------------------------------------------------------------------
# 混合检索结果打印
# ---------------------------------------------------------------------------

_SNIPPET_MAX_LEN = 100
_DESCRIPTION_MAX_LEN = 200

_MATCH_TYPE_LABELS = {
    "both": "元数据 + 正文",
    "metadata": "仅元数据",
    "content": "仅正文",
}


def print_hybrid_search_results(
    results: list[HybridSearchResult],
) -> None:
    """打印混合检索结果列表，包含匹配类型、得分和正文摘要。"""
    # 延迟导入避免循环依赖

    if not results:
        info("无匹配结果")
        return

    for idx, sr in enumerate(results, 1):
        if idx > 1:
            blank()

        exp = sr.experience
        section(f"第 {idx} 条结果")

        # 基本信息
        echo(f"{'ID':<12}: {exp.id}")
        echo(f"{'名称':<12}: {exp.name}")
        echo(f"{'类型':<12}: {_format_value(exp.type)}")

        # 匹配信息
        match_label = _MATCH_TYPE_LABELS.get(sr.match_type, sr.match_type)
        echo(f"{'匹配方式':<12}: {match_label}")

        # 正文匹配摘要
        if sr.snippets:
            echo(f"{'正文命中':<12}: {sr.content_hit_count} 处")
            echo(f"{'正文摘要':<12}:")
            for snip in sr.snippets[:3]:  # 最多展示 3 条片段
                # 截断过长行
                text = snip.content
                if len(text) > _SNIPPET_MAX_LEN:
                    text = text[: _SNIPPET_MAX_LEN - 3] + "..."
                echo(f"{'':<12}  L{snip.line_num}: {text}")

        # 描述
        if exp.description:
            desc = exp.description
            if len(desc) > _DESCRIPTION_MAX_LEN:
                desc = desc[: _DESCRIPTION_MAX_LEN - 3] + "..."
            echo(f"{'描述':<12}: {desc}")

        # 来源
        echo(f"{'来源':<12}: {exp.source}")
        echo(f"{'是否热门':<12}: {'是' if exp.is_hot else '否'}")
