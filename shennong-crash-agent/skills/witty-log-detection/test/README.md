# Log Detection 测试套件

本目录包含基于 pytest 的测试程序，用于测试 log_detection 模块的各种功能。

## 测试文件说明

### test_worker.py
主要测试文件，包含以下测试类：

#### TestBaseWorker
- `test_find_worker_class_exists`: 测试查找存在的worker类
- `test_find_worker_class_not_exists`: 测试查找不存在的worker类
- `test_get_worker_name`: 测试获取worker名称
- `test_get_files_from_file_path_list_single_file`: 测试处理单个文件路径
- `test_get_files_from_file_path_list_directory`: 测试处理目录路径
- `test_get_files_from_file_path_list_empty`: 测试处理空路径列表

#### TestLogDetectionBasedOnKeywordsWorker
- `test_cal_keyword_similarity_full_match`: 测试计算关键词完全匹配的相似度
- `test_cal_keyword_similarity_partial_match`: 测试计算关键词部分匹配的相似度
- `test_cal_keyword_similarity_no_match`: 测试计算关键词不匹配的相似度
- `test_cal_keyword_similarity_empty_keywords`: 测试计算关键词为空列表的相似度
- `test_cal_keyword_similarity_empty_text`: 测试计算空字符串与关键词的相似度
- `test_cal_sentiment_score_with_anomaly_keywords`: 测试计算包含异常关键词的日志情感分数
- `test_cal_sentiment_score_without_anomaly_keywords`: 测试计算不包含异常关键词的日志情感分数
- `test_cal_sentiment_score_unknown_log_type`: 测试计算未知日志类型的情感分数
- `test_cal_sentiment_score_empty_log_type`: 测试计算日志类型为空的情感分数

#### TestLogDetectionBasedOnClusteringWorker
- `test_cal_keyword_similarity`: 测试关键词相似度计算
- `test_cal_sentiment_score`: 测试情感分数计算
- `test_cal_cosine_similarity_full_match`: 测试计算完全相似的向量
- `test_cal_cosine_similarity_no_match`: 测试计算完全不相似的向量
- `test_cal_cosine_similarity_partial_match`: 测试计算部分相似的向量
- `test_cal_cosine_similarity_zero_vector`: 测试计算零向量相似度
- `test_cal_cosine_similarity_high_dimensional`: 测试计算高维向量相似度

#### TestClusterService
- `test_single_DBSCAN`: 测试单次DBSCAN聚类
- `test_single_DBSCAN_all_outliers`: 测试所有点都是离群点的情况
- `test_single_KMeans`: 测试单次KMeans聚类
- `test_single_KMeans_k_greater_than_clusters`: 测试K值大于聚类数量的情况
- `test_single_KMeans_k_equals_1`: 测试K值为1的情况
- `test_DBSCAN`: 测试DBSCAN聚类服务
- `test_DBSCAN_empty_logs`: 测试对空日志列表聚类
- `test_KMeans`: 测试KMeans聚类服务
- `test_KMeans_empty_logs`: 测试对空日志列表聚类

#### TestLLMService
- `test_assemble_chat`: 测试组装聊天消息
- `test_assemble_chat_with_history`: 测试带历史记录的聊天组装
- `test_nostream_with_valid_response`: 测试LLM非流式调用

#### TestTaskService
- `test_process_successful_or_failed_tasks`: 测试处理成功或失败的任务
- `test_process_pending_tasks`: 测试处理待处理任务
- `test_update_running_tasks_to_pending_tasks`: 测试将运行中的任务更新为待处理

#### TestLogModel
- `test_create_log_model`: 测试创建日志模型
- `test_log_model_with_anomaly`: 测试带异常信息的日志模型
- `test_log_model_with_template`: 测试带模板的日志模型

#### TestTaskModel
- `test_create_task_model`: 测试创建任务模型
- `test_task_model_with_pid`: 测试带进程ID的任务模型
- `test_task_model_with_time_range`: 测试带时间范围的任务模型

## 运行测试

### 安装依赖

```bash
cd log_detection/test
poetry install
```

### 运行所有测试

```bash
poetry run pytest -v
```

### 运行特定测试类

```bash
poetry run pytest -v test_worker.py::TestBaseWorker
```

### 运行特定测试

```bash
poetry run pytest -v test_worker.py::TestBaseWorker::test_find_worker_class_exists
```

### 生成测试报告

```bash
poetry run pytest -v --html=report.html --self-contained-html
```

### 运行并显示print输出

```bash
poetry run pytest -v -s
```

## 测试覆盖率

要查看测试覆盖率，可以安装 pytest-cov：

```bash
poetry add --dev pytest-cov
poetry run pytest --cov=. --cov-report=html
```

## 注意事项

1. 测试需要访问 SQLite 数据库，测试前确保数据库文件存在
2. LLMService 测试需要有效的 API 密钥和端点配置
3. 某些测试可能需要特定的日志文件进行测试
4. 测试会创建临时文件和数据库记录，测试后会自动清理

## 添加新测试

添加新测试时，请遵循以下规则：

1. 测试类名以 `Test` 开头
2. 测试方法名以 `test_` 开头
3. 使用 `@pytest.mark.asyncio` 装饰异步测试
4. 使用 `assert` 语句验证结果
5. 保持测试独立，不依赖其他测试的执行顺序

## 参考文档

- [pytest 官方文档](https://docs.pytest.org/)
- [pytest-asyncio 文档](https://pytest-asyncio.readthedocs.io/)
