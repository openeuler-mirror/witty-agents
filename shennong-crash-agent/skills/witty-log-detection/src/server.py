import json
import uuid
import asyncio
from typing import Annotated
from pydantic import Field
from mcp.server import FastMCP
from src.enum.task import TaskStatusEnum
from src.enum.task import TaskTypeEnum
from src.config.config import Config
from src.service.embedding import Embedding
from src.service.llm import LLMService
from src.service.log import LogTaskHandleService
from src.sqlite.sqlite import AsyncSQLiteSingleton
from src.service.task import TaskService

host = Config().get_config().run_config.host
port = Config().get_config().run_config.port
mcp = FastMCP("Log Detect MCP Server", host=host, port=port)

def _task_type_needs_models(task_type: TaskTypeEnum | None) -> tuple[bool, bool]:
    """返回 (是否需要 embedding, 是否需要 LLM)"""
    if task_type is None:
        cfg = Config().get_config()
        task_type = cfg.log_parse_method

    if task_type in (
        TaskTypeEnum.BASE,
        TaskTypeEnum.LOG_DETECTION_BASE_ON_KEYWORDS,
    ):
        return False, False
    if task_type == TaskTypeEnum.LOG_DETECTION_BASE_ON_LLM:
        return True, True
    # clustering / embedding 方法只依赖 embedding
    return True, False


@mcp.tool(
    name="setup_log_detection_config",
    description="""
    首次使用日志检测 MCP 时配置 Embedding 和 LLM 模型参数。
    配置会保存到 ~/.config/shennong-crash-agent/witty-log-detection-config.toml。
    参数包括：
    - embedding_provider: Embedding 供应商，可选 openai/ascending
    - embedding_end_point: Embedding API 端点
    - embedding_api_key: Embedding API 密钥
    - embedding_model_name: Embedding 模型名称
    - llm_provider: LLM 供应商，可选 openai/ascending
    - llm_end_point: LLM API 端点
    - llm_api_key: LLM API 密钥
    - llm_model_name: LLM 模型名称
    - llm_max_tokens: 最大生成 token 数
    返回是否保存成功。
    """,
)
async def setup_log_detection_config(
    embedding_provider: Annotated[str, Field(default="openai", description="Embedding 供应商，例如 openai/ascending")] = "openai",
    embedding_end_point: Annotated[str, Field(default="", description="Embedding API 端点，例如 https://api.siliconflow.cn/v1/embeddings")] = "",
    embedding_api_key: Annotated[str, Field(default="", description="Embedding API 密钥")] = "",
    embedding_model_name: Annotated[str, Field(default="", description="Embedding 模型名称，例如 BAAI/bge-m3")] = "",
    llm_provider: Annotated[str, Field(default="openai", description="LLM 供应商，例如 openai/ascending")] = "openai",
    llm_end_point: Annotated[str, Field(default="", description="LLM API 端点，例如 https://dashscope.aliyuncs.com/compatible-mode/v1")] = "",
    llm_api_key: Annotated[str, Field(default="", description="LLM API 密钥")] = "",
    llm_model_name: Annotated[str, Field(default="", description="LLM 模型名称，例如 qwen3-max")] = "",
    llm_max_tokens: Annotated[int, Field(default=32000, description="LLM 最大生成 token 数")] = 32000,
) -> str:
    Config.save_user_config(
        embedding={
            "provider": embedding_provider,
            "end_point": embedding_end_point,
            "api_key": embedding_api_key,
            "model_name": embedding_model_name,
        },
        llm={
            "provider": llm_provider,
            "end_point": llm_end_point,
            "api_key": llm_api_key,
            "model_name": llm_model_name,
            "max_tokens": llm_max_tokens,
        },
    )
    return json.dumps({
        "success": True,
        "message": f"配置已保存到 {Config.get_user_config_path()}，请重新调用日志检测任务。"
    })


