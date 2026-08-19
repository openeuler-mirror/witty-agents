import asyncio
import pytest
import uuid
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.worker.base import BaseWorker
from src.worker.log_detection_base_on_keywords import LogDetectionBasedOnKeywordsWorker
from src.worker.log_detection_base_on_clustering import (
    LogDetectionBasedOnClusteringWorker,
)
from src.worker.log_detection_base_on_llm import LogDetectionBasedOnLLMWorker
from src.worker.log_detection_base_on_embedding import LogDetectionBasedOnEmbeddingWorker
from src.service.task import TaskService
from src.parser.parser import LogParser
from src.parser.log_feature_loader import log_feature_class_mapping, BaseLogFeature
from src.sqlite.manager.task import TaskManager
from src.sqlite.manager.log_parse_result import LogParseResultManager
from src.schemas.task import TaskModel, TaskRelatedParamsModel
from src.schemas.log import LogModel
from src.enum.task import TaskTypeEnum, TaskStatusEnum
from src.enum.log import LogTypeEnum, LogLevelEnum
from src.enum.query_intent import QueryIntentEnum
from src.service.cluster import ClusterService
from src.service.llm import LLMService
from src.config.config import Config
from src.sqlite.sqlite import AsyncSQLiteSingleton


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """初始化数据库"""
    AsyncSQLiteSingleton()
    yield


@pytest.fixture
def temp_log_file():
    """创建临时日志文件"""
    test_file = Path("/tmp/test_log_detection.log")
    test_file.write_text(
        "2024-01-01 10:00:00 ERROR: device disconnected\n"
        "2024-01-01 10:01:00 INFO: device connected\n"
        "2024-01-01 10:02:00 ERROR: network failed\n"
    )
    yield str(test_file)
    test_file.unlink()


@pytest.fixture
def temp_directory_with_logs():
    """创建临时目录和日志文件"""
    test_dir = Path("/tmp/test_logs")
    test_dir.mkdir(exist_ok=True)

    (test_dir / "file1.log").write_text(
        "2024-01-01 10:00:00 ERROR: device disconnected\n"
    )
    (test_dir / "file2.log").write_text("2024-01-01 10:01:00 ERROR: network failed\n")

    yield str(test_dir)

    for f in test_dir.iterdir():
        f.unlink()
    test_dir.rmdir()


@pytest.fixture
async def test_task():
    """创建测试任务"""
    task_id = str(uuid.uuid4())
    params = {
        "query": "network error",
        "file_path_list": ["/tmp/test.log"],
        "max_anomaly_log_count": 100,
        "anomaly_keywords": ["error", "failed"],
    }

    task_model = TaskModel(
        task_id=task_id,
        task_name="test_task",
        task_type=TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS.value,
        completion_precent=0.0,
        status=TaskStatusEnum.PENDING.value,
        task_related_params=json.dumps(params),
    )

    await TaskManager.create_task(task_model)
    yield task_id
    await TaskManager.delete_task_by_id(task_id)


