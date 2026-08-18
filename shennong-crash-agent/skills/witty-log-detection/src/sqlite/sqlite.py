import os
from multiprocessing import Lock as ProcessLock
import asyncio
import sqlite3
import logging
from typing import Any, Optional
from src.config.config import Config

# 配置日志
logger = logging.getLogger(__name__)

# 表结构定义
table_ddl_list = {
    "task_table": '''
        CREATE TABLE IF NOT EXISTS task_table (
            task_id TEXT PRIMARY KEY,
            pid INTEGER,
            task_name TEXT NOT NULL,
            task_type TEXT NOT NULL,
            completion_precent REAL NOT NULL,
            status TEXT NOT NULL,
            task_related_params TEXT,
            created_at TEXT NOT NULL
        )
    ''',
    "log_parse_result_table": '''
        CREATE TABLE IF NOT EXISTS log_parse_result_table(
            id TEXT PRIMARY KEY,
            file_path TEXT,
            offset INTEGER,
            is_anomalous BOOLEAN NOT NULL,
            task_id TEXT,
            content TEXT,
            anomaly_reason TEXT,
            anomaly_score REAL,
            duplicate_count INTEGER DEFAULT 1,
            FOREIGN KEY (task_id) REFERENCES task_table (task_id) ON DELETE CASCADE
        )
    ''',
    "embedding_cache_table": '''
        CREATE TABLE IF NOT EXISTS embedding_cache_table (
            text_hash TEXT PRIMARY KEY,
            text_content TEXT NOT NULL,
            embedding_vector TEXT NOT NULL,
            model_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_accessed_at TEXT NOT NULL,
            access_count INTEGER DEFAULT 0
        )
    ''',
    "embedding_cache_index": '''
        CREATE INDEX IF NOT EXISTS idx_embedding_model ON embedding_cache_table (model_name)
    '''
}


class _SQLiteConnBase:
    """SQLite 连接管理基类

    提供进程级单例、连接复用、异步 SQL 接口等公共能力。
    子类需指定数据库路径，并可选择是否启用外键约束。
    """
    _instances: dict[tuple[type, int], '_SQLiteConnBase'] = {}
    _process_lock = ProcessLock()

    def __new__(cls):
        """实现单例模式（支持多进程）"""
        pid = os.getpid()
        key = (cls, pid)
        if key not in cls._instances:
            with cls._process_lock:
                if key not in cls._instances:
                    logger.debug(f"为进程 {pid} 创建新的 {cls.__name__} 实例")
                    cls._instances[key] = super().__new__(cls)
        return cls._instances[key]

    def __init__(self, db_path: str, *, enable_foreign_keys: bool = False, log_prefix: str = ""):
        # 防止重复初始化
        if hasattr(self, '_initialized') and self._initialized:
            return

        self.DB_PATH = db_path
        self._async_lock = asyncio.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._initialized = False
        self._enable_foreign_keys = enable_foreign_keys
        self._log_prefix = log_prefix

        self._init_connection()

    def _init_connection(self):
        """初始化数据库连接（复用连接）"""
        try:
            self._conn = sqlite3.connect(
                self.DB_PATH,
                check_same_thread=False,
                timeout=30.0,
                isolation_level=None
            )
            if self._enable_foreign_keys:
                self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")

            prefix = f"{self._log_prefix} " if self._log_prefix else ""
            logger.debug(f"进程 {os.getpid()} {prefix}数据库连接初始化成功")
        except sqlite3.Error as e:
            prefix = f"{self._log_prefix}" if self._log_prefix else "数据库"
            logger.error(f"{prefix}连接初始化失败: {e}")
            raise

    def _ensure_connection(self):
        """确保数据库连接可用"""
        if not self._conn:
            prefix = f"{self._log_prefix} " if self._log_prefix else ""
            logger.debug(f"进程 {os.getpid()} {prefix}连接为空，正在重新初始化")
            self._init_connection()
            return True

        try:
            self._conn.execute("SELECT 1")
            return True
        except (sqlite3.Error, sqlite3.ProgrammingError):
            prefix = f"{self._log_prefix} " if self._log_prefix else ""
            logger.warning(f"进程 {os.getpid()} {prefix}连接失效，正在重新初始化")
            self._init_connection()
            return True

    def _sync_execute_query(self, sql: str, params: dict | tuple = ()) -> list[dict]:
        """同步执行查询（复用连接）"""
        self._ensure_connection()

        try:
            self._conn.row_factory = sqlite3.Row
            cursor = self._conn.cursor()
            cursor.execute(sql, params)
            results = [dict(row) for row in cursor.fetchall()]
            prefix = f"{self._log_prefix} " if self._log_prefix else ""
            logger.debug(f"{prefix}查询成功，返回 {len(results)} 条记录")
            return results
        except (sqlite3.Error, sqlite3.ProgrammingError) as e:
            prefix = f"{self._log_prefix} " if self._log_prefix else ""
            logger.warning(f"{prefix}查询失败，尝试重新连接: {e}")
            self._init_connection()
            try:
                self._conn.row_factory = sqlite3.Row
                cursor = self._conn.cursor()
                cursor.execute(sql, params)
                results = [dict(row) for row in cursor.fetchall()]
                logger.debug(f"{prefix}重试查询成功，返回 {len(results)} 条记录")
                return results
            except Exception as e2:
                logger.error(f"{prefix}重试查询也失败: {e2} (SQL: {sql})")
                return []

    def _sync_execute_modify(self, sql: str, params: Any = ()) -> bool:
        """
        同步执行增删改（支持单条/批量，复用连接）
        :param sql: SQL修改语句（位置参数用?，命名参数用:param_name）
        :param params: 单条：dict/元组；批量：list[元组]
        :return: 是否执行成功
        """
        self._ensure_connection()

        try:
            cursor = self._conn.cursor()

            if isinstance(params, list) and len(params) > 0 and isinstance(params[0], (tuple, list)):
                cursor.executemany(sql, params)
                prefix = f"{self._log_prefix} " if self._log_prefix else ""
                logger.debug(f"{prefix}批量修改成功，影响行数: {cursor.rowcount}")
            else:
                cursor.execute(sql, params)
                prefix = f"{self._log_prefix} " if self._log_prefix else ""
                logger.debug(f"{prefix}单条修改成功，影响行数: {cursor.rowcount}")

            self._conn.commit()
            return True
        except (sqlite3.Error, sqlite3.ProgrammingError) as e:
            prefix = f"{self._log_prefix} " if self._log_prefix else ""
            logger.warning(f"{prefix}修改失败，尝试重新连接: {e}")
            try:
                self._conn.rollback()
            except:
                pass
            self._init_connection()
            try:
                cursor = self._conn.cursor()
                if isinstance(params, list) and len(params) > 0 and isinstance(params[0], (tuple, list)):
                    cursor.executemany(sql, params)
                else:
                    cursor.execute(sql, params)
                self._conn.commit()
                logger.debug(f"{prefix}重试修改成功")
                return True
            except Exception as e2:
                logger.error(f"{prefix}重试修改也失败: {e2} (SQL: {sql})")
                return False

    # -------------------------- 异步封装接口 --------------------------
    async def init_database(self) -> bool:
        """异步初始化数据库"""
        async with self._async_lock:
            return await asyncio.to_thread(self._sync_init_database)

    async def execute_query(self, sql: str, params: dict | tuple = ()) -> list[dict]:
        """
        异步执行查询语句
        :param sql: SQL查询语句（支持命名参数 :param_name 或位置参数 ?）
        :param params: 命名参数字典或位置参数元组
        :return: 查询结果列表（每行是字典）
        """
        async with self._async_lock:
            return await asyncio.to_thread(self._sync_execute_query, sql, params)

    async def execute_modify(self, sql: str, params: Any = ()) -> bool:
        """
        异步执行增删改语句
        :param sql: SQL修改语句（支持命名参数 :param_name 或位置参数 ?）
        :param params: 命名参数字典或位置参数元组
        :return: 是否执行成功
        """
        async with self._async_lock:
            return await asyncio.to_thread(self._sync_execute_modify, sql, params)

    async def close_connection(self):
        """关闭数据库连接"""
        async with self._async_lock:
            def _close():
                if self._conn:
                    self._conn.close()
                    self._conn = None
                    prefix = f"{self._log_prefix} " if self._log_prefix else ""
                    logger.info(f"{prefix}数据库连接已关闭")
            await asyncio.to_thread(_close)

    def __del__(self):
        """析构函数：确保连接关闭"""
        if self._conn:
            try:
                self._conn.close()
                prefix = f"{self._log_prefix} " if self._log_prefix else ""
                logger.info(f"析构函数中关闭{prefix}数据库连接")
            except:
                pass


