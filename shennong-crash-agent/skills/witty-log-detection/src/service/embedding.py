# Copyright (c) Huawei Technologies Co., Ltd. 2023-2024. All rights reserved.
import asyncio
import requests
import json
import urllib3
import time
from src.config.config import Config
import logging
from src.enum.provider import ProviderEnum
from src.sqlite.manager.embedding_cache import EmbeddingCacheManager

logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class Embedding():
    @staticmethod
    def _validate_config():
        """验证Embedding配置是否有效"""
        config = Config().get_config().embedding_model
        
        if not config.api_key:
            raise ValueError("Embedding模型API Key未配置，请在配置文件中设置EMBEDDING_API_KEY")
        
        if not config.end_point:
            raise ValueError("Embedding模型End Point未配置，请在配置文件中设置EMBEDDING_END_POINT")
        
        if not config.model_name:
            raise ValueError("Embedding模型名称未配置，请在配置文件中设置EMBEDDING_MODEL_NAME")
        
        return config
    
    @staticmethod
    async def test_connection():
        """异步测试与Embedding服务的连接是否正常"""
        config = Embedding._validate_config()
        
        try:
            test_text = ["ping"]
            
            if config.provider == ProviderEnum.OPENAPI:
                headers = {"Authorization": f"Bearer {config.api_key}"}
                data = {
                    "input": test_text,
                    "model": config.model_name,
                    "encoding_format": "float"
                }
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(
                    None,
                    lambda: requests.post(
                        url=config.end_point,
                        headers=headers,
                        json=data,
                        verify=False,
                        timeout=10
                    )
                )
                if 200 <= res.status_code < 300:
                    logger.info("[Embedding] 连接测试成功")
                    return True
                else:
                    raise ValueError(f"Embedding模型连接失败，HTTP状态码: {res.status_code}")
            
            elif config.provider == ProviderEnum.ASCENDING:
                data = {"inputs": test_text[0]}
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(
                    None,
                    lambda: requests.post(
                        url=config.end_point, json=data, verify=False, timeout=10
                    )
                )
                if 200 <= res.status_code < 300:
                    logger.info("[Embedding] 连接测试成功")
                    return True
                else:
                    raise ValueError(f"Embedding模型连接失败，HTTP状态码: {res.status_code}")
            
            else:
                raise ValueError(f"不支持的Embedding提供者: {config.provider}")
        
        except Exception as e:
            logger.error(f"[Embedding] 连接测试失败: {e}")
            raise ValueError(f"Embedding模型连接失败，请检查配置: {e}")
    
    @staticmethod
    async def _fetch_embeddings_from_api(text_list: list[str], max_retries: int = 5, base_delay: float = 1.0) -> list[list[float]] | None:
        """从API获取embedding（不包含缓存逻辑）"""
        config = Embedding._validate_config()
        
        if config.provider == ProviderEnum.OPENAPI:
            headers = {"Authorization": f"Bearer {config.api_key}"}
            data = {
                "input": text_list,
                "model": config.model_name,
                "encoding_format": "float"
            }
            
            for retry in range(max_retries):
                try:
                    loop = asyncio.get_event_loop()
                    res = await loop.run_in_executor(
                        None,
                        lambda: requests.post(
                            url=config.end_point,
                            headers=headers,
                            json=data,
                            verify=False,
                            timeout=60
                        )
                    )
                    
                    if 200 <= res.status_code < 300:
                        result = res.json()
                        vectors = []
                        for item in result["data"]:
                            vec = item["embedding"]
                            while len(vec) < 1024:
                                vec.append(0.0)
                            vectors.append(vec[:1024])
                        return vectors
                    elif res.status_code == 429:
                        retry_after = res.headers.get("Retry-After")
                        delay = float(retry_after) if retry_after else base_delay * (2 ** retry)
                        logger.warning(f"[Embedding] 请求被限流 (429)，第 {retry+1}/{max_retries} 次重试，等待 {delay:.1f} 秒")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"[Embedding] 向量化接口失败 {res.status_code}")
                        return None
                        
                except requests.exceptions.ConnectionError as e:
                    delay = base_delay * (2 ** retry)
                    logger.warning(f"[Embedding] 连接错误，第 {retry+1}/{max_retries} 次重试，等待 {delay:.1f} 秒: {e}")
                    await asyncio.sleep(delay)
                except Exception as e:
                    logger.exception(f"[Embedding] 批量向量化失败: {e}")
                    return None
            
            logger.error(f"[Embedding] 达到最大重试次数 {max_retries}，放弃请求")
            return None
            
        elif config.provider == ProviderEnum.ASCENDING:
            vectors = []
            for text in text_list:
                success = False
                for retry in range(max_retries):
                    try:
                        data = {"inputs": text}
                        loop = asyncio.get_event_loop()
                        res = await loop.run_in_executor(
                            None,
                            lambda: requests.post(
                                url=config.end_point, json=data, verify=False, timeout=60
                            )
                        )
                        if 200 <= res.status_code < 300:
                            vec = json.loads(res.text)[0]
                            while len(vec) < 1024:
                                vec.append(0.0)
                            vectors.append(vec[:1024])
                            success = True
                            break
                        elif res.status_code == 429:
                            retry_after = res.headers.get("Retry-After")
                            delay = float(retry_after) if retry_after else base_delay * (2 ** retry)
                            logger.warning(f"[Embedding] 昇腾请求被限流 (429)，第 {retry+1}/{max_retries} 次重试，等待 {delay:.1f} 秒")
                            await asyncio.sleep(delay)
                        else:
                            logger.warning(f"[Embedding] 昇腾向量化失败 {res.status_code}")
                            await asyncio.sleep(base_delay * (2 ** retry))
                    except requests.exceptions.ConnectionError as e:
                        delay = base_delay * (2 ** retry)
                        logger.warning(f"[Embedding] 昇腾连接错误，第 {retry+1}/{max_retries} 次重试，等待 {delay:.1f} 秒: {e}")
                        await asyncio.sleep(delay)
                    except Exception as e:
                        logger.exception(f"[Embedding] 昇腾向量化失败: {e}")
                        break
                if not success:
                    vectors.append([0.0]*1024)
            return vectors
        else:
            return None

    @staticmethod
    async def get_embedding_with_retry(text_list: list[str], max_retries: int = 5, base_delay: float = 1.0, use_cache: bool = True) -> list[list[float]] | None:
        """带重试机制和缓存的向量化接口调用"""
        config = Config().get_config().embedding_model
        model_name = config.model_name
        
        if not use_cache:
            return await Embedding._fetch_embeddings_from_api(text_list, max_retries, base_delay)
        
        # 先从缓存批量查询
        cached_results, uncached_indices = await EmbeddingCacheManager.get_embeddings_batch_from_cache(text_list, model_name)
        
        # logger.info(f"[Embedding] 缓存查询: 命中 {len(cached_results)}/{len(text_list)} 条")
        
        # 如果全部命中，直接返回
        if len(cached_results) == len(text_list):
            return [cached_results[i] for i in range(len(text_list))]
        
        # 获取需要从API获取的文本
        texts_to_fetch = [text_list[i] for i in uncached_indices]
        
        # 从API获取
        api_vectors = await Embedding._fetch_embeddings_from_api(texts_to_fetch, max_retries, base_delay)
        
        if api_vectors is None:
            logger.error(f"[Embedding] API获取失败，返回全0向量")
            return [[0.0]*1024 for _ in text_list]
        
        # 保存新获取的向量到缓存
        await EmbeddingCacheManager.save_embeddings_batch_to_cache(texts_to_fetch, api_vectors, model_name)
        
        # 合并结果
        final_vectors = []
        api_idx = 0
        for i in range(len(text_list)):
            if i in cached_results:
                final_vectors.append(cached_results[i])
            else:
                final_vectors.append(api_vectors[api_idx])
                api_idx += 1
        
        return final_vectors

    @staticmethod
    async def get_embedding(text_list: list[str], use_cache: bool = True) -> list[list[float]] | None:
        """批量获取文本向量（一次API，多条文本） - 保持向后兼容"""
        return await Embedding.get_embedding_with_retry(text_list, use_cache=use_cache)

    @staticmethod
    async def vectorize_embedding(text_list: list[str], use_cache: bool = True) -> list[list[float]]:
        config = Config().get_config()
        batch_size = config.embedding_model.batch_size
        embeddings = []
        total_batch = (len(text_list) + batch_size - 1) // batch_size
        
        base_delay_between_batches = 1.0

        for i in range(0, len(text_list), batch_size):
            current_batch = i // batch_size + 1
            #logger.info(f"开始向量化第 {current_batch}/{total_batch} 个批次")
            batch_texts = text_list[i:i + batch_size]

            batch_embeddings = await Embedding.get_embedding_with_retry(batch_texts, use_cache=use_cache)
            
            if batch_embeddings:
                embeddings.extend(batch_embeddings)
            else:
                embeddings.extend([[0.0]*1024 for _ in batch_texts])
            
            if i + batch_size < len(text_list):
                await asyncio.sleep(base_delay_between_batches)

        return embeddings