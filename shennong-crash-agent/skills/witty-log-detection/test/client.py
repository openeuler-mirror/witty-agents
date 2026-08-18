# Copyright (c) Huawei Technologies Co., Ltd. 2023-2025. All rights reserved.
"""MCP Client"""
import json
import asyncio
import logging
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Union
from pydantic import BaseModel, Field
from enum import Enum
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client


logger = logging.getLogger(__name__)


class MCPStatus(str, Enum):
    """MCP状态枚举"""
    UNINITIALIZED = "UNINITIALIZED"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class MCPClient:
    """MCP客户端基类"""

    def __init__(self, url: str, headers: dict[str, str]) -> None:
        """初始化MCP Client"""
        self.url = url
        self.headers = headers
        self.client: Union[ClientSession, None] = None
        self.status = MCPStatus.UNINITIALIZED

    async def _main_loop(
        self
    ) -> None:
        """
        创建MCP Client

        抽象函数；作用为在初始化的时候使用MCP SDK创建Client
        由于目前MCP的实现中Client和Session是1:1的关系，所以直接创建了 :class:`~mcp.ClientSession`
        """
        # 创建Client
        try:
            client = sse_client(
                url=self.url,
                headers=self.headers
            )
        except Exception as e:
            self.error_sign.set()
            err = f"创建Client失败，错误信息：{e}"
            print(err)
            raise Exception(err)
        # 创建Client、Session
        try:
            exit_stack = AsyncExitStack()
            read, write = await exit_stack.enter_async_context(client)
            self.client = ClientSession(read, write)
            session = await exit_stack.enter_async_context(self.client)
            # 初始化Client
            await session.initialize()
        except Exception:
            self.error_sign.set()
            self.status = MCPStatus.STOPPED
            err = f"初始化Client失败，错误信息：{e}"
            print(err)
            raise

        self.ready_sign.set()
        self.status = MCPStatus.RUNNING
        # 等待关闭信号
        await self.stop_sign.wait()

        # 关闭Client
        try:
            await exit_stack.aclose()  # type: ignore[attr-defined]
            self.status = MCPStatus.STOPPED
        except Exception:
            print(f"关闭Client失败，错误信息：{e}")

    async def init(self) -> None:
        """
        初始化 MCP Client类
        :return: None
        """
        # 初始化变量
        self.ready_sign = asyncio.Event()
        self.error_sign = asyncio.Event()
        self.stop_sign = asyncio.Event()

        # 创建协程
        self.task = asyncio.create_task(self._main_loop())

        # 等待初始化完成
        done, pending = await asyncio.wait(
            [asyncio.create_task(self.ready_sign.wait()),
             asyncio.create_task(self.error_sign.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )
        if self.error_sign.is_set():
            self.status = MCPStatus.ERROR
            print("MCP Client 初始化失败")
            raise Exception("MCP Client 初始化失败")

    async def call_tool(self, tool_name: str, params: dict) -> "CallToolResult":
        """调用MCP Server的工具"""
        return await self.client.call_tool(tool_name, params)

    async def stop(self) -> None:
        """停止MCP Client"""
        self.stop_sign.set()
        try:
            await self.task
        except Exception as e:
            err = f"关闭MCP Client失败，错误信息：{e}"
            print(err)


async def main() -> None:
    """测试MCP Client"""
    url = "http://0.0.0.0:12144/sse"
    headers = {}
    client = MCPClient(url, headers)
    await client.init()
    js = {
        "task_type": "log_detection_base_on_llm",
        "query": "我的网卡掉了帮我分析下异常",
        "file_path_list": ["/home/zjq/euler-copilot-rag/witty_log_detection/test/test.log"],
        "anomaly_keywords": ["disconnected"],
        "max_anomaly_log_count": 64
    }
    print(js)
    result = await client.call_tool("create_log_parse_task", js)
    print(result)

    # 解析 task_id 并轮询等待任务完成
    task_data = json.loads(result.content[0].text)
    task_id = task_data["task_id"]
    print(f"任务已创建, task_id: {task_id}")
    while True:
        msg_result = await client.call_tool("get_task_message", {"task_id": task_id})
        msg_data = json.loads(msg_result.content[0].text)
        status = msg_data.get("status", "")
        percent = msg_data.get("completion_precent", 0)
        print(f"任务状态: {status}, 完成度: {percent}%")
        if status in ("successful", "failed"):
            break
        await asyncio.sleep(2)

    # 获取并打印 is_anomalous、anomaly_score
    if status == "successful":
        result_resp = await client.call_tool("get_task_result", {"task_id": task_id, "limit": 20})
        result_data = json.loads(result_resp.content[0].text)
        total = result_data["total"]
        results = result_data["results"]
        print(f"\n共 {total} 条结果, 显示前 {len(results)} 条:")
        for i, item in enumerate(results, 1):
            content_preview = (item.get("content", "") or "")[:80]
            print(f"  [{i}] is_anomalous={item.get('is_anomalous')}, anomaly_score={item.get('anomaly_score')}, content={content_preview}...")
    else:
        print("任务失败, 无检测结果")

    js = {
        "task_id": task_id
    }
    result = await client.call_tool("get_task_result", js)
    print(result)
    await client.stop()

if __name__ == "__main__":
    asyncio.run(main())