class AsyncSQLiteSingleton(_SQLiteConnBase):
    """主业务数据库单例"""

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        config = Config().get_config()
        super().__init__(
            db_path=config.sql_lite_db_path,
            enable_foreign_keys=True,
            log_prefix=""
        )
        self._sync_init_database()

    def _sync_init_database(self) -> bool:
        """同步初始化数据库（复用连接）"""
        if not self._conn:
            logger.debug(f"进程 {os.getpid()} 重新初始化连接")
            self._init_connection()

        if not self._conn:
            logger.error("无法建立数据库连接")
            return False

        try:
            for _table_name, ddl in table_ddl_list.items():
                self._conn.execute(ddl)
            # 迁移：为已有表添加 duplicate_count 列
            try:
                self._conn.execute("ALTER TABLE log_parse_result_table ADD COLUMN duplicate_count INTEGER DEFAULT 1")
            except sqlite3.OperationalError:
                pass
            self._conn.commit()
            logger.info(f"进程 {os.getpid()} 数据库初始化成功，表创建完成")
            self._initialized = True
            return True
        except sqlite3.Error as e:
            try:
                self._conn.rollback()
            except:
                pass
            logger.error(f"数据库初始化失败: {e}")
            return False


class EmbeddingCacheSQLite(_SQLiteConnBase):
    """Embedding缓存专用的SQLite数据库单例

    与主数据库分离，独立管理embedding缓存
    """

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        config = Config().get_config()
        super().__init__(
            db_path=config.embedding_cache_db_path,
            enable_foreign_keys=False,
            log_prefix="Embedding缓存"
        )
        self._sync_init_database()

    def _sync_init_database(self) -> bool:
        """同步初始化数据库（复用连接）"""
        self._ensure_connection()

        try:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS embedding_cache_table (
                    text_hash TEXT PRIMARY KEY,
                    text_content TEXT NOT NULL,
                    embedding_vector TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_accessed_at TEXT NOT NULL,
                    access_count INTEGER DEFAULT 0
                )
            """)

            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_embedding_model ON embedding_cache_table (model_name)
            """)

            self._conn.commit()
            logger.info(f"进程 {os.getpid()} Embedding缓存数据库初始化成功")
            self._initialized = True
            return True
        except sqlite3.Error as e:
            try:
                self._conn.rollback()
            except:
                pass
            logger.error(f"Embedding缓存数据库初始化失败: {e}")
            return False