@mcp.tool(
    name="test_log_detection_connection",
    description="""
    测试日志检测 MCP 与 Embedding / LLM 服务的连接是否正常。
    如果连接失败，会返回具体错误信息，提示检查配置。
    """,
)
async def test_log_detection_connection() -> str:
    cfg = Config()
    results = {}
    if cfg.is_embedding_configured():
        try:
            await Embedding.test_connection()
            results["embedding"] = "ok"
        except Exception as e:
            results["embedding"] = f"failed: {e}"
    else:
        results["embedding"] = "not configured"

    if cfg.is_llm_configured():
        try:
            llm = LLMService(
                openai_api_key=cfg.get_config().llm_model.api_key,
                openai_api_base=cfg.get_config().llm_model.end_point,
                model_name=cfg.get_config().llm_model.model_name,
                max_tokens=cfg.get_config().llm_model.max_tokens,
                batch_size=cfg.get_config().llm_model.batch_size,
            )
            await llm.test_connection()
            results["llm"] = "ok"
        except Exception as e:
            results["llm"] = f"failed: {e}"
    else:
        results["llm"] = "not configured"

    return json.dumps(results)


@mcp.tool(
    name="create_log_parse_task",
    description="""
    这是创建日志解析任务的工具函数，前端会调用这个接口来创建日志解析任务。参数包括：
    - task_type: 任务类型，枚举值包括：base（基础版本，直接返回日志内容，不进行异常检测）、log_detection_base_on_keywords（基于关键词的日志检测）、log_detection_base_on_clustering（基于聚类的日志检测）、log_detection_base_on_llm（基于LLM的日志检测）,log_detection_base_on_embedding(基于embedding和关键字的日志检测),也可以者不传，默认为配置文件中设置的日志解析方法
    - query: 查询语句，用于描述当前的异常现象或者需要关注的日志内容，基于这个查询语句，日志检测Worker会进行日志异常检测
    - file_path_list: 日志文件路径列表，包含需要进行日志检测的日志文件的路径
    - max_anomaly_log_count: 最大异常日志数量，日志检测Worker会根据这个数量来限制返回的异常日志的数量，确保不会返回过多的异常日志
    - anomaly_keywords: 异常关键词列表，基于关键词的日志检测Worker会使用这个异常关键词列表来进行日志的异常检测
    - time_start: 日志时间范围的起始时间，格式为 "YYYY-MM-DD HH:MM"，日志检测Worker会基于这个时间范围来过滤日志，确保只检测这个时间范围内的日志
    - time_end: 日志时间范围的结束时间，格式为 "YYYY-MM-DD HH:MM"，日志检测Worker会基于这个时间范围来过滤日志，确保只检测这个时间范围内的日志
    - enable_deduplication: 是否启用去重，默认为False。当返回结果中大量重复日志片段时，可开启此开关。开启后会对结果进行去重，每个条目会附带 duplicate_count 字段表示该日志在去重前出现的次数
    - deduplication_threshold: 去重阈值，默认为0.8。当 enable_deduplication 为 False 时，如果 topK 结果中重复率超过此阈值，也会自动触发去重
    这个函数会返回创建的任务ID（uuid4格式），前端可以基于这个任务ID来查询任务的执行状态和结果。返回格式如下：
    {
        "task_id": "生成的任务ID，uuid4格式"
    }
    """,
)
async def create_log_parse_task(
    task_type: TaskTypeEnum | None = None,
    query: str = Field(
        default="",
        description="查询语句，用于描述当前的异常现象或者需要关注的日志内容，基于这个查询语句，日志检测Worker会进行日志异常检测",
    ),
    file_path_list: list[str] = Field(
        default_factory=list,
        description="日志文件路径列表，包含需要进行日志检测的日志文件的路径",
    ),
    max_anomaly_log_count: int = Field(
        default=64,
        description="最大异常日志数量，日志检测Worker会根据这个数量来限制返回的异常日志的数量，确保不会返回过多的异常日志",
    ),
    anomaly_keywords: list[str] = Field(
        default_factory=list,
        description="异常关键词列表，基于关键词的日志检测Worker会使用这个异常关键词列表来进行日志的异常检测",
    ),
    time_start: str | None = Field(
        default=None,
        description="日志时间范围的起始时间，格式为 'YYYY-MM-DD HH:MM'",
        pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$",
    ),
    time_end: str | None = Field(
        default=None,
        description="日志时间范围的结束时间，格式为 'YYYY-MM-DD HH:MM'",
        pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$",
    ),
    enable_deduplication: bool = Field(
        default=False,
        description="是否启用去重，当返回结果中大量重复时，可开启此开关",
    ),
    deduplication_threshold: float = Field(
        default=0.8,
        description="去重阈值，当topk中重复率超过此值时自动触发去重",
    ),
) -> str:
    cfg = Config()
    needs_embedding, needs_llm = _task_type_needs_models(task_type)
    missing = []
    if needs_embedding and not cfg.is_embedding_configured():
        missing.append("Embedding 模型")
    if needs_llm and not cfg.is_llm_configured():
        missing.append("LLM 模型")
    if missing:
        return json.dumps({
            "error": "CONFIGURATION_REQUIRED",
            "message": Config.build_config_prompt(),
            "missing": missing,
        })
    task_id = await LogTaskHandleService.create_log_parse_task(
        task_type=task_type,
        query=query,
        file_path_list=file_path_list,
        max_anomaly_log_count=max_anomaly_log_count,
        anomaly_keywords=anomaly_keywords,
        time_start=time_start,
        time_end=time_end,
        enable_deduplication=enable_deduplication,
        deduplication_threshold=deduplication_threshold,
    )
    return json.dumps({"task_id": task_id})