class TestBaseWorker:
    """BaseWorker 测试类"""

    @pytest.mark.asyncio
    async def test_find_worker_class_exists(self):
        """测试查找存在的worker类"""
        worker_class = BaseWorker.find_worker_class(
            TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS.value
        )
        assert worker_class is not None
        assert worker_class.name == TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS.value

    @pytest.mark.asyncio
    async def test_find_worker_class_not_exists(self):
        """测试查找不存在的worker类"""
        worker_class = BaseWorker.find_worker_class("non_existent_worker")
        assert worker_class is None

    @pytest.mark.asyncio
    async def test_find_all_worker_classes(self):
        """测试查找所有worker类"""
        subclasses = BaseWorker.__subclasses__()
        worker_names = [subclass.name for subclass in subclasses]
        assert TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS.value in worker_names
        assert TaskTypeEnum.LOG_DETECTION_BASE_ON_CLUSTERING.value in worker_names
        assert TaskTypeEnum.LOG_DETECTION_BASE_ON_LLM.value in worker_names
        assert TaskTypeEnum.LOG_DETECTION_BASE_ON_EMBEDDING.value in worker_names

    @pytest.mark.asyncio
    async def test_get_worker_name(self, test_task):
        """测试获取worker名称"""
        worker_name = await BaseWorker.get_worker_name(test_task)
        assert worker_name == TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS.value

    @pytest.mark.asyncio
    async def test_get_worker_name_not_exists(self):
        """测试获取不存在任务的worker名称"""
        non_existent_id = str(uuid.uuid4())
        with pytest.raises(ValueError):
            await BaseWorker.get_worker_name(non_existent_id)

    @pytest.mark.asyncio
    async def test_get_files_from_file_path_list_single_file(self, temp_log_file):
        """测试处理单个文件路径"""
        file_paths = await BaseWorker.get_files_from_file_path_list([temp_log_file])
        assert len(file_paths) == 1
        assert temp_log_file in file_paths

    @pytest.mark.asyncio
    async def test_get_files_from_file_path_list_directory(
        self, temp_directory_with_logs
    ):
        """测试处理目录路径"""
        file_paths = await BaseWorker.get_files_from_file_path_list(
            [temp_directory_with_logs]
        )
        assert len(file_paths) == 2

    @pytest.mark.asyncio
    async def test_get_files_from_file_path_list_empty(self):
        """测试处理空路径列表"""
        file_paths = await BaseWorker.get_files_from_file_path_list([])
        assert len(file_paths) == 0

    @pytest.mark.asyncio
    async def test_get_files_from_file_path_list_mixed(
        self, temp_log_file, temp_directory_with_logs
    ):
        """测试处理混合路径"""
        file_paths = await BaseWorker.get_files_from_file_path_list(
            [temp_log_file, temp_directory_with_logs]
        )
        assert len(file_paths) == 3

    @pytest.mark.asyncio
    async def test_get_files_from_file_path_list_non_existent(self):
        """测试处理不存在的文件路径"""
        file_paths = await BaseWorker.get_files_from_file_path_list(
            ["/non/existent/path.log"]
        )
        assert len(file_paths) == 0

    @pytest.mark.asyncio
    async def test_add_log_parse_results(self, test_task):
        """测试添加日志解析结果"""
        log_models = [
            LogModel(
                file_path="/tmp/test.log",
                content="error: device disconnected",
                offset=0,
                is_anomalous=False,
                anomaly_score=85.0,
                anomaly_reason="network disconnected",
            ),
            LogModel(
                file_path="/tmp/test.log",
                content="info: device connected",
                offset=1,
                is_anomalous=False,
                anomaly_score=0.0,
            ),
        ]

        anomaly_log_models = [log_models[0]]

        await BaseWorker.add_log_parse_results(
            anomaly_log_models, log_models, test_task
        )

        results = await LogParseResultManager.get_log_parse_results_by_task_id(
            test_task
        )
        assert len(results) == 2


class TestLogDetectionBasedOnKeywordsWorker:
    """LogDetectionBasedOnKeywordsWorker 测试类"""

    @pytest.mark.asyncio
    async def test_cal_keyword_similarity_full_match(self):
        """测试计算关键词完全匹配的相似度"""
        text = "error disconnected network"
        keywords = ["error", "disconnected", "network"]
        similarity = await LogDetectionBasedOnKeywordsWorker.cal_keyword_similarity(
            text, keywords
        )
        assert similarity == 100.0

    @pytest.mark.asyncio
    async def test_cal_keyword_similarity_partial_match(self):
        """测试计算关键词部分匹配的相似度"""
        text = "error network"
        keywords = ["error", "disconnected", "network"]
        similarity = await LogDetectionBasedOnKeywordsWorker.cal_keyword_similarity(
            text, keywords
        )
        assert 0 < similarity < 100.0

    @pytest.mark.asyncio
    async def test_cal_keyword_similarity_no_match(self):
        """测试计算关键词不匹配的相似度"""
        text = "success completed"
        keywords = ["error", "disconnected", "failed"]
        similarity = await LogDetectionBasedOnKeywordsWorker.cal_keyword_similarity(
            text, keywords
        )
        assert similarity == 0.0

    @pytest.mark.asyncio
    async def test_cal_keyword_similarity_empty_keywords(self):
        """测试计算关键词为空列表的相似度"""
        text = "error network"
        keywords = []
        similarity = await LogDetectionBasedOnKeywordsWorker.cal_keyword_similarity(
            text, keywords
        )
        assert similarity == 0.0

    @pytest.mark.asyncio
    async def test_cal_keyword_similarity_empty_text(self):
        """测试计算空字符串与关键词的相似度"""
        text = ""
        keywords = ["error", "network"]
        similarity = await LogDetectionBasedOnKeywordsWorker.cal_keyword_similarity(
            text, keywords
        )
        assert similarity == 0.0

    @pytest.mark.asyncio
    async def test_cal_keyword_similarity_chinese(self):
        """测试计算包含中文关键词的相似度"""
        text = "网络 断开 连接"
        keywords = ["网络", "断开", "连接"]
        similarity = await LogDetectionBasedOnKeywordsWorker.cal_keyword_similarity(
            text, keywords
        )
        assert similarity == 100.0

    @pytest.mark.asyncio
    async def test_cal_sentiment_score_with_anomaly_keywords(self):
        """测试计算包含异常关键词的日志情感分数"""
        log_type = LogTypeEnum.DMESG
        log_content = "error: device disconnected"
        score = await LogDetectionBasedOnKeywordsWorker.cal_sentiment_score(
            log_type, log_content
        )
        assert 0 <= score <= 100.0

    @pytest.mark.asyncio
    async def test_cal_sentiment_score_without_anomaly_keywords(self):
        """测试计算不包含异常关键词的日志情感分数"""
        log_type = LogTypeEnum.DMESG
        log_content = "info: device connected successfully"
        score = await LogDetectionBasedOnKeywordsWorker.cal_sentiment_score(
            log_type, log_content
        )
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_cal_sentiment_score_unknown_log_type(self):
        """测试计算未知日志类型的情感分数"""
        log_type = None
        log_content = "error: something failed"
        score = await LogDetectionBasedOnKeywordsWorker.cal_sentiment_score(
            log_type, log_content
        )
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_cal_sentiment_score_empty_log_type(self):
        """测试计算日志类型为空的情感分数"""
        log_content = "error: something failed"
        score = await LogDetectionBasedOnKeywordsWorker.cal_sentiment_score(
            None, log_content
        )
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_cal_sentiment_score_python_log(self):
        """测试计算Python日志类型的情感分数"""
        log_type = LogTypeEnum.PYTHON
        log_content = "ERROR: Connection refused"
        score = await LogDetectionBasedOnKeywordsWorker.cal_sentiment_score(
            log_type, log_content
        )
        assert 0 <= score <= 100.0


