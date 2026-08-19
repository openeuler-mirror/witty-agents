import asyncio
import math
import json
import logging
from faiss import IndexFlatL2
import numpy as np
import jieba
import re
from datetime import datetime

from src.worker.base import BaseWorker
from src.service.embedding import Embedding
from src.service.cluster import ClusterService
from src.parser.parser import LogParser
from src.parser.log_feature_loader import log_feature_class_mapping
from src.sqlite.manager.task import TaskManager
from src.schemas.task import TaskRelatedParamsModel
from src.schemas.cluster import ClusterModel
from src.enum.log import LogTypeEnum
from src.enum.task import TaskTypeEnum, TaskStatusEnum
from src.schemas.log import LogModel

logger = logging.getLogger(__name__)
class LogDetectionBasedOnClusteringWorker(BaseWorker):
    name = TaskTypeEnum.LOG_DETECTION_BASE_ON_CLUSTERING.value

    @staticmethod
    async def create_index(datas_embedding: list[list[float]]) -> IndexFlatL2:
        # 构建索引，这里我们选用暴力检索的方法FlatL2为例，L2代表构建的index采用的相似度度量方法为L2范数，即欧氏距离
        # 这里必须传入一个向量的维度，创建一个空的索引
        index = IndexFlatL2(len(datas_embedding[0]))
        index.add(np.array(datas_embedding, dtype='float32'))   # 把向量数据加入索引
        return index

    @staticmethod
    async def data_recall(faiss_index: IndexFlatL2, query_embedding: list[float], top_k: int) -> tuple[list[float], list[int]]:
        Distance, Index = faiss_index.search(
            np.array([query_embedding], dtype='float32'), top_k)
        return Distance.tolist(), Index.tolist()

    @staticmethod
    async def merge_log_templates(log_models: list[LogModel], similarity_threshold: float = 0.8):
        """合并相似的日志模板"""
        # 这里实现合并相似日志模板的具体逻辑
        log_template_embeddings = [
            log_model.template_vector for log_model in log_models]
        faiss_index = await LogDetectionBasedOnClusteringWorker.create_index(log_template_embeddings)
        top_k = int(math.log10(len(log_models)))
        top_k = max(top_k, 2)
        for i, log_model in enumerate(log_models):
            Distance, Index = await LogDetectionBasedOnClusteringWorker.data_recall(faiss_index, log_model.template_vector, top_k=top_k)
            for ind in Index[0]:
                id1 = i
                while log_models[id1].parent_id is not None:
                    id1 = log_models[id1].parent_id
                id2 = ind
                while log_models[id2].parent_id is not None:
                    id2 = log_models[id2].parent_id
                if id1 != id2:
                    if log_models[id1].rank < log_models[id2].rank:
                        log_models[id2].parent_id = id1
                        log_models[id1].sz += log_models[id2].sz
                    elif log_models[id1].rank > log_models[id2].rank:
                        log_models[id1].parent_id = id2
                        log_models[id2].sz += log_models[id1].sz
                    else:
                        log_models[id2].parent_id = id1
                        log_models[id1].rank += 1
                        log_models[id1].sz += log_models[id2].sz

    @staticmethod
    async def cal_cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        """计算余弦相似度"""
        vec1_np = np.array(vec1)
        vec2_np = np.array(vec2)
        if np.linalg.norm(vec1_np) == 0 or np.linalg.norm(vec2_np) == 0:
            return 0.0
        cosine_similarity = np.dot(
            vec1_np, vec2_np) / (np.linalg.norm(vec1_np) * np.linalg.norm(vec2_np))
        # 百分制
        return (cosine_similarity + 1) / 2 * 100

    @staticmethod
    async def cal_keyword_similarity(str1: str, keywords: list[str]) -> float:
        """计算jaccard相似度"""
        words = list(jieba.cut(str1))
        new_keywords = []
        for keyword in keywords:
            new_keywords.extend(jieba.cut(keyword)) 
        keywords = set(new_keywords)
        words_set = set(words)
        intersection = words_set & keywords
        return (len(intersection) / len(keywords) if len(keywords) > 0 else 0.0)*100

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
    async def handle_single_log_file(file_path: str, max_anomaly_log_count: int, time_start: str, time_end: str) -> list[LogModel]:
        """处理单个日志文件的逻辑"""
        # 这里实现处理单个日志文件的具体逻辑
        log_models: list[LogModel] = await LogParser.parse_log_file(file_path=file_path, need_split_by_regex=True, time_start=time_start, time_end=time_end)
        if len(log_models) == 0:
            return log_models, []
        await LogParser.get_log_templates(log_models=log_models, need_embedding=True)
        await LogDetectionBasedOnClusteringWorker.merge_log_templates(log_models=log_models)
        log_models_after_merge = [
            log_model for log_model in log_models if log_model.parent_id is None]
        cluster_models_DBSCAN: list[ClusterModel] = await ClusterService.DBSCAN(log_models=log_models_after_merge)
        outlier_logs = []
        normal_log_template_vector = []
        for cluster_model in cluster_models_DBSCAN:
            if cluster_model.is_outlier:
                outlier_logs += cluster_model.log_models
            else:
                normal_log_template_vector += [
                    log_model.template_vector for log_model in cluster_model.log_models]
        if normal_log_template_vector:
            normal_log_template_center = np.mean(
                normal_log_template_vector, axis=0).tolist()
        else:
            normal_log_template_center = None
        cluster_models_KMeans = await ClusterService.KMeans(outlier_logs)
        # 通过计算与正常日志模板的相似度（normal_log_template_center），增加异常日志模板的候选，每个文件选2*max_anomaly_log_count个候选
        cluster_models_KMeans_dis_to_normal: list[tuple[ClusterModel, float]] = [
        ]
        for cluster_model in cluster_models_KMeans:
            if normal_log_template_center is not None:
                distance_to_normal = np.linalg.norm(
                    np.array(cluster_model.cluster_center) - np.array(normal_log_template_center))
            else:
                distance_to_normal = 0
            cluster_models_KMeans_dis_to_normal.append(
                (cluster_model, distance_to_normal))

        cluster_models_KMeans_dis_to_normal.sort(
            key=lambda x: x[1], reverse=True)
        candidate_unnormal_log_models: list[LogModel] = []
        for i in range(min(2*max_anomaly_log_count, len(cluster_models_KMeans_dis_to_normal))):
            candidate_unnormal_log_models += cluster_models_KMeans_dis_to_normal[i][0].log_models
        candidate_unnormal_log_model_id_set = set(
            [log_model.id for log_model in candidate_unnormal_log_models])
        tmp_log_cnt = 0
        for _, log_model in enumerate(log_models):
            id = _
            while log_models[id].parent_id is not None:
                id = log_models[id].parent_id
            if id in candidate_unnormal_log_model_id_set:
                log_model.is_anomaly = True
                candidate_unnormal_log_models.append(log_model)
                tmp_log_cnt += 1
                if tmp_log_cnt >= 2*max_anomaly_log_count:
                    break
        return log_models, candidate_unnormal_log_models

    @staticmethod
    async def run(task_id: str) -> None:
        try:
            """日志检测服务"""
            task_entity = await TaskManager.get_task_by_id(task_id)
            if task_entity is None:
                await TaskManager.update_task_by_id(task_id, {"status": TaskStatusEnum.FAILED.value})
                raise ValueError(f"任务 {task_id} 不存在")
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
                
            query = task_related_params_model.query
            query_embedding = await Embedding.get_embedding(query)
            query_embedding = query_embedding[0]
            file_path_list = task_related_params_model.file_path_list
            max_anomaly_log_count = task_related_params_model.max_anomaly_log_count
            anomaly_keywords: list[str] = task_related_params_model.anomaly_keywords
            time_start = task_related_params_model.time_start
            time_end = task_related_params_model.time_end
            # 异常日志候选列表
            log_models = []
            candidate_unnormal_log_models: list[LogModel] = []
            batch_size = 8
            file_path_list = await BaseWorker.get_files_from_file_path_list(file_path_list)
            total_files = len(file_path_list)
            processed_files = 0
            # 更新任务进度为0%
            progress = 0.0
            logger.info(f"[进度更新] task_id={task_id}, total={progress:.1f}%")
            await TaskManager.update_task_by_id(task_id, {"completion_precent": progress})
            for i in range(0, len(file_path_list), batch_size):
                batch_file_path_list = file_path_list[i:i + batch_size]
                handle_tasks = []
                for file_path in batch_file_path_list:
                    handle_tasks.append(LogDetectionBasedOnClusteringWorker.handle_single_log_file(
                        file_path=file_path, max_anomaly_log_count=max_anomaly_log_count, time_start=time_start, time_end=time_end))
                handle_results = await asyncio.gather(*handle_tasks)
                for log_model_list, candidate_unnormal_log_model_list in handle_results:
                    log_models.extend(log_model_list)
                    candidate_unnormal_log_models.extend(
                        candidate_unnormal_log_model_list)
                processed_files += len(batch_file_path_list)
                # 更新任务进度
                progress = (processed_files / total_files) * 95
                logger.info(f"[进度更新] task_id={task_id}, total={progress:.1f}%")
                await TaskManager.update_task_by_id(task_id, {"completion_precent": min(progress, 95)})
            # 通过query embedding（余弦距离 30%） 、 异常关键词（50%）和情感模型（20%）来对候选的异常日志进行排序，选出最终的异常日志列表返回
            for log_model in candidate_unnormal_log_models:
                cosine_similarity = await LogDetectionBasedOnClusteringWorker.cal_cosine_similarity(log_model.template_vector, query_embedding)
                keyword_similarity = await LogDetectionBasedOnClusteringWorker.cal_keyword_similarity(log_model.content, anomaly_keywords)
                sentiment_score = await LogDetectionBasedOnClusteringWorker.cal_sentiment_score(log_model.log_type, log_model.content)
                final_score = cosine_similarity * 0.3 + \
                    keyword_similarity * 0.5 + \
                    sentiment_score * 0.2
                log_model.anomaly_score = final_score
            candidate_unnormal_log_models.sort(
                key=lambda x: x.anomaly_score, reverse=True)
            candidate_unnormal_log_models = candidate_unnormal_log_models[:max_anomaly_log_count]
            enable_deduplication = task_related_params_model.enable_deduplication
            deduplication_threshold = task_related_params_model.deduplication_threshold
            await LogDetectionBasedOnClusteringWorker.add_log_parse_results(
                candidate_unnormal_log_models, log_models, task_id,
                enable_deduplication=enable_deduplication,
                deduplication_threshold=deduplication_threshold
            )

            # 任务完成，更新进度为100%
            progress = 100.0
            logger.info(f"[进度更新] task_id={task_id}, total={progress:.1f}%")
            await TaskManager.update_task_by_id(task_id, {"completion_precent": progress, "status": TaskStatusEnum.SUCCESSFUL_PENDING_REMOVE.value})
        except Exception as e:
            await TaskManager.update_task_by_id(task_id, {"status": TaskStatusEnum.FAILED_PENDING_REMOVE.value})
            raise e
