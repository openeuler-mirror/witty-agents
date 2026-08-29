"""经验数据访问层。"""

from datetime import datetime
from typing import Any

from experience_skill_cli.common.exprience import HOT_EXPRINCE_CNT_LIMIT
from experience_skill_cli.schema.enum import ExperienceStatus, ExperienceType
from experience_skill_cli.schema.exprience import Experience
from experience_skill_cli.sqlite import AsyncSQLiteSingleton


class ExperienceManager:
    """经验管理器，负责经验的增删改查及 FTS5 全文检索。"""

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_experience(row: dict[str, Any]) -> Experience:
        """将数据库行转换为 Experience 对象。"""
        return Experience(
            id=row["id"],
            type=ExperienceType(row["type"]),
            name=row["name"],
            description=row["description"],
            references=row["references"],
            status=ExperienceStatus(row["status"]),
            is_hot=bool(row["is_hot"]),
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # 写入操作
    # ------------------------------------------------------------------
    @staticmethod
    def add_experiences(experiences: list[Experience]) -> None:
        """批量添加经验记录。"""
        db = AsyncSQLiteSingleton()
        for experience in experiences:
            db.run(
                """
                INSERT INTO experience_table
                    (id, type, name, description, "references", status, is_hot, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experience.id,
                    experience.type.value,
                    experience.name,
                    experience.description,
                    experience.references,
                    experience.status.value,
                    experience.is_hot,
                    experience.source,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # noqa: DTZ005
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # noqa: DTZ005
                ),
            )

    @staticmethod
    def delete_experiences_by_ids(experience_ids: list[str]) -> None:
        """按 ID 列表软删除经验。"""
        db = AsyncSQLiteSingleton()
        placeholders = ",".join(["?"] * len(experience_ids))
        db.run(
            f"""
            UPDATE experience_table
            SET status = ?
            WHERE id IN ({placeholders})
            """,
            (ExperienceStatus.DELETED.value, *experience_ids),
        )

    @staticmethod
    def update_experience(experience: Experience) -> None:
        """更新经验记录。"""
        db = AsyncSQLiteSingleton()
        db.run(
            """
            UPDATE experience_table
            SET type = ?, name = ?, description = ?, "references" = ?, status = ?, source = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                experience.type.value,
                experience.name,
                experience.description,
                experience.references,
                experience.status.value,
                experience.source,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # noqa: DTZ005
                experience.id,
            ),
        )

    @staticmethod
    def update_hot_experience(experience_id: str) -> None:
        """更新经验热度（最多保留 20 条热门）。"""
        db = AsyncSQLiteSingleton()
        # 先查当前的experience是否存在
        experience = db.query(
            """
            SELECT * FROM experience_table WHERE id = ? AND status = ?
            """,
            (experience_id, ExperienceStatus.EXISTED.value),
        )
        if experience:
            if experience[0]["is_hot"] == 1:
                # 更新updated_at
                db.run(
                    """
                    UPDATE experience_table
                    SET updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # noqa: DTZ005
                        experience_id,
                    ),
                )
                return
            experience_type = experience[0]["type"]
            hot_experience_cnt = db.query(
                """\
                SELECT COUNT(*) as cnt FROM experience_table
                WHERE type = ? AND is_hot = 1 AND status = ?
                """,
                (experience_type, ExperienceStatus.EXISTED.value),
            )[0]["cnt"]
            if hot_experience_cnt >= HOT_EXPRINCE_CNT_LIMIT:
                # 将最早的热门经验取消热门标记
                db.run(
                    """
                    UPDATE experience_table
                    SET is_hot = 0
                    WHERE id = (
                        SELECT id FROM experience_table
                        WHERE type = ? AND is_hot = 1 AND status = ?
                        ORDER BY updated_at ASC LIMIT 1
                    )
                    """,
                    (experience_type, ExperienceStatus.EXISTED.value),
                )
            db.run(
                """
                    UPDATE experience_table
                    SET is_hot = 1, updated_at = ?
                    WHERE id = ?
                    """,
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # noqa: DTZ005
                    experience_id,
                ),
            )

    @staticmethod
    def list_experiences(
        experience_type: ExperienceType | None,
        keywords: list[str] | None,
        name: str | None,
        is_hot: bool | None,
        page: int,
        page_size: int,
        *,
        experience_ids: list[str] | None = None,
    ) -> tuple[int, list[Experience]]:
        """列出经验列表，支持多条件筛选和分页。"""
        if keywords is not None and len(keywords) == 0:
            return 0, []
        if experience_ids is not None and len(experience_ids) == 0:
            return 0, []
        db = AsyncSQLiteSingleton()
        offset = (page - 1) * page_size
        where_clauses = ["status = ?"]
        params: list[Any] = [ExperienceStatus.EXISTED.value]
        if experience_type is not None:
            where_clauses.append("type = ?")
            params.append(experience_type.value)
        if keywords is not None:
            where_clauses.append(" AND ".join(["description LIKE ?"] * len(keywords)))
            params.extend([f"%{keyword}%" for keyword in keywords])
        if name is not None:
            where_clauses.append("name LIKE ?")
            params.append(f"%{name}%")
        if is_hot is not None:
            where_clauses.append("is_hot = ?")
            params.append(int(is_hot))
        if experience_ids is not None:
            placeholders = ",".join(["?"] * len(experience_ids))
            where_clauses.append(f"id IN ({placeholders})")
            params.extend(experience_ids)
        where_clause = " AND ".join(where_clauses)
        total_cnt = db.query(
            f"""
            SELECT COUNT(*) as cnt FROM experience_table
            WHERE {where_clause}
            """,
            params,
        )[0]["cnt"]
        experience_rows = db.query(
            f"""
            SELECT * FROM experience_table
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, offset),
        )
        experiences = [ExperienceManager._row_to_experience(r) for r in experience_rows]
        return total_cnt, experiences

    @staticmethod
    def query_experience_by_fts5_use_description(
        keywords: list[str],
        exp_type: ExperienceType,
        fields: list[str] | None = None,
        top_k: int = 5,
        is_hot: bool | None = None,
        banned_experience_ids: list[str] | None = None,
        experience_ids: list[str] | None = None,
    ) -> list[Experience]:
        """
        基于 FTS5 检索 Experience（适配 simple tokenizer 扩展）。

        1. 先使用 simple_query() 做 AND 语义精确查询（支持中文/拼音）
        2. 不足数量再使用标准 OR 语法做松散查询补全
        """
        # 1. 初始化默认参数
        if top_k <= 0:
            return []
        if fields is not None and len(fields) == 0:
            return []
        if experience_ids is not None and len(experience_ids) == 0:
            return []

        # 初始化列表，不修改外部传入参数
        banned_ids = banned_experience_ids.copy() if banned_experience_ids else []
        target_experience_ids = experience_ids

        db = AsyncSQLiteSingleton()
        tight_query_cnt = max(1, top_k // 2)
        experiences = []

        # ====================== 抽取公共方法：避免代码重复 ======================
        def build_fts_query(
            match_expr: str,
            limit: int,
            use_simple_query: bool = False,
        ) -> tuple[str, list[Any]]:
            """构建 SQL 和参数（公共逻辑）。"""
            # 基础：关联FTS表
            from_clause = """
                FROM experience_table
                JOIN experience_fts ON experience_table.rowid = experience_fts.rowid
            """
            if use_simple_query:
                where_clause = "WHERE experience_fts MATCH simple_query(?) AND type = ?"
            else:
                where_clause = "WHERE experience_fts MATCH ? AND type = ?"
            params: list[Any] = [match_expr, exp_type.value]

            # ====================== fields 筛选（关联keyword_table） ======================
            if fields is not None and len(fields) > 0:
                # 关联关键词表，只保留name在fields里的experience
                from_clause += """
                    JOIN keyword_table ON experience_table.id = keyword_table.experience_id
                """
                # 生成占位符
                field_placeholders = ",".join(["?"] * len(fields))
                where_clause += f" AND keyword_table.name IN ({field_placeholders})"
                params.extend(fields)

            # 过滤已排除ID
            if banned_ids:
                placeholders = ",".join(["?"] * len(banned_ids))
                where_clause += f" AND experience_table.id NOT IN ({placeholders})"
                params.extend(banned_ids)

            # 过滤指定ID
            if target_experience_ids:
                placeholders = ",".join(["?"] * len(target_experience_ids))
                where_clause += f" AND experience_table.id IN ({placeholders})"
                params.extend(target_experience_ids)

            # 安全拼接is_hot
            if is_hot is not None:
                where_clause += " AND experience_table.is_hot = ?"
                params.append(int(is_hot))

            # 最终SQL（去重，避免一个experience匹配多个keyword返回多条）
            sql = f"""
            SELECT DISTINCT experience_table.*
            {from_clause}
            {where_clause}
            ORDER BY experience_fts.rank
            LIMIT ?
            """
            params.append(limit)
            return sql, params

        # ====================== 1. 紧凑查询（simple_query AND 语义） ======================
        and_keywords = " ".join(keywords)
        sql, params = build_fts_query(
            and_keywords,
            tight_query_cnt,
            use_simple_query=True,
        )

        experience_rows = db.query(sql, params)
        experiences = [ExperienceManager._row_to_experience(r) for r in experience_rows]

        # 已查到的ID加入排除
        banned_ids.extend([exp.id for exp in experiences])

        # ====================== 2. 松散查询（标准 OR 语法补全） ======================
        if len(experiences) < top_k:
            loose_cnt = top_k - len(experiences)
            or_keywords = " OR ".join(keywords)
            sql, params = build_fts_query(
                or_keywords,
                loose_cnt,
                use_simple_query=False,
            )

            experience_rows = db.query(sql, params)
            experiences.extend(
                ExperienceManager._row_to_experience(r) for r in experience_rows
            )

        return experiences

    @staticmethod
    def query_experience_ids_by_source(source: str) -> list[str]:
        """按来源路径查询经验 ID 列表。"""
        db = AsyncSQLiteSingleton()
        rows = db.query(
            "SELECT id FROM experience_table WHERE source = ? AND status = ?",
            (source, ExperienceStatus.EXISTED.value),
        )
        return [row["id"] for row in rows]

    @staticmethod
    def query_experience_by_ids(experience_ids: list[str]) -> list[Experience]:
        """按 ID 列表查询经验。"""
        if len(experience_ids) == 0:
            return []
        db = AsyncSQLiteSingleton()
        placeholders = ",".join(["?"] * len(experience_ids))
        rows = db.query(
            f"SELECT * FROM experience_table WHERE id IN ({placeholders}) AND status = ?",
            (*experience_ids, ExperienceStatus.EXISTED.value),
        )
        return [ExperienceManager._row_to_experience(r) for r in rows]

    @staticmethod
    def query_experience_by_source(source: str) -> list[Experience]:
        """按来源路径查询经验列表。"""
        db = AsyncSQLiteSingleton()
        rows = db.query(
            "SELECT * FROM experience_table WHERE source = ? AND status = ?",
            (source, ExperienceStatus.EXISTED.value),
        )
        return [ExperienceManager._row_to_experience(r) for r in rows]