@mcp.tool(
    name="get_task_message",
    description="""
    这是获取任务信息的工具函数，前端会调用这个接口来获取任务的执行状态和相关信息。参数包括：
- task_id: 任务ID，uuid4格式
这个函数会返回任务的相关信息，包括：任务ID、任务名称、任务类型、任务完成百分比、任务状态、任务相关参数、任务创建时间。返回格式如下：
{
    "task_id": "任务ID，uuid4格式",
    "task_name": "任务名称",
    "task_type": "任务类型",
    "compltetion_precent": 任务完成百分比，float类型,
    "status": "任务状态",
    "task_related_params": "任务相关参数，json字符串格式",
    "created_at": "任务创建时间，格式为 'YYYY-MM-DD HH:MM:SS'"
}
    """,
)
async def get_task_status(
    task_id: str = Field(description="任务ID，uuid4格式的字符串"),
) -> str:
    task_model = await LogTaskHandleService.get_task_message(task_id)
    if task_model is None:
        raise ValueError(f"任务 {task_id} 不存在")
    return json.dumps(task_model.model_dump(exclude_none=True))


@mcp.tool(
    name="stop_task",
    description="""
    这是停止任务的工具函数，前端会调用这个接口来停止正在执行的任务。参数包括：
    - task_id: 任务ID，uuid4格式的字符串
    这个函数会返回一个布尔值，表示是否成功停止了任务。返回格式如下：
    {
        "success": true // 如果成功停止了任务，则为true；如果没有成功停止任务（例如任务已经完成或者不存在），则为false
    }
""",
)
async def stop_task(
    task_id: str = Field(description="任务ID，uuid4格式的字符串"),
) -> str:
    success = await LogTaskHandleService.stop_task(task_id)
    return json.dumps({"success": success})


