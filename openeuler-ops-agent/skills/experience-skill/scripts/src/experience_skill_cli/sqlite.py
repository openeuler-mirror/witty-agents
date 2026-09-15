"""SQLite 数据库单例管理及 tokenizer 扩展加载。"""

import asyncio
import logging
import sqlite3
from collections.abc import Sequence
from multiprocessing import Lock as ProcessLock
from multiprocessing.synchronize import Lock as ProcessLockType
from pathlib import Path
from typing import Any, Self

from experience_skill_cli.common.exprience import SKILL_ROOT

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====================== 路径常量 ======================
SCRIPT_DIR = Path(__file__).resolve().parent
TOKENIZER_DIR = SCRIPT_DIR / "tokenizer"
LIBSIMPLE_PATH = TOKENIZER_DIR / "libsimple"


DATA_DIR = SKILL_ROOT / "data"


# ====================== 表结构 ======================
table_ddl_list = {
    "keyword_table": """
        CREATE TABLE IF NOT EXISTS keyword_table (
            id TEXT PRIMARY KEY,
            experience_id TEXT NOT NULL,
            name TEXT NOT NULL
        )
    """,
    "experience_table": """
        CREATE TABLE IF NOT EXISTS experience_table (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT,
            description TEXT,
            "references" TEXT DEFAULT '',
            status TEXT NOT NULL,
            is_hot BOOLEAN NOT NULL DEFAULT 0,
            source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "experience_fts": """
        CREATE VIRTUAL TABLE IF NOT EXISTS experience_fts USING fts5(
            description,
            content=experience_table,
            content_rowid=rowid,
            tokenize='simple'
        )
    """,
    "trg1": """
        CREATE TRIGGER IF NOT EXISTS fts_insert
        AFTER INSERT ON experience_table
        BEGIN
            INSERT INTO experience_fts(rowid, description) VALUES (new.rowid, new.description);
        END
    """,
    "trg2": """
        CREATE TRIGGER IF NOT EXISTS fts_update
        AFTER UPDATE ON experience_table
        BEGIN
            UPDATE experience_fts SET description=new.description WHERE rowid=new.rowid;
        END
    """,
    "trg3": """
        CREATE TRIGGER IF NOT EXISTS fts_delete
        AFTER DELETE ON experience_table
        BEGIN
            DELETE FROM experience_fts WHERE rowid=old.rowid;
        END
    """,
}


def _check_tokenizer() -> str:
    """
    检查 libsimple 扩展是否已就绪，返回扩展路径（不带后缀）。

    如果不存在，抛出 RuntimeError 提示用户手动编译。
    """
    ext_candidates = [
        str(LIBSIMPLE_PATH),
        str(LIBSIMPLE_PATH) + ".so",
        str(LIBSIMPLE_PATH) + ".dylib",
        str(LIBSIMPLE_PATH) + ".dll",
    ]
    ext_exists = any(Path(p).exists() for p in ext_candidates)

    if not ext_exists:
        build_script = TOKENIZER_DIR / "build.sh"
        msg = (
            f"[Tokenizer] 扩展未找到: {LIBSIMPLE_PATH}\n"
            f"            请先编译 simple 分词器扩展:\n"
            f"            bash {build_script}"
        )
        raise RuntimeError(msg)

    return str(LIBSIMPLE_PATH)


class AsyncSQLiteSingleton:
    """SQLite 异步安全单例管理器。"""

    _instance: "AsyncSQLiteSingleton | None" = None
    _process_lock: ProcessLockType = ProcessLock()

    db_path: str
    _async_lock: asyncio.Lock
    _conn: sqlite3.Connection | None
    _init: bool
    _ext_path: str | None

    def __new__(cls) -> Self:
        """创建或返回单例实例。"""
        if cls._instance is None:
            with cls._process_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化数据库连接与 tokenizer 扩展。"""
        if hasattr(self, "_init"):
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = str(DATA_DIR / "experience.db")
        self._async_lock = asyncio.Lock()
        self._conn = None
        self._init = True
        self._ext_path = None
        self._connect()

    def run(self, sql: str, params: Sequence[Any] = ()) -> bool:
        """执行写操作 SQL。"""
        self._connect()
        assert self._conn is not None
        try:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            self._conn.commit()
        except Exception:
            logger.exception("SQL execute error: sql=%s, params=%s", sql, params)
            self._conn.rollback()
            return False
        else:
            return True

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        """执行查询操作 SQL，返回字典列表。"""
        self._connect()
        assert self._conn is not None
        try:
            self._conn.row_factory = sqlite3.Row
            cur = self._conn.cursor()
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            logger.exception("SQL query error: sql=%s, params=%s", sql, params)
            return []

    def init(self) -> None:
        """初始化数据库表结构。"""
        for sql in table_ddl_list.values():
            self.run(sql)
        # 兼容旧表：动态添加列（如果尚不存在）
        self._ensure_column("experience_table", "name", "TEXT")
        self._ensure_column("experience_table", "references", "TEXT")

    def clear_database(self) -> None:
        """清空数据库文件。"""
        if self._conn:
            self._conn.close()
            self._conn = None
        for suffix in ["", "-wal", "-shm"]:
            path = Path(self.db_path + suffix)
            if path.exists():
                path.unlink()

    def _connect(self) -> None:
        """建立 SQLite 连接并加载 simple 分词器扩展。"""
        if self._conn:
            return
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")

        # 加载 simple 分词器扩展（幂等：只加载一次）
        if self._ext_path is None:
            self._ext_path = _check_tokenizer()
        self._conn.enable_load_extension(True)  # noqa: FBT003
        self._conn.load_extension(self._ext_path)

    def _ensure_column(self, table: str, column: str, col_type: str) -> None:
        """检查表是否包含指定列，没有则添加（用于旧表迁移）。"""
        self._connect()
        assert self._conn is not None
        cur = self._conn.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        if column not in cols:
            self.run(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
