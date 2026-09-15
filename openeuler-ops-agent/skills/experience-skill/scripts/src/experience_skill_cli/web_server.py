"""经验管理 Web 服务"""

import os
import re
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from experience_skill_cli.common.exprience import SKILL_ROOT
from experience_skill_cli.console import launch, link, rocket, warn
from experience_skill_cli.manager.experience_manager import ExperienceManager
from experience_skill_cli.manager.keyword_manager import KeyWordManager
from experience_skill_cli.schema.enum import ExperienceType
from experience_skill_cli.schema.exprience import Experience
from experience_skill_cli.service.experience_service import ExperienceService, HybridSearchResult

TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="经验管理", docs_url=None, redoc_url=None)


# ------------------------------
# 静态页面
# ------------------------------
@app.get("/", response_class=HTMLResponse, response_model=None)
async def index() -> HTMLResponse | str:
    """返回主页面 index.html。"""
    index_path = TEMPLATES_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return HTMLResponse("<h1>index.html not found</h1>", status_code=404)


# ------------------------------
# API：获取所有关键词
# ------------------------------
@app.get("/api/keywords")
async def list_keywords(
    exp_type: Annotated[str | None, Query(description="类型过滤：SKILL / WIKI")] = None,
) -> JSONResponse:
    """获取所有关键词，可按类型过滤。"""
    experience_type = ExperienceType[exp_type.upper()] if exp_type else None
    keywords = KeyWordManager.get_all_keywords(experience_type)
    return JSONResponse({"keywords": keywords})


# ------------------------------
# API：列出经验
# ------------------------------
@app.get("/api/experiences")
async def list_experiences(
    exp_type: Annotated[str | None, Query(description="类型过滤：SKILL / WIKI")] = None,
    name: Annotated[str | None, Query(description="名称模糊匹配")] = None,
    is_hot: Annotated[bool | None, Query(description="是否热门")] = None,
    kw: Annotated[list[str] | None, Query(description="关键词过滤（多选）")] = None,
    page: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页数量")] = 20,
) -> JSONResponse:
    """列出经验列表，支持多条件筛选和分页。"""
    experience_type = ExperienceType[exp_type.upper()] if exp_type else None

    # 关键词过滤：先查出命中的经验 ID，再传给列表查询
    keyword_ids = KeyWordManager.get_experience_ids_by_keywords(kw) if kw else None

    total, exps = ExperienceManager.list_experiences(
        experience_type=experience_type,
        keywords=None,
        name=name,
        is_hot=is_hot,
        page=page,
        page_size=page_size,
        experience_ids=keyword_ids,
    )
    # 补回 keywords 字段
    for exp in exps:
        exp.keywords = KeyWordManager.get_keywords_by_experience_id(exp.id)
    return JSONResponse(
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_exp_to_dict(e) for e in exps],
        },
    )


# ------------------------------
# API：热门 Top 20
# ------------------------------
@app.get("/api/experiences/hot")
async def list_hot_experiences(
    exp_type: Annotated[str | None, Query(description="类型过滤：SKILL / WIKI")] = None,
) -> JSONResponse:
    """获取热门经验 Top 20。"""
    experience_type = ExperienceType[exp_type.upper()] if exp_type else None
    total, exps = ExperienceService.list_experiences(
        experience_type=experience_type,
        name=None,
        is_hot=True,
        page=1,
        page_size=20,
    )
    return JSONResponse(
        {
            "total": total,
            "items": [_exp_to_dict(e) for e in exps],
        },
    )


# ------------------------------
# API：搜索经验（FTS）
# ------------------------------
@app.get("/api/experiences/search")
async def search_experiences(
    query: Annotated[str, Query(min_length=1, description="搜索关键词")],
    exp_type: Annotated[str | None, Query(description="类型：SKILL / WIKI，不传则搜索全部")] = None,
    top_k: Annotated[int, Query(ge=1, le=100, description="返回条数")] = 20,
    is_hot: Annotated[bool | None, Query(description="是否热门")] = None,
    search_mode: Annotated[
        str | None,
        Query(description="检索模式：hybrid（默认）/ metadata / content"),
    ] = None,
) -> JSONResponse:
    """搜索经验，支持三种检索模式和跨类型搜索。

    - exp_type 不传时同时搜索 SKILL + WIKI，按得分合并排序
    - hybrid（默认）：元数据 + 正文内容混合检索
    - metadata：仅 FTS5 元数据检索
    - content：仅正文内容 grep 检索
    """
    mode = (search_mode or "hybrid").strip().lower()
    types: list[ExperienceType] = (
        [ExperienceType.SKILL, ExperienceType.WIKI]
        if exp_type is None
        else [ExperienceType[exp_type.upper()]]
    )

    if mode == "metadata":
        all_exps: list[Experience] = []
        for experience_type in types:
            exps = ExperienceService.search_experiences(
                query=query,
                exp_type=experience_type,
                top_k=top_k,
                is_hot=is_hot,
            )
            all_exps.extend(exps)
        all_exps = all_exps[:top_k]
        return JSONResponse(
            {
                "items": [_exp_to_dict(e) for e in all_exps],
                "mode": "metadata",
            },
        )

    # hybrid / content 模式
    all_hybrid: list[HybridSearchResult] = []
    for experience_type in types:
        if mode == "content":
            results = ExperienceService.search_content_only(
                query=query,
                exp_type=experience_type,
                top_k=top_k,
                is_hot=is_hot,
            )
        else:
            results = ExperienceService.search_with_content(
                query=query,
                exp_type=experience_type,
                top_k=top_k,
                is_hot=is_hot,
            )
        all_hybrid.extend(results)

    # 跨类型时按得分排序，截断至 top_k
    if len(types) > 1:
        all_hybrid.sort(key=lambda r: r.final_score, reverse=True)
    all_hybrid = all_hybrid[:top_k]

    return JSONResponse(
        {
            "items": [_hybrid_result_to_dict(r) for r in all_hybrid],
            "mode": mode,
        },
    )