class TestLogDetectionBasedOnClusteringWorker:
    """LogDetectionBasedOnClusteringWorker 测试类"""

    @pytest.mark.asyncio
    async def test_cal_keyword_similarity(self):
        """测试关键词相似度计算"""
        text = "error disconnected network"
        keywords = ["error", "disconnected", "network"]
        similarity = await LogDetectionBasedOnClusteringWorker.cal_keyword_similarity(
            text, keywords
        )
        assert similarity == 100.0

    @pytest.mark.asyncio
    async def test_cal_sentiment_score(self):
        """测试情感分数计算"""
        log_type = LogTypeEnum.DMESG
        log_content = "error: device disconnected"
        score = await LogDetectionBasedOnClusteringWorker.cal_sentiment_score(
            log_type, log_content
        )
        assert 0 <= score <= 100.0

    @pytest.mark.asyncio
    async def test_cal_cosine_similarity_full_match(self):
        """测试计算完全相似的向量"""
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [1.0, 2.0, 3.0]
        similarity = await LogDetectionBasedOnClusteringWorker.cal_cosine_similarity(
            vec1, vec2
        )
        assert similarity == 100.0

    @pytest.mark.asyncio
    async def test_cal_cosine_similarity_no_match(self):
        """测试计算完全不相似的向量"""
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]
        similarity = await LogDetectionBasedOnClusteringWorker.cal_cosine_similarity(
            vec1, vec2
        )
        assert similarity == 50.0

    @pytest.mark.asyncio
    async def test_cal_cosine_similarity_partial_match(self):
        """测试计算部分相似的向量"""
        vec1 = [1.0, 1.0, 0.0]
        vec2 = [1.0, 0.0, 0.0]
        similarity = await LogDetectionBasedOnClusteringWorker.cal_cosine_similarity(
            vec1, vec2
        )
        assert 0 < similarity < 100.0

    @pytest.mark.asyncio
    async def test_cal_cosine_similarity_zero_vector(self):
        """测试计算零向量相似度"""
        vec1 = [0.0, 0.0, 0.0]
        vec2 = [1.0, 2.0, 3.0]
        similarity = await LogDetectionBasedOnClusteringWorker.cal_cosine_similarity(
            vec1, vec2
        )
        assert similarity == 0.0

    @pytest.mark.asyncio
    async def test_cal_cosine_similarity_high_dimensional(self):
        """测试计算高维向量相似度"""
        vec1 = [1.0] * 100
        vec2 = [1.0] * 100
        similarity = await LogDetectionBasedOnClusteringWorker.cal_cosine_similarity(
            vec1, vec2
        )
        assert similarity == 100.0

    @pytest.mark.asyncio
    async def test_cal_cosine_similarity_negative_values(self):
        """测试计算包含负值的向量相似度"""
        vec1 = [1.0, -1.0, 0.0]
        vec2 = [1.0, 1.0, 0.0]
        similarity = await LogDetectionBasedOnClusteringWorker.cal_cosine_similarity(
            vec1, vec2
        )
        assert 0 <= similarity <= 100.0


