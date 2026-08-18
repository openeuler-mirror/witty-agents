import hashlib
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging
from src.sqlite.sqlite import EmbeddingCacheSQLite
from src.config.config import Config

logger = logging.getLogger(__name__)


class EmbeddingCacheManager:
    """Embedding缓存管理类"""

    @staticmethod
    def _compute_text_hash(text: str) -> str:
        """计算文本的SHA-256哈希值"""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    @staticmethod
    async def get_embedding_from_cache(
        text: str,
        model_name: Optional[str] = None
    ) -> Optional[List[float]]:
        """
        从缓存中获取embedding向量
        
        Args:
            text: 输入文本
            model_name: 模型名称，如果为None则使用配置中的模型
            
        Returns:
            缓存的embedding向量，如果没有缓存则返回None
        """
        if model_name is None:
            model_name = Config().get_config().embedding_model.model_name
        
        text_hash = EmbeddingCacheManager._compute_text_hash(text)
        
        sql_str = """
            SELECT embedding_vector, text_content, model_name
            FROM embedding_cache_table
            WHERE text_hash = :text_hash AND model_name = :model_name
        """
        params = {"text_hash": text_hash, "model_name": model_name}
        
        try:
            results = await EmbeddingCacheSQLite().execute_query(sql_str, params)
            
            if results:
                # 更新访问时间和访问计数
                await EmbeddingCacheManager._update_access_stats(text_hash)
                
                # 解析向量
                embedding_data = results[0]
                embedding_vector = json.loads(embedding_data["embedding_vector"])
                logger.debug(f"从缓存中获取到embedding: {text[:50]}...")
                return embedding_vector
        except Exception as e:
            logger.error(f"从缓存获取embedding失败: {e}")
        
        return None

    @staticmethod
    async def get_embeddings_batch_from_cache(
        texts: List[str],
        model_name: Optional[str] = None
    ) -> Tuple[Dict[int, List[float]], List[int]]:
        """
        批量从缓存中获取embedding向量
        
        Args:
            texts: 输入文本列表
            model_name: 模型名称，如果为None则使用配置中的模型
            
        Returns:
            (缓存结果字典, 未缓存的索引列表)
            缓存结果字典: {文本索引: embedding向量}
        """
        if model_name is None:
            model_name = Config().get_config().embedding_model.model_name
        
        if not texts:
            return {}, []
        
        text_hashes = [EmbeddingCacheManager._compute_text_hash(text) for text in texts]
        placeholders = ', '.join(['?'] * len(text_hashes))
        sql_str = f"""
            SELECT text_hash, embedding_vector, text_content
            FROM embedding_cache_table
            WHERE text_hash IN ({placeholders}) AND model_name = ?
        """
        params = text_hashes + [model_name]
        
        cached_results = {}
        cached_hashes = set()
        
        try:
            results = await EmbeddingCacheSQLite().execute_query(sql_str, params)
            
            hash_to_embedding = {}
            for row in results:
                hash_to_embedding[row["text_hash"]] = json.loads(row["embedding_vector"])
                cached_hashes.add(row["text_hash"])
            
            for idx, (text, text_hash) in enumerate(zip(texts, text_hashes)):
                if text_hash in hash_to_embedding:
                    cached_results[idx] = hash_to_embedding[text_hash]
            
            if cached_hashes:
                await EmbeddingCacheManager._update_access_stats_batch(list(cached_hashes))
            
            logger.debug(f"批量缓存查询: 命中 {len(cached_results)}/{len(texts)}")
            
        except Exception as e:
            logger.error(f"批量从缓存获取embedding失败: {e}")
        
        uncached_indices = [idx for idx in range(len(texts)) if idx not in cached_results]
        return cached_results, uncached_indices

    @staticmethod
    async def save_embedding_to_cache(
        text: str,
        embedding_vector: List[float],
        model_name: Optional[str] = None
    ) -> bool:
        """保存embedding到缓存"""
        if model_name is None:
            model_name = Config().get_config().embedding_model.model_name
        
        text_hash = EmbeddingCacheManager._compute_text_hash(text)
        now_str = datetime.now().isoformat()
        
        sql_str = """
            INSERT OR REPLACE INTO embedding_cache_table 
            (text_hash, text_content, embedding_vector, model_name, created_at, last_accessed_at, access_count)
            VALUES (:text_hash, :text_content, :embedding_vector, :model_name, :created_at, :last_accessed_at, :access_count)
        """
        
        existing = await EmbeddingCacheManager._get_cache_entry(text_hash, model_name)
        access_count = existing["access_count"] + 1 if existing else 0
        created_at = existing["created_at"] if existing else now_str
        
        params = {
            "text_hash": text_hash,
            "text_content": text,
            "embedding_vector": json.dumps(embedding_vector),
            "model_name": model_name,
            "created_at": created_at,
            "last_accessed_at": now_str,
            "access_count": access_count
        }
        
        try:
            result = await EmbeddingCacheSQLite().execute_modify(sql_str, params)
            if result:
                logger.debug(f"embedding已保存到缓存: {text[:50]}...")
            return result
        except Exception as e:
            logger.error(f"保存embedding到缓存失败: {e}")
            return False

    @staticmethod
    async def save_embeddings_batch_to_cache(
        texts: List[str],
        embedding_vectors: List[List[float]],
        model_name: Optional[str] = None
    ) -> bool:
        """批量保存embedding到缓存"""
        if model_name is None:
            model_name = Config().get_config().embedding_model.model_name
        
        if len(texts) != len(embedding_vectors):
            logger.error(f"文本数量 ({len(texts)}) 与向量数量 ({len(embedding_vectors)}) 不匹配")
            return False
        
        if not texts:
            return True
        
        now_str = datetime.now().isoformat()
        text_hashes = [EmbeddingCacheManager._compute_text_hash(text) for text in texts]
        existing_entries = await EmbeddingCacheManager._get_cache_entries_batch(text_hashes, model_name)
        
        batch_data = []
        for text, vector, text_hash in zip(texts, embedding_vectors, text_hashes):
            existing = existing_entries.get(text_hash)
            access_count = existing["access_count"] + 1 if existing else 0
            created_at = existing["created_at"] if existing else now_str
            
            batch_data.append((
                text_hash,
                text,
                json.dumps(vector),
                model_name,
                created_at,
                now_str,
                access_count
            ))
        
        sql_str = """
            INSERT OR REPLACE INTO embedding_cache_table 
            (text_hash, text_content, embedding_vector, model_name, created_at, last_accessed_at, access_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        
        try:
            result = await EmbeddingCacheSQLite().execute_modify(sql_str, batch_data)
            if result:
                logger.debug(f"批量保存embedding到缓存: {len(batch_data)} 条")
            return result
        except Exception as e:
            logger.error(f"批量保存embedding到缓存失败: {e}")
            return False

    @staticmethod
    async def _get_cache_entry(text_hash: str, model_name: str) -> Optional[Dict]:
        """获取单个缓存条目（内部方法）"""
        sql_str = """
            SELECT created_at, access_count
            FROM embedding_cache_table
            WHERE text_hash = :text_hash AND model_name = :model_name
        """
        params = {"text_hash": text_hash, "model_name": model_name}
        
        results = await EmbeddingCacheSQLite().execute_query(sql_str, params)
        return results[0] if results else None

    @staticmethod
    async def _get_cache_entries_batch(text_hashes: List[str], model_name: str) -> Dict[str, Dict]:
        """批量获取缓存条目（内部方法）"""
        if not text_hashes:
            return {}
        
        placeholders = ', '.join(['?'] * len(text_hashes))
        sql_str = f"""
            SELECT text_hash, created_at, access_count
            FROM embedding_cache_table
            WHERE text_hash IN ({placeholders}) AND model_name = ?
        """
        params = text_hashes + [model_name]
        
        results = await EmbeddingCacheSQLite().execute_query(sql_str, params)
        return {row["text_hash"]: row for row in results}

    @staticmethod
    async def _update_access_stats(text_hash: str) -> None:
        """更新单个条目的访问统计（内部方法）"""
        now_str = datetime.now().isoformat()
        sql_str = """
            UPDATE embedding_cache_table
            SET last_accessed_at = :last_accessed_at, access_count = access_count + 1
            WHERE text_hash = :text_hash
        """
        params = {"last_accessed_at": now_str, "text_hash": text_hash}
        await EmbeddingCacheSQLite().execute_modify(sql_str, params)

    @staticmethod
    async def _update_access_stats_batch(text_hashes: List[str]) -> None:
        """批量更新访问统计（内部方法）"""
        if not text_hashes:
            return
        
        now_str = datetime.now().isoformat()
        placeholders = ', '.join(['?'] * len(text_hashes))
        sql_str = f"""
            UPDATE embedding_cache_table
            SET last_accessed_at = ?, access_count = access_count + 1
            WHERE text_hash IN ({placeholders})
        """
        params = [now_str] + text_hashes
        await EmbeddingCacheSQLite().execute_modify(sql_str, params)

    @staticmethod
    async def clear_old_cache(older_than_days: int = 30) -> int:
        """清理旧的缓存条目"""
        from datetime import timedelta
        cutoff_date = (datetime.now() - timedelta(days=older_than_days)).isoformat()
        
        sql_str = """
            DELETE FROM embedding_cache_table
            WHERE last_accessed_at < :cutoff_date
        """
        params = {"cutoff_date": cutoff_date}
        
        count_sql = """
            SELECT COUNT(*) as count
            FROM embedding_cache_table
            WHERE last_accessed_at < :cutoff_date
        """
        count_result = await EmbeddingCacheSQLite().execute_query(count_sql, params)
        count = count_result[0]["count"] if count_result else 0
        
        await EmbeddingCacheSQLite().execute_modify(sql_str, params)
        
        logger.info(f"清理了 {count} 条旧缓存（超过 {older_than_days} 天未访问）")
        return count

    @staticmethod
    async def get_cache_stats() -> Dict:
        """获取缓存统计信息"""
        stats = {}
        
        count_sql = "SELECT COUNT(*) as count FROM embedding_cache_table"
        count_result = await EmbeddingCacheSQLite().execute_query(count_sql)
        stats["total_entries"] = count_result[0]["count"] if count_result else 0
        
        model_sql = """
            SELECT model_name, COUNT(*) as count, SUM(access_count) as total_accesses
            FROM embedding_cache_table
            GROUP BY model_name
        """
        model_results = await EmbeddingCacheSQLite().execute_query(model_sql)
        stats["by_model"] = {row["model_name"]: {
            "count": row["count"],
            "total_accesses": row["total_accesses"]
        } for row in model_results}
        
        recent_sql = """
            SELECT text_content, access_count, last_accessed_at
            FROM embedding_cache_table
            ORDER BY last_accessed_at DESC
            LIMIT 10
        """
        recent_results = await EmbeddingCacheSQLite().execute_query(recent_sql)
        stats["recent_accesses"] = recent_results
        
        return stats