# ------------------------------
# API：获取单条经验详情（含文件内容）
# ------------------------------


def _strip_yaml_header(md_content: str) -> str:
    """去除 Markdown 文件开头的 YAML front matter（--- ... ---）。"""
    return re.sub(
        r"^---\s*\n.*?\n---\s*\n",
        "",
        md_content,
        count=1,
        flags=re.DOTALL,
    ).lstrip("\n")


@app.get("/api/experiences/{experience_id}")
async def get_experience(experience_id: str) -> JSONResponse:
    """获取单条经验详情，含源文件内容。"""
    exps = ExperienceManager.query_experience_by_ids([experience_id])
    if not exps:
        return JSONResponse({"error": "Experience not found"}, status_code=404)

    exp = exps[0]
    exp.keywords = KeyWordManager.get_keywords_by_experience_id(exp.id)

    # 读取源文件内容（skill_hub / wiki_hub 均位于 SKILL_ROOT 下）
    content = ""
    try:
        if exp.type == ExperienceType.SKILL:
            skill_md = SKILL_ROOT / exp.source / "skill_def.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")
        elif exp.type == ExperienceType.WIKI:
            wiki_md = SKILL_ROOT / exp.source
            if wiki_md.exists():
                content = wiki_md.read_text(encoding="utf-8")
    except Exception:
        content = "无法读取文件内容"

    # 剥离 YAML header，正文区域不展示冗余元信息
    content = _strip_yaml_header(content)

    result = _exp_to_dict(exp)
    result["content"] = content
    return JSONResponse(result)


# ------------------------------
# 辅助函数
# ------------------------------
def _exp_to_dict(exp: Experience) -> dict[str, object]:
    """将 Experience 对象转为字典。"""
    return {
        "id": exp.id,
        "type": exp.type.value,
        "name": exp.name,
        "description": exp.description,
        "keywords": exp.keywords,
        "source": exp.source,
        "is_hot": exp.is_hot,
        "status": exp.status.value,
        "created_at": exp.created_at,
        "updated_at": exp.updated_at,
    }


def _hybrid_result_to_dict(sr: HybridSearchResult) -> dict[str, object]:
    """将 HybridSearchResult 转为前端可用的字典。"""
    result = _exp_to_dict(sr.experience)
    result.update(
        {
            "match_type": sr.match_type,
        },
    )
    return result


def start_web_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    *,
    open_browser: bool = True,
) -> None:
    """启动 Web 服务并可选自动打开浏览器。"""
    url = f"http://{host}:{port}"

    # 在后台线程启动 uvicorn
    server_thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": host, "port": port, "log_level": "warning"},
        daemon=True,
    )
    server_thread.start()

    # 等待服务就绪
    max_retries = 30
    for _ in range(max_retries):
        try:
            with urllib.request.urlopen(  # noqa: S310
                f"{url}/api/keywords",
                timeout=1,
            ):
                break
        except Exception:
            time.sleep(0.1)
    else:
        warn(f"服务启动超时，请手动访问: {url}")
        # 等待 server 线程结束（通常不会到这里）
        server_thread.join()
        return

    # 服务就绪后再打开浏览器
    has_display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    is_macos = os.uname().sysname == "Darwin"

    if open_browser and (has_display or is_macos):
        try:
            webbrowser.open(url)
            launch(f"浏览器已打开: {url}")
        except Exception:
            warn(f"无法自动打开浏览器，请手动访问: {url}")
    else:
        link(f"请访问: {url}")

    rocket(f"Web 服务启动于 {host}:{port}，按 Ctrl+C 停止")

    # 阻塞主线程，直到 uvicorn 结束
    try:
        while server_thread.is_alive():
            server_thread.join(timeout=0.5)
    except KeyboardInterrupt:
        pass
