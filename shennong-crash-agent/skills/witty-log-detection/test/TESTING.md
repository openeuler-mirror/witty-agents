# log_detection 测试套件

## 项目结构

```
log_detection/test/
├── test_worker.py          # 主测试文件
├── test_client.py          # MCP客户端测试
├── pyproject.toml          # 项目依赖配置
├── pytest.ini              # pytest配置
└── README.md               # 测试说明文档
```

## 快速开始

### 1. 安装依赖

```bash
cd log_detection/test
pip install -r requirements.txt
```

或者使用 poetry:

```bash
poetry install
```

### 2. 运行测试

```bash
# 运行所有测试
pytest -v

# 运行特定测试文件
pytest test_worker.py -v

# 运行特定测试类
pytest test_worker.py::TestBaseWorker -v

# 显示print输出
pytest -v -s

# 生成HTML报告
pytest -v --html=report.html --self-contained-html

# 显示覆盖率
pytest -v --cov=. --cov-report=html
```

## 测试覆盖范围

### 1. BaseWorker 测试
- Worker 类查找功能
- 文件路径处理功能
- 任务运行和停止功能

### 2. LogDetectionBasedOnKeywordsWorker 测试
- 关键词相似度计算
- 情感分数计算
- 日志文件处理

### 3. LogDetectionBasedOnClusteringWorker 测试
- 关键词相似度计算
- 余弦相似度计算
- 情感分数计算
- 日志模板合并

### 4. ClusterService 测试
- DBSCAN 聚类
- KMeans 聚类
- 单次聚类测试
- 边界情况测试

### 5. LLMService 测试
- 聊天消息组装
- 流式输出
- 非流式输出

### 6. TaskService 测试
- 任务状态更新
- 任务处理
- 进程管理

### 7. LogModel 和 TaskModel 测试
- 模型创建
- 字段验证
- 数据转换

## 测试规范

### 命名规范
- 测试类名：`Test` + 类名
- 测试方法名：`test_` + 功能描述
- 测试文件名：`test_` + 模块名

### 断言规范
- 使用 `assert` 语句
- 提供清晰的错误消息
- 覆盖正常和异常情况

### 异步测试
- 使用 `@pytest.mark.asyncio` 装饰器
- 使用 `pytest-asyncio` 插件

## 配置文件

### pytest.ini
```ini
[pytest]
asyncio_mode = auto
markers =
    async: async test
    slow: slow test
```

### pyproject.toml
```toml
[tool.poetry]
name = "log-detection-test"
version = "0.1.0"
description = "Log detection testing suite"
authors = ["zhaojiaqi18@huawei.com"]

[tool.poetry.dependencies]
python = "^3.9"
pytest = "^7.4.0"
pytest-asyncio = "^0.21.0"
pydantic = "^2.0.0"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

## CI/CD 集成

在 CI/CD 中运行测试：

```yaml
test:
  stage: test
  script:
    - cd log_detection/test
    - pip install -r requirements.txt
    - pytest -v --cov=. --cov-report=xml
  artifacts:
    reports:
      junit: pytest.xml
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
```

## 常见问题

### 1. 测试超时
```bash
pytest -v --asyncio-timeout=60
```

### 2. 数据库连接问题
确保测试前数据库已初始化：
```python
from apps.sqlite.sqlite import AsyncSQLiteSingleton
await AsyncSQLiteSingleton().init()
```

### 3. LLM 测试失败
使用 mock 或跳过 LLM 测试：
```bash
pytest -v -m "not llm"
```

## 贡献指南

欢迎贡献测试代码！

1. Fork 项目
2. 创建测试分支 (`git checkout -b feature/test`)
3. 提交测试 (`git commit -m 'Add some test'`)
4. 推送分支 (`git push origin feature/test`)
5. 提交 Pull Request

## 许可证

本测试套件遵循 Huawei Open Source License。
