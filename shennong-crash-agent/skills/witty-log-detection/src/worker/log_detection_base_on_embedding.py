
import json
import logging
import numpy as np
import jieba
import re
import asyncio
from datetime import datetime
from src.worker.base import BaseWorker
from src.parser.parser import LogParser
from src.parser.log_feature_loader import log_feature_class_mapping
from src.sqlite.manager.task import TaskManager
from src.schemas.task import TaskRelatedParamsModel
from src.enum.log import LogTypeEnum
from src.enum.task import TaskTypeEnum, TaskStatusEnum
from src.schemas.log import LogModel
from src.service.embedding import Embedding
from src.config.config import Config
from src.enum.query_intent import QueryIntentEnum

logger = logging.getLogger(__name__)


class LogDetectionBasedOnEmbeddingWorker(BaseWorker):
    """
    基于 Embedding 聚类和关键字匹配的日志检测 Worker
    """
    name = TaskTypeEnum.LOG_DETECTION_BASE_ON_EMBEDDING.value

    @staticmethod
    def cal_keyword_similarity(
        log_words: list[str],
        word_vector_dict: dict[str, list[float]],
        keyword_vectors: list[list[float]],
        query_word_vectors: list[list[float]]
    ) -> float:
        """计算基于embedding的关键字相似度：
        1. 使用预计算的词向量字典
        2. 计算每个词与keywords和query词的余弦相似度
        3. 取平均值"""
        if not keyword_vectors and not query_word_vectors:
            return 0.0
        
        if not log_words:
            return 0.0
        
        total_similarity = 0.0
        count = 0
        
        for word in log_words:
            log_vec = word_vector_dict.get(word)
            if log_vec is None:
                continue
            
            max_keyword_sim = 0.0
            for kw_vec in keyword_vectors:
                sim = LogDetectionBasedOnEmbeddingWorker.cosine_similarity(log_vec, kw_vec)
                if sim > max_keyword_sim:
                    max_keyword_sim = sim
            
            max_query_sim = 0.0
            for qw_vec in query_word_vectors:
                sim = LogDetectionBasedOnEmbeddingWorker.cosine_similarity(log_vec, qw_vec)
                if sim > max_query_sim:
                    max_query_sim = sim
            
            word_sim = max(max_keyword_sim, max_query_sim)
            total_similarity += word_sim
            count += 1
        
        return total_similarity / count if count > 0 else 0.0

    @staticmethod
    async def cal_sentiment_score(log_type: LogTypeEnum, log_content: str) -> float:
        """计算日志的情感分数"""
        log_class = log_feature_class_mapping.get(log_type, None)
        if log_class is None:
            return 0.0
        sum = 0.0
        score = 0.0
        for anomalous_keywords, _ in log_class.keywords_regex_and_scores["anomalous"].items():
            sum += _
            if re.search(anomalous_keywords, log_content):
                score += _
        return score/sum * 100 if sum > 0 else 0.0
    
    @staticmethod
    def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        """计算两个向量的余弦相似度"""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        vec1_np = np.array(vec1)
        vec2_np = np.array(vec2)
        norm1 = np.linalg.norm(vec1_np)
        norm2 = np.linalg.norm(vec2_np)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        similarity = np.dot(vec1_np, vec2_np) / (norm1 * norm2)
        return max(0.0, similarity) * 100  # 归一化到0-100分
    
    @staticmethod
    def classify_query_intent(query: str) -> str:
        """识别query意图类型"""
        query_lower = query.lower()
        
        # 精确检索特征模式列表
        precise_patterns = [
            r'\d+\.\d+\.\d+\.\d+',            # IP地址
            r'0x[0-9a-fA-F]+',              # 十六进制错误码
            r'[A-Z]+-\d+',                  # 错误码格式如ERR-123
            r'错误码\s*\d+',                 # 错误码XXX格式
            r'端口\s*\d+',                   # 端口XXX格式
            r'\d{3,}',                      # 3位以上数字（端口号、错误码等）
            r'([a-zA-Z0-9_-]+)\.[a-zA-Z]{2,}',  # 域名
        ]
        
        # 特定类型问题关键词 - 避免与异常排查关键词重叠，只保留明确的问题类型关键词
        specific_type_keywords = {
            "oom": ["内存溢出", "oom", "out of memory", "内存不足", "内存泄漏"],
            "timeout": ["超时", "timeout", "time out", "连接超时", "请求超时", "read timeout", "write timeout"],
            "crash": ["崩溃", "crash", "宕机", "挂了", "退出", "重启", "core dump", "段错误", "segment fault"],
            "network": ["网络", "连接失败", "断开", "丢包", "延迟高", "ping不通", "端口不通", "网络抖动", "丢包率高"],
            "performance": ["cpu高", "cpu使用率", "内存高", "内存使用率", "负载高", "load高", "io高", "磁盘慢", "响应慢"],
            "resource": ["磁盘满", "磁盘不足", "空间不足", "inode满", "文件句柄", "端口耗尽", "资源不足", "fd不够"],
            "disk": ["磁盘坏道", "io错误", "磁盘只读", "挂载失败", "raid故障", "磁盘告警"],
            "config": ["配置错误", "参数不对", "配置不生效", "配置加载失败", "配置文件错误"],
            "service": ["进程不存在", "服务起不来", "启动失败", "停止失败", "状态异常"]
        }
        
        # 异常排查类关键词
        anomaly_keywords = [
            "分析", "排查", "看看", "检查", "有没有问题", "正常",
            "异常", "错误", "故障", "问题", "帮忙看", "帮我看看",
            "什么原因", "为啥", "怎么回事", "原因是什么", "为什么"
        ]
        
        # 决策逻辑：精确检索 > 特定问题 > 异常排查
        # 1. 先判断是否是精确检索（包含具体特征）
        for pattern in precise_patterns:
            if re.search(pattern, query):
                return QueryIntentEnum.PRECISE_SEARCH
        
        # 2. 再判断是否是特定问题
        for type_, keywords in specific_type_keywords.items():
            for kw in keywords:
                if kw in query_lower:
                    return QueryIntentEnum.SPECIFIC_TYPE
        
        # 3. 最后判断是否是异常排查
        for kw in anomaly_keywords:
            if kw in query_lower:
                return QueryIntentEnum.ANOMALY_DETECTION
        
        # 4. 兜底为精确检索
        return QueryIntentEnum.PRECISE_SEARCH
    


    @staticmethod
    async def handle_single_log_file(
        file_path: str, 
        max_anomaly_log_count: int, 
        keyword_vectors: list[list[float]],
        query_word_vectors: list[list[float]],
        time_start: str, 
        time_end: str,
        query_vector: list[float],
        intent: str
    ) -> tuple[list[LogModel], list[LogModel]]:
        """处理单个日志文件的逻辑：直接计算embedding相似度和关键字匹配"""
        # 解析日志文件
        log_models: list[LogModel] = await LogParser.parse_log_file(file_path=file_path, need_split_by_regex=True, time_start=time_start, time_end=time_end)
        
        if len(log_models) == 0:
            return log_models, []
        
        # 第一步：先计算所有日志的整行语义相似度，提前剪枝低相关日志
        log_contents = [log.content for log in log_models]
        logger.info(f"原始日志内容向量化，共{len(log_contents)}条")
        content_vectors = await Embedding.vectorize_embedding(log_contents)
        
        # 计算语义相似度，初步筛选出>10分的高相关候选日志（剪枝过滤70%+低相关日志）
        candidate_items = []
        for log_model, content_vector in zip(log_models, content_vectors):
            semantic_similarity = 0.0
            if content_vector is not None:
                semantic_similarity = LogDetectionBasedOnEmbeddingWorker.cosine_similarity(
                    content_vector, query_vector
                )
            # 语义分本身已经超过20分，或者加上异常分可能超过20分的，才进入下一轮
            if semantic_similarity > 10:  # 留足够余量，避免误删
                candidate_items.append({
                    "log_model": log_model,
                    "content_vector": content_vector,
                    "semantic_similarity": semantic_similarity
                })
        
        # 没有任何候选，直接返回
        if not candidate_items:
            return log_models, []
        
        # 第二步：每行计算词相关性，取TopN核心词，仅向量化核心词
        config = Config().get_config()
        TOP_WORDS_PER_LINE = config.top_core_words_per_line
        all_words_set = set()
        log_words_list = []
        
        for item in candidate_items:
            content = item["log_model"].content
            line_words = list(jieba.cut(content))
            word_with_score = []
            
            # 计算每个词和当前行的相关性得分：越长越靠前的词得分越高
            for word in line_words:
                word = word.strip()
                if not word:
                    continue
                # 长度权重：词越长越可能是核心词
                len_score = len(word) * 3
                # 位置权重：日志核心信息一般在前，越靠前权重越高
                pos = content.find(word)
                pos_score = max(0, 100 - pos) / 2 if pos != -1 else 0
                total_score = len_score + pos_score
                word_with_score.append((total_score, word))
            
            # 按得分倒序排序，取TopN核心词
            word_with_score.sort(reverse=True)
            core_words = [word for score, word in word_with_score[:TOP_WORDS_PER_LINE]]
            
            log_words_list.append(core_words)
            all_words_set.update(core_words)
        
        # 只向量化候选日志的唯一词
        logger.info("所有唯一词向量化开始")
        word_vector_dict = {}
        if all_words_set:
            all_words = list(all_words_set)
            all_word_vectors = await Embedding.vectorize_embedding(all_words)
            for word, vec in zip(all_words, all_word_vectors):
                if vec is not None:
                    word_vector_dict[word] = vec
        
        # 第三步：只对候选日志计算多维度评分
        candidate_unnormal_log_models: list[LogModel] = []
        for item, log_words in zip(candidate_items, log_words_list):
            log_model = item["log_model"]
            content_vector = item["content_vector"]
            semantic_similarity = item["semantic_similarity"]
            
            # 2. 计算关键字相似度（使用预计算的词向量字典）
            keyword_similarity = LogDetectionBasedOnEmbeddingWorker.cal_keyword_similarity(
                log_words, word_vector_dict, keyword_vectors, query_word_vectors
            )
            
            # 3. 计算情感分数
            sentiment_score = await LogDetectionBasedOnEmbeddingWorker.cal_sentiment_score(
                log_model.log_type, log_model.content
            )
            
            # 意图识别的动态权重调整
            if intent == QueryIntentEnum.PRECISE_SEARCH:
                # 精确检索：语义相似度权重最高
                final_score = semantic_similarity * 0.6 + keyword_similarity * 0.3 + sentiment_score * 0.1
            elif intent == QueryIntentEnum.ANOMALY_DETECTION:
                # 异常排查：异常分数权重最高
                final_score = sentiment_score * 0.5 + keyword_similarity * 0.3 + semantic_similarity * 0.2
            else:  # specific_type
                # 特定类型：语义相似度和异常分数权重相当
                final_score = semantic_similarity * 0.5 + sentiment_score * 0.35 + keyword_similarity * 0.15
            
            # 过滤低分日志
            if final_score >= 10:  # 最低阈值40分（从20分提高，减少误报）
                log_model.anomaly_score = final_score
                candidate_unnormal_log_models.append(log_model)
        
        # 排序并返回Top N
        candidate_unnormal_log_models = sorted(
            candidate_unnormal_log_models, key=lambda x: x.anomaly_score, reverse=True)[:max_anomaly_log_count]
        
        return log_models, candidate_unnormal_log_models
    
    @staticmethod
    async def run(task_id: str) -> None:
        """日志检测服务"""
        try:
            task_entity = await TaskManager.get_task_by_id(task_id)
            if task_entity is None:
                await TaskManager.update_task_by_id(task_id, {"status": TaskStatusEnum.FAILED.value})
                raise ValueError(f"任务 {task_id} 不存在")
            
            # 解析任务参数
            task_related_params_js = json.loads(
                task_entity.task_related_params)
            if "time_start" in task_related_params_js and task_related_params_js["time_start"]:
                task_related_params_js["time_start"] = datetime.strptime(task_related_params_js["time_start"],
                                                                         '%Y-%m-%d %H:%M')
            else:
                task_related_params_js["time_start"] = None
            if "time_end" in task_related_params_js and task_related_params_js["time_end"]:
                task_related_params_js["time_end"] = datetime.strptime(task_related_params_js["time_end"],
                                                                       '%Y-%m-%d %H:%M')
            else:
                task_related_params_js["time_end"] = None
            
            task_related_params_model = TaskRelatedParamsModel(
                **task_related_params_js)
            
            # 获取任务参数
            query = task_related_params_model.query
            file_path_list = task_related_params_model.file_path_list
            max_anomaly_log_count = task_related_params_model.max_anomaly_log_count
            anomaly_keywords: list[str] = task_related_params_model.anomaly_keywords
            time_start = task_related_params_model.time_start
            time_end = task_related_params_model.time_end
            
            # 连接测试：验证Embedding配置
            await Embedding.test_connection()
            
            # 前置处理：query向量化、意图识别和关键词向量化（只执行一次）
            logger.info(f"[任务准备] 开始处理query: {query}")
            query_vectors = await Embedding.vectorize_embedding([query])
            query_vector = query_vectors[0]
            intent = LogDetectionBasedOnEmbeddingWorker.classify_query_intent(query)
            logger.info(f"[任务准备] query意图识别结果: {intent}")
            
            # 对query分词并向量化
            query_words = list(jieba.cut(query))
            query_word_vectors = []
            if query_words:
                query_word_vectors = await Embedding.vectorize_embedding(query_words)
                query_word_vectors = [vec for vec in query_word_vectors if vec is not None]
            
            # 对关键词向量化
            keyword_vectors = []
            if anomaly_keywords:
                keyword_vectors = await Embedding.vectorize_embedding(anomaly_keywords)
                keyword_vectors = [vec for vec in keyword_vectors if vec is not None]
            logger.info(f"[任务准备] 关键词向量化完成: {len(keyword_vectors)}个关键词向量")
            
            # 准备工作
            log_models = []
            candidate_unnormal_log_models: list[LogModel] = []
            file_path_list = await BaseWorker.get_files_from_file_path_list(file_path_list)
            total_files = len(file_path_list)
            processed_files = 0
            
            # 更新任务进度为5%
            progress = 5.0
            logger.info(f"[进度更新] task_id={task_id}, total={progress:.1f}%")
            await TaskManager.update_task_by_id(task_id, {"completion_precent": progress})
            
            # 批量处理文件
            batch_size = Config().get_config().embedding_worker_batch_size
            for i in range(0, len(file_path_list), batch_size):
                batch_file_path_list = file_path_list[i:i + batch_size]
                
                # 异步批量处理
                handle_tasks = []
                for file_path in batch_file_path_list:
                    handle_tasks.append(LogDetectionBasedOnEmbeddingWorker.handle_single_log_file(
                    file_path, 
                    max_anomaly_log_count, 
                    keyword_vectors,
                    query_word_vectors,
                    time_start, 
                    time_end,
                    query_vector,
                    intent
                ))
                
                batch_results = await asyncio.gather(*handle_tasks)
                
                # 合并结果
                for log_model_list, candidate_unnormal_log_model_list in batch_results:
                    log_models.extend(log_model_list)
                    candidate_unnormal_log_models.extend(candidate_unnormal_log_model_list)
                
                # 更新进度
                processed_files += len(batch_file_path_list)
                progress = 5.0 + (processed_files / total_files) * 90.0
                logger.info(f"[进度更新] task_id={task_id}, total={progress:.1f}%")
                await TaskManager.update_task_by_id(task_id, {"completion_precent": min(progress, 95.0)})
            
            # 最终处理：全局排序
            candidate_unnormal_log_models.sort(
                key=lambda x: x.anomaly_score, reverse=True)
            candidate_unnormal_log_models = candidate_unnormal_log_models[:max_anomaly_log_count]
            await TaskManager.update_task_by_id(task_id, {"completion_precent": 97.5})
            
            enable_deduplication = task_related_params_model.enable_deduplication
            deduplication_threshold = task_related_params_model.deduplication_threshold
            await LogDetectionBasedOnEmbeddingWorker.add_log_parse_results(
                candidate_unnormal_log_models, log_models, task_id,
                enable_deduplication=enable_deduplication,
                deduplication_threshold=deduplication_threshold
            )
            
            # 任务完成
            progress = 100.0
            await TaskManager.update_task_by_id(task_id, {"completion_precent": progress, "status": TaskStatusEnum.SUCCESSFUL_PENDING_REMOVE.value})
            logger.info(f"[进度更新] task_id={task_id}, total=100.0%")
            logger.info(f"[任务完成] 共处理日志{len(log_models)}条, 检出异常{len(candidate_unnormal_log_models)}条")
        except ValueError as e:
            await TaskManager.update_task_by_id(task_id, {"status": TaskStatusEnum.FAILED.value})
            logger.exception(f"[任务失败] task_id={task_id}, 错误信息: {str(e)}")
            raise e
        except Exception as e:
            await TaskManager.update_task_by_id(task_id, {"status": TaskStatusEnum.FAILED_PENDING_REMOVE.value})
            logger.exception(f"[任务失败] task_id={task_id}, 错误信息: {str(e)}")
            raise e