class TestLogDetectionBasedOnEmbeddingWorker:
    """LogDetectionBasedOnEmbeddingWorker 测试类"""

    @pytest.mark.asyncio
    async def test_classify_query_intent_precise_search(self):
        """测试识别精确检索类查询"""
        # 包含具体错误码、IP、端口等特征
        queries = [
            "查找错误码500的日志",
            "192.168.1.100 登录失败",
            "端口8080 连接超时",
            "0x1234 错误",
            "用户ID 12345 异常"
        ]
        for query in queries:
            intent = LogDetectionBasedOnEmbeddingWorker.classify_query_intent(query)
            assert intent == QueryIntentEnum.PRECISE_SEARCH

    @pytest.mark.asyncio
    async def test_classify_query_intent_anomaly_detection(self):
        """测试识别异常排查类查询"""
        queries = [
            "看看有没有异常",
            "排查下系统问题",
            "帮忙分析下错误日志",
            "系统运行正常吗？",
            "为什么服务没了？"
        ]
        for query in queries:
            intent = LogDetectionBasedOnEmbeddingWorker.classify_query_intent(query)
            assert intent == QueryIntentEnum.ANOMALY_DETECTION

    @pytest.mark.asyncio
    async def test_classify_query_intent_specific_type(self):
        """测试识别特定类型问题查询"""
        queries = [
            "查找内存溢出的日志",
            "有没有超时相关的错误",
            "排查下网络问题",
            "看看有没有崩溃日志",
            "CPU高的原因是什么"
        ]
        for query in queries:
            intent = LogDetectionBasedOnEmbeddingWorker.classify_query_intent(query)
            assert intent == QueryIntentEnum.SPECIFIC_TYPE

    @pytest.mark.asyncio
    async def test_classify_query_intent_default(self):
        """测试无法识别的查询默认分类"""
        queries = [
            "查看日志",
            "最近的日志",
            "系统日志"
        ]
        for query in queries:
            intent = LogDetectionBasedOnEmbeddingWorker.classify_query_intent(query)
            assert intent == QueryIntentEnum.PRECISE_SEARCH

    @pytest.mark.asyncio
    async def test_cal_cosine_similarity_full_match(self):
        """测试完全匹配的余弦相似度"""
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [1.0, 2.0, 3.0]
        similarity = LogDetectionBasedOnEmbeddingWorker.cosine_similarity(vec1, vec2)
        assert similarity == 100.0

    @pytest.mark.asyncio
    async def test_cal_cosine_similarity_partial_match(self):
        """测试部分匹配的余弦相似度"""
        vec1 = [1.0, 1.0, 0.0]
        vec2 = [1.0, 0.0, 0.0]
        similarity = LogDetectionBasedOnEmbeddingWorker.cosine_similarity(vec1, vec2)
        assert 50 < similarity < 100

    @pytest.mark.asyncio
    async def test_cal_cosine_similarity_zero_vector(self):
        """测试零向量的相似度计算"""
        vec1 = [0.0, 0.0, 0.0]
        vec2 = [1.0, 2.0, 3.0]
        similarity = LogDetectionBasedOnEmbeddingWorker.cosine_similarity(vec1, vec2)
        assert similarity == 0.0

    @pytest.mark.asyncio
    async def test_cal_keyword_similarity(self):
        """测试关键词相似度计算"""
        import jieba
        log_words = list(jieba.cut("error network timeout"))
        word_vector_dict = {
            "error": [1.0, 0.0, 0.0],
            "network": [0.0, 1.0, 0.0],
            "timeout": [0.0, 0.0, 1.0]
        }
        keyword_vectors = [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]  # error, timeout
        query_word_vectors = []
        similarity = LogDetectionBasedOnEmbeddingWorker.cal_keyword_similarity(
            log_words, word_vector_dict, keyword_vectors, query_word_vectors
        )
        assert 0 < similarity <= 100.0

    @pytest.mark.asyncio
    async def test_cal_sentiment_score(self):
        """测试情感分数计算"""
        log_type = LogTypeEnum.PYTHON
        # 使用包含明确异常关键词的日志内容
        log_content = "ERROR: exception occurred, connection refused, failed to connect"
        score = await LogDetectionBasedOnEmbeddingWorker.cal_sentiment_score(log_type, log_content)
        assert 0 <= score <= 100.0




class TestLogFeatureLoader:
    """日志特征加载器测试类"""

    @pytest.mark.asyncio
    async def test_log_feature_mapping_complete(self):
        """测试所有日志类型都有对应的特征配置"""
        # 检查枚举中的类型是否都在映射中
        for log_type in LogTypeEnum:
            if log_type != LogTypeEnum.UNKNOWN:
                assert log_type in log_feature_class_mapping
                assert isinstance(log_feature_class_mapping[log_type], BaseLogFeature)

    @pytest.mark.asyncio
    async def test_log_feature_patterns_loaded(self):
        """测试日志特征正则表达式正确加载"""
        for log_type, feature in log_feature_class_mapping.items():
            assert hasattr(feature, 'keywords_regex_and_scores')
            assert hasattr(feature, 'mandatory')
            assert hasattr(feature, 'capture_patterns')
            assert isinstance(feature.keywords_regex_and_scores, dict)