@mcp.tool(
    name="get_task_result",
    description="""
    这是获取任务结果的工具函数，前端会调用这个接口来获取任务的执行结果。参数包括：
- task_id: 任务ID，uuid4格式的字符串
- offset: 偏移量，整数类型，表示从第几条结果开始返回，用于分页查询
- limit: 返回结果的数量，整数类型，表示一次返回多少条结果，用于分页查询
- is_anomalous: 是否只返回异常日志，布尔类型，如果为true，则只返回异常日志；如果为false，则返回所有日志；如果不传，则默认返回所有日志
这个函数会返回任务的执行结果，包括总结果数量和结果列表。结果列表中的每个元素包含：日志文件路径、任务ID、异常原因（如果是异常日志则有值，否则为null）、异常分数（如果是异常日志则有值，否则为null）。返回格式如下：
{
    "total": 总结果数量，整数类型,
    "results": [
        {
            "id": "日志解析结果ID，uuid4格式",
            "file_path": "日志文件路径",
            "task_id": "任务ID，uuid4格式",
            "is_anomalous": "日志是否异常，布尔类型",
            "content": "日志内容，字符串类型",
            "anomaly_reason": "日志异常原因，如果日志不异常，则返回空字符串",
            "anomaly_score": "日志异常分数，如果日志不异常，则返回0.0"
        },
        ...
    ]
""",
)
# 加关键字匹配
async def get_task_result(
    task_id: str = Field(description="任务ID，uuid4格式的字符串"),
    offset: int | None = Field(
        default=None,
        description="偏移量，整数类型，表示从第几条结果开始返回，用于分页查询",
    ),
    limit: int | None = Field(
        default=None,
        description="返回结果的数量，整数类型，表示一次返回多少条结果，用于分页查询",
    ),
    is_anomalous: bool | None = Field(
        default=None,
        description="是否只返回异常日志，布尔类型，如果为true，则只返回异常日志；如果为false，则返回所有日志；如果不传，则默认返回所有日志",
    ),
) -> str:
    task_model = await LogTaskHandleService.get_task_message(task_id)
    if task_model is None:
        raise ValueError(f"任务 {task_id} 不存在")
    if (
        task_model.status == TaskStatusEnum.PENDING.value
        or task_model.status == TaskStatusEnum.RUNNING.value
    ):
        return "任务正在执行中，结果尚未生成结果，请稍后再试"
    total, log_parse_result_models = await LogTaskHandleService.get_task_result(
        task_id, limit, offset, is_anomalous
    )
    return json.dumps(
        {
            "total": total,
            "results": [
                log_parse_result_model.model_dump(exclude_none=True)
                for log_parse_result_model in log_parse_result_models
            ],
        }
    )


@mcp.tool(
    name="delete_task",
    description="""
    这是删除任务的工具函数，前端会调用这个接口来删除指定的任务。参数包括：
    - task_id: 任务ID，uuid4格式的字符串
    这个函数会先尝试停止正在运行的任务（如果任务正在运行），然后从数据库中删除任务记录。函数会返回一个布尔值，表示是否成功删除了任务。返回格式如下：
    {
        "success": true // 如果成功删除了任务，则为true；如果没有成功删除任务（例如任务不存在），则为false
    }
    """,
)
async def delete_task(
    task_id: str = Field(description="任务ID，uuid4格式的字符串"),
) -> str:
    success = await LogTaskHandleService.delete_task(task_id)
    return json.dumps({"success": success})

@mcp.tool(
    name="get_task_queue",
    description="""
    这是获取任务队列情况的工具函数，前端会调用这个接口来获取所有任务的状态信息。
    这个函数会返回所有任务的列表，每个任务包含：任务ID、任务完成百分比、任务状态。返回格式如下：
    {
        "tasks": [
            {
                "task_id": "任务ID，uuid4格式",
                "completion_percent": "任务完成百分比，float类型",
                "status": "任务状态"
            },
            ...
        ]
    }
    """,
)
async def get_task_queue() -> str:
    task_models = await LogTaskHandleService.get_all_tasks()
    return json.dumps({
        "tasks": [
            {
                "task_id": task_model.task_id,
                "status": task_model.status,
                "completion_percent": task_model.completion_precent
            }
            for task_model in task_models
        ],
    })
    
# 定义异步主函数，统一管理异步任务和MCP服务器启动


def init():
    AsyncSQLiteSingleton()
    asyncio.run(TaskService.update_running_tasks_to_pending_tasks())


if __name__ == "__main__":
    init()
    try:
        listener = TaskService.run_task_listener_in_process()
        mcp.run(transport="sse")
    except Exception as e:
        print(f"启动MCP Server失败，错误信息：{e}")
    finally:
        import os
        import signal

        print(f"任务监听进程ID：{listener.pid}")
        if listener.pid is not None:
            os.kill(listener.pid, signal.SIGKILL)
        print(f"任务监听进程ID：{listener.pid} 已被终止")
