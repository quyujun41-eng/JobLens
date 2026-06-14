# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""MCP Client：连接外部 MCP Server（stdio 或 SSE 传输），将其工具暴露给本地 Agent
用法示例：
  client = MCPClient.from_stdio("python", ["/path/to/server.py"])
  tools = await client.list_tools()
  result = await client.call_tool("search_jobs", {"keyword": "RAG"})
"""

import asyncio
import json
from typing import Any


class MCPClient:
    """轻量级 MCP 客户端，支持 stdio 和 SSE 两种传输"""

    def __init__(self):
        self._session = None
        self._tools_cache = None

    # ── stdio 传输（连接本地 MCP Server 进程）────────────────────────────

    @classmethod
    def from_stdio(cls, command: str, args: list[str]) -> "MCPClient":
        """工厂方法：创建 stdio MCP 客户端"""
        instance = cls()
        instance._command = command
        instance._args = args
        instance._transport = "stdio"
        return instance

    # ── SSE 传输（连接远程 MCP Server HTTP 端点）─────────────────────────

    @classmethod
    def from_sse(cls, url: str) -> "MCPClient":
        """工厂方法：创建 SSE MCP 客户端"""
        instance = cls()
        instance._sse_url = url
        instance._transport = "sse"
        return instance

    # ── 核心方法 ──────────────────────────────────────────────────────────

    async def list_tools(self) -> list[dict]:
        """列出 MCP Server 提供的所有工具"""
        if self._tools_cache is not None:
            return self._tools_cache

        if self._transport == "stdio":
            tools = await self._stdio_list_tools()
        else:
            tools = await self._sse_list_tools()

        self._tools_cache = tools
        return tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        """调用指定工具，返回结果文本"""
        if self._transport == "stdio":
            return await self._stdio_call_tool(name, arguments)
        else:
            return await self._sse_call_tool(name, arguments)

    # ── stdio 实现 ────────────────────────────────────────────────────────

    async def _stdio_request(self, method: str, params: dict = None) -> Any:
        """向 stdio MCP Server 发送 JSON-RPC 请求并等待响应"""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client
        import mcp.types as types

        server_params = types.StdioServerParameters(
            command=self._command,
            args=self._args,
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                if method == "tools/list":
                    result = await session.list_tools()
                    return result.tools
                elif method == "tools/call":
                    result = await session.call_tool(params["name"], params.get("arguments", {}))
                    return result.content
        return None

    async def _stdio_list_tools(self) -> list[dict]:
        tools = await self._stdio_request("tools/list")
        if not tools:
            return []
        return [
            {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
            for t in tools
        ]

    async def _stdio_call_tool(self, name: str, arguments: dict) -> str:
        content = await self._stdio_request("tools/call", {"name": name, "arguments": arguments})
        if not content:
            return ""
        return "\n".join(c.text for c in content if hasattr(c, "text"))

    # ── SSE 实现 ──────────────────────────────────────────────────────────

    async def _sse_request(self, method: str, params: dict = None) -> Any:
        """向 SSE MCP Server 发送 JSON-RPC 请求"""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        async with sse_client(self._sse_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                if method == "tools/list":
                    result = await session.list_tools()
                    return result.tools
                elif method == "tools/call":
                    result = await session.call_tool(params["name"], params.get("arguments", {}))
                    return result.content
        return None

    async def _sse_list_tools(self) -> list[dict]:
        tools = await self._sse_request("tools/list")
        if not tools:
            return []
        return [
            {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
            for t in tools
        ]

    async def _sse_call_tool(self, name: str, arguments: dict) -> str:
        content = await self._sse_request("tools/call", {"name": name, "arguments": arguments})
        if not content:
            return ""
        return "\n".join(c.text for c in content if hasattr(c, "text"))

    # ── 同步封装（在 Flask 中使用）───────────────────────────────────────

    def sync_list_tools(self) -> list[dict]:
        """同步版 list_tools，可在普通函数中调用"""
        return asyncio.run(self.list_tools())

    def sync_call_tool(self, name: str, arguments: dict) -> str:
        """同步版 call_tool，可在普通函数中调用"""
        return asyncio.run(self.call_tool(name, arguments))


# ── 工厂函数：连接本地 JobLens MCP Server ─────────────────────────────────

def get_local_joblens_client() -> MCPClient:
    """获取连接本地 JobLens MCP Server 的客户端实例"""
    import os
    server_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")
    return MCPClient.from_stdio("python", [server_path])


if __name__ == "__main__":
    import sys

    async def demo():
        # 演示：连接本地 JobLens MCP Server
        client = get_local_joblens_client()
        print("可用工具：")
        tools = await client.list_tools()
        for t in tools:
            print(f"  - {t['name']}: {t['description']}")

        print("\n调用 get_overview：")
        result = await client.call_tool("get_overview", {})
        print(result)

    asyncio.run(demo())