class TestClusterService:
    """ClusterService 测试类"""

    @pytest.mark.asyncio
    async def test_single_DBSCAN(self):
        """测试单次DBSCAN聚类"""
        from src.schemas.cluster import ClusterModel

        clusters = [
            ClusterModel(
                cluster_center=[1.0, 2.0],
                log_models=[
                    LogModel(file_path="/tmp/test.log", content="test1", offset=0)
                ],
            ),
            ClusterModel(
                cluster_center=[1.1, 2.1],
                log_models=[
                    LogModel(file_path="/tmp/test.log", content="test2", offset=1)
                ],
            ),
        ]

        result = await ClusterService.single_DBSCAN(
            eps=0.5, min_samples=2, clusters=clusters
        )
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_single_DBSCAN_all_outliers(self):
        """测试所有点都是离群点的情况"""
        from src.schemas.cluster import ClusterModel

        clusters = [
            ClusterModel(
                cluster_center=[1.0, 2.0],
                log_models=[
                    LogModel(file_path="/tmp/test.log", content="test1", offset=0)
                ],
            ),
            ClusterModel(
                cluster_center=[10.0, 20.0],
                log_models=[
                    LogModel(file_path="/tmp/test.log", content="test2", offset=1)
                ],
            ),
        ]

        result = await ClusterService.single_DBSCAN(
            eps=0.1, min_samples=2, clusters=clusters
        )
        assert len(result) > 0
        outlier_count = sum(1 for c in result if c.is_outlier)
        assert outlier_count > 0

    @pytest.mark.asyncio
    async def test_single_DBSCAN_all_in_cluster(self):
        """测试所有点都在簇中的情况"""
        from src.schemas.cluster import ClusterModel

        clusters = [
            ClusterModel(
                cluster_center=[1.0, 2.0],
                log_models=[
                    LogModel(file_path="/tmp/test.log", content="test1", offset=0)
                ],
            ),
            ClusterModel(
                cluster_center=[1.1, 2.1],
                log_models=[
                    LogModel(file_path="/tmp/test.log", content="test2", offset=1)
                ],
            ),
            ClusterModel(
                cluster_center=[1.2, 2.2],
                log_models=[
                    LogModel(file_path="/tmp/test.log", content="test3", offset=2)
                ],
            ),
        ]

        result = await ClusterService.single_DBSCAN(
            eps=0.5, min_samples=1, clusters=clusters
        )
        assert len(result) > 0
        outlier_count = sum(1 for c in result if c.is_outlier)
        assert outlier_count == 0

    @pytest.mark.asyncio
    async def test_single_KMeans(self):
        """测试单次KMeans聚类"""
        from src.schemas.cluster import ClusterModel

        clusters = [
            ClusterModel(
                cluster_center=[1.0, 2.0],
                log_models=[
                    LogModel(file_path="/tmp/test.log", content="test1", offset=0)
                ],
            ),
            ClusterModel(
                cluster_center=[1.1, 2.1],
                log_models=[
                    LogModel(file_path="/tmp/test.log", content="test2", offset=1)
                ],
            ),
            ClusterModel(
                cluster_center=[1.2, 2.2],
                log_models=[
                    LogModel(file_path="/tmp/test.log", content="test3", offset=2)
                ],
            ),
        ]

        result = await ClusterService.single_KMeans(
            n_clusters=2, n_init=10, random_state=42, clusters=clusters
        )
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_single_KMeans_k_greater_than_clusters(self):
        """测试K值大于聚类数量的情况"""
        from src.schemas.cluster import ClusterModel

        clusters = [
            ClusterModel(
                cluster_center=[1.0, 2.0],
                log_models=[
                    LogModel(file_path="/tmp/test.log", content="test1", offset=0)
                ],
            ),
        ]

        result = await ClusterService.single_KMeans(
            n_clusters=5, n_init=10, random_state=42, clusters=clusters
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_single_KMeans_k_equals_1(self):
        """测试K值为1的情况"""
        from src.schemas.cluster import ClusterModel

        clusters = [
            ClusterModel(
                cluster_center=[1.0, 2.0],
                log_models=[
                    LogModel(file_path="/tmp/test.log", content="test1", offset=0)
                ],
            ),
            ClusterModel(
                cluster_center=[1.1, 2.1],
                log_models=[
                    LogModel(file_path="/tmp/test.log", content="test2", offset=1)
                ],
            ),
        ]

        result = await ClusterService.single_KMeans(
            n_clusters=1, n_init=10, random_state=42, clusters=clusters
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_single_KMeans_empty_clusters(self):
        """测试空聚类列表"""
        result = await ClusterService.single_KMeans(
            n_clusters=1, n_init=10, random_state=42, clusters=[]
        )
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_DBSCAN(self):
        """测试DBSCAN聚类服务"""
        log_models = [
            LogModel(
                file_path="/tmp/test.log",
                content="error: device disconnected",
                offset=0,
                template_vector=[0.1] * 768,
            ),
            LogModel(
                file_path="/tmp/test.log",
                content="error: network failed",
                offset=1,
                template_vector=[0.11] * 768,
            ),
        ]

        result = await ClusterService.DBSCAN(
            log_models=log_models, max_iterations=2, batch_size=8
        )
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_DBSCAN_empty_logs(self):
        """测试对空日志列表聚类"""
        log_models = []
        result = await ClusterService.DBSCAN(log_models=log_models)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_DBSCAN_large_dataset(self):
        """测试大规模数据集聚类"""
        log_models = [
            LogModel(
                file_path="/tmp/test.log",
                content=f"error: device {i}",
                offset=i,
                template_vector=[0.1 + i * 0.001] * 768,
            )
            for i in range(100)
        ]

        result = await ClusterService.DBSCAN(
            log_models=log_models, max_iterations=2, batch_size=8
        )
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_KMeans(self):
        """测试KMeans聚类服务"""
        log_models = [
            LogModel(
                file_path="/tmp/test.log",
                content="error: device disconnected",
                offset=0,
                template_vector=[0.1] * 768,
            ),
            LogModel(
                file_path="/tmp/test.log",
                content="error: network failed",
                offset=1,
                template_vector=[0.11] * 768,
            ),
        ]

        result = await ClusterService.KMeans(
            log_models=log_models, max_iterations=2, batch_size=8
        )
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_KMeans_empty_logs(self):
        """测试对空日志列表聚类"""
        log_models = []
        result = await ClusterService.KMeans(log_models=log_models)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_KMeans_large_dataset(self):
        """测试大规模数据集聚类"""
        log_models = [
            LogModel(
                file_path="/tmp/test.log",
                content=f"error: device {i}",
                offset=i,
                template_vector=[0.1 + i * 0.001] * 768,
            )
            for i in range(100)
        ]

        result = await ClusterService.KMeans(
            log_models=log_models, max_iterations=2, batch_size=8
        )
        assert len(result) > 0


class TestLLMService:
    """LLMService 测试类"""

    @pytest.mark.asyncio
    async def test_assemble_chat(self):
        """测试组装聊天消息"""
        llm = LLMService(
            openai_api_key="test_key",
            openai_api_base="https://test.com",
            model_name="test-model",
            max_tokens=1024,
        )

        chat = llm.assemble_chat(chat=[], system_call="system", user_call="user")
        assert len(chat) == 2
        assert chat[0]["role"] == "system"
        assert chat[0]["content"] == "system"
        assert chat[1]["role"] == "user"
        assert chat[1]["content"] == "user"

    @pytest.mark.asyncio
    async def test_assemble_chat_with_history(self):
        """测试带历史记录的聊天组装"""
        llm = LLMService(
            openai_api_key="test_key",
            openai_api_base="https://test.com",
            model_name="test-model",
            max_tokens=1024,
        )

        history = [{"role": "assistant", "content": "previous"}]
        chat = llm.assemble_chat(chat=history, system_call="system", user_call="user")
        assert len(chat) == 3
        assert chat[0] == {"role": "assistant", "content": "previous"}

    @pytest.mark.asyncio
    async def test_assemble_chat_none_chat(self):
        """测试chat参数为None的情况"""
        llm = LLMService(
            openai_api_key="test_key",
            openai_api_base="https://test.com",
            model_name="test-model",
            max_tokens=1024,
        )

        chat = llm.assemble_chat(chat=None, system_call="system", user_call="user")
        assert len(chat) == 2

    @pytest.mark.asyncio
    async def test_llm_service_initialization(self):
        """测试LLM服务初始化"""
        config = Config().get_config()
        # 跳过无有效配置的测试
        if not config.llm_model.api_key or config.llm_model.api_key == "your_api_key":
            pytest.skip("LLM API Key 未配置，跳过测试")
        llm = LLMService(
            openai_api_key=config.llm_model.api_key,
            openai_api_base=config.llm_model.end_point,
            model_name=config.llm_model.model_name,
            max_tokens=config.llm_model.max_tokens,
            batch_size=config.llm_model.batch_size,
        )
        assert llm is not None
        assert llm.openai_api_key == config.llm_model.api_key


class TestTaskService:
    """TaskService 测试类"""

    @pytest.mark.asyncio
    async def test_process_successful_or_failed_tasks(self):
        """测试处理成功或失败的任务"""
        task_id = str(uuid.uuid4())
        task_model = TaskModel(
            task_id=task_id,
            task_name="test_task",
            task_type=TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS.value,
            completion_precent=100.0,
            status=TaskStatusEnum.SUCCESSFUL_PENDING_REMOVE.value,
            task_related_params=json.dumps({}),
        )
        await TaskManager.create_task(task_model)

        result = await TaskService.process_successful_or_failed_tasks()

        task = await TaskManager.get_task_by_id(task_id)
        assert task.status == TaskStatusEnum.SUCCESSFUL.value

        await TaskManager.delete_task_by_id(task_id)

    @pytest.mark.asyncio
    async def test_process_successful_or_failed_tasks_failed_status(self):
        """测试处理失败状态的任务"""
        task_id = str(uuid.uuid4())
        task_model = TaskModel(
            task_id=task_id,
            task_name="test_task",
            task_type=TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS.value,
            completion_precent=0.0,
            status=TaskStatusEnum.FAILED_PENDING_REMOVE.value,
            task_related_params=json.dumps({}),
        )
        await TaskManager.create_task(task_model)

        result = await TaskService.process_successful_or_failed_tasks()

        task = await TaskManager.get_task_by_id(task_id)
        assert task.status == TaskStatusEnum.FAILED.value

        await TaskManager.delete_task_by_id(task_id)

    @pytest.mark.asyncio
    async def test_process_pending_tasks(self, test_task):
        """测试处理待处理任务"""
        result = await TaskService.process_pending_tasks()

        task = await TaskManager.get_task_by_id(test_task)
        assert task.status in [
            TaskStatusEnum.RUNNING.value,
            TaskStatusEnum.CANCLED.value,
        ]

    @pytest.mark.asyncio
    async def test_update_running_tasks_to_pending_tasks(self):
        """测试将运行中的任务更新为待处理"""
        task_id = str(uuid.uuid4())
        task_model = TaskModel(
            task_id=task_id,
            task_name="test_task",
            task_type=TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS.value,
            completion_precent=50.0,
            status=TaskStatusEnum.RUNNING.value,
            task_related_params=json.dumps({}),
        )
        await TaskManager.create_task(task_model)

        result = await TaskService.update_running_tasks_to_pending_tasks()

        task = await TaskManager.get_task_by_id(task_id)
        assert task.status == TaskStatusEnum.PENDING.value

        await TaskManager.delete_task_by_id(task_id)

    @pytest.mark.asyncio
    async def test_process_successful_or_failed_tasks_empty(self):
        """测试处理空的任务列表"""
        result = await TaskService.process_successful_or_failed_tasks()
        assert len(result) == 0


class TestLogModel:
    """LogModel 测试类"""

    @pytest.mark.asyncio
    async def test_create_log_model(self):
        """测试创建日志模型"""
        log_model = LogModel(
            file_path="/tmp/test.log", content="error: device disconnected", offset=0
        )
        assert log_model.id is not None
        assert len(log_model.id) > 0
        assert log_model.is_anomalous is False
        assert log_model.anomaly_score == 0.0
        assert log_model.anomaly_reason == ""

    @pytest.mark.asyncio
    async def test_log_model_with_anomaly(self):
        """测试带异常信息的日志模型"""
        log_model = LogModel(
            file_path="/tmp/test.log",
            content="error: device disconnected",
            offset=0,
            is_anomalous=True,
            anomaly_reason="network disconnected",
            anomaly_score=85.0,
        )
        assert log_model.is_anomalous is True
        assert log_model.anomaly_reason == "network disconnected"
        assert log_model.anomaly_score == 85.0

    @pytest.mark.asyncio
    async def test_log_model_with_template(self):
        """测试带模板的日志模型"""
        log_model = LogModel(
            file_path="/tmp/test.log",
            content="error: device disconnected",
            offset=0,
            template="<level>: device <action>",
            template_vector=[0.1] * 768,
        )
        assert log_model.template == "<level>: device <action>"
        assert len(log_model.template_vector) == 768

    @pytest.mark.asyncio
    async def test_log_model_with_time(self):
        """测试带时间的日志模型"""
        time = datetime.now()
        log_model = LogModel(
            file_path="/tmp/test.log",
            content="error: device disconnected",
            offset=0,
            start_time=time,
            end_time=time,
        )
        assert log_model.start_time is not None
        assert log_model.end_time is not None

    @pytest.mark.asyncio
    async def test_log_model_with_all_fields(self):
        """测试所有字段的日志模型"""
        time = datetime.now()
        log_model = LogModel(
            file_path="/tmp/test.log",
            log_type=LogTypeEnum.DMESG,
            offset=0,
            start_time=time,
            end_time=time,
            level=LogLevelEnum.ERROR,
            content="error: device disconnected",
            template="<level>: device <action>",
            template_vector=[0.1] * 768,
            is_anomalous=True,
            anomaly_reason="network disconnected",
            anomaly_score=85.0,
        )
        assert log_model.log_type == LogTypeEnum.DMESG
        assert log_model.level == LogLevelEnum.ERROR
        assert log_model.content == "error: device disconnected"


class TestTaskModel:
    """TaskModel 测试类"""

    @pytest.mark.asyncio
    async def test_create_task_model(self):
        """测试创建任务模型"""
        task_model = TaskModel(
            task_name="test_task",
            task_type=TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS.value,
            completion_precent=0.0,
            status=TaskStatusEnum.PENDING.value,
            task_related_params=json.dumps({}),
        )
        assert task_model.task_id is not None
        assert len(task_model.task_id) > 0
        assert task_model.task_name == "test_task"

    @pytest.mark.asyncio
    async def test_task_model_with_pid(self):
        """测试带进程ID的任务模型"""
        task_model = TaskModel(
            task_name="test_task",
            task_type=TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS.value,
            completion_precent=50.0,
            status=TaskStatusEnum.RUNNING.value,
            pid=12345,
            task_related_params=json.dumps({}),
        )
        assert task_model.pid == 12345
        assert task_model.completion_precent == 50.0
        assert task_model.status == TaskStatusEnum.RUNNING.value

    @pytest.mark.asyncio
    async def test_task_model_with_time_range(self):
        """测试带时间范围的任务模型"""
        time_start = datetime.now().strftime("%Y-%m-%d %H:%M")
        time_end = datetime.now().strftime("%Y-%m-%d %H:%M")

        params = {
            "time_start": time_start,
            "time_end": time_end,
            "query": "network error",
            "file_path_list": ["/tmp/test.log"],
            "max_anomaly_log_count": 100,
            "anomaly_keywords": ["error", "failed"],
        }

        task_model = TaskModel(
            task_name="test_task",
            task_type=TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS.value,
            completion_precent=0.0,
            status=TaskStatusEnum.PENDING.value,
            task_related_params=json.dumps(params),
        )

        params_loaded = json.loads(task_model.task_related_params)
        assert "time_start" in params_loaded
        assert "time_end" in params_loaded
        assert params_loaded["query"] == "network error"

    @pytest.mark.asyncio
    async def test_task_model_with_all_fields(self):
        """测试所有字段的任务模型"""
        time_start = datetime.now().strftime("%Y-%m-%d %H:%M")
        time_end = datetime.now().strftime("%Y-%m-%d %H:%M")

        params = {
            "time_start": time_start,
            "time_end": time_end,
            "query": "network error",
            "file_path_list": ["/tmp/test.log"],
            "max_anomaly_log_count": 100,
            "anomaly_keywords": ["error", "failed"],
        }

        task_model = TaskModel(
            task_name="test_task",
            task_type=TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS.value,
            completion_precent=100.0,
            status=TaskStatusEnum.SUCCESSFUL.value,
            pid=12345,
            task_related_params=json.dumps(params),
        )

        assert task_model.pid == 12345
        assert task_model.completion_precent == 100.0
        assert task_model.status == TaskStatusEnum.SUCCESSFUL.value


class TestIntegration:
    """集成测试"""

    @pytest.mark.asyncio
    async def test_full_task_workflow(self, test_task):
        """测试完整任务流程"""
        task_id = test_task

        task = await TaskManager.get_task_by_id(task_id)
        assert task.status == TaskStatusEnum.PENDING.value

        result = await TaskService.process_pending_tasks()

        task = await TaskManager.get_task_by_id(task_id)
        assert task.status in [
            TaskStatusEnum.RUNNING.value,
            TaskStatusEnum.CANCLED.value,
        ]

    @pytest.mark.asyncio
    async def test_worker_run_and_stop(self, test_task):
        """测试worker运行和停止"""
        task_id = test_task

        result = await BaseWorker.run(task_id)
        assert result is True

        task = await TaskManager.get_task_by_id(task_id)
        assert task.status == TaskStatusEnum.RUNNING.value

        result = await BaseWorker.stop(task_id)
        assert result is True

        task = await TaskManager.get_task_by_id(task_id)
        assert task.status == TaskStatusEnum.CANCLED.value


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])
