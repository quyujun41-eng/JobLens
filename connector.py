# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""Connector 模式：统一工具注册表，将本地工具、MCP Server、外部 API 聚合为单一接口
Agent 通过 Connector 调用工具，无需关心工具来源（本地/MCP/远程API）"""

from typing import Callable


class ToolConnector:
    """工具连接器：注册 + 路由 + 统一调用"""

    def __init__(self):
        self._tools: dict = {}  # name → {schema, handler, source}

    # ── 注册接口 ────────────────────────────────────────────

    def register(self, name: str, description: str, schema: dict,
                 handler: Callable, source: str = "local") -> None:
        """注册单个工具"""
        self._tools[name] = {
            "name": name,
            "description": description,
            "input_schema": schema,
            "handler": handler,
            "source": source,
        }

    def register_from_agent_tools(self, tools: list, execute_fn: Callable) -> None:
        """批量注册 agent.TOOLS 列表中的所有工具"""
        for t in tools:
            name = t["name"]
            def _make(n):
                def handler(**kwargs):
                    return execute_fn(n, kwargs)
                return handler
            self.register(name, t["description"], t["input_schema"],
                          _make(name), source="local")

    def register_mcp_server(self, mcp_client, source_name: str = "mcp") -> int:
        """从 MCP Client 批量注册工具（同步），返回注册数量"""
        try:
            remote_tools = mcp_client.sync_list_tools()
            for t in remote_tools:
                n = t["name"]
                def _make(c, _n):
                    def handler(**kwargs):
                        return c.sync_call_tool(_n, kwargs)
                    return handler
                self.register(
                    n, t.get("description", ""),
                    t.get("inputSchema", {"type": "object", "properties": {}}),
                    _make(mcp_client, n), source=source_name,
                )
            return len(remote_tools)
        except Exception as e:
            print(f"[Connector] MCP 注册失败 ({source_name}): {e}")
            return 0

    # ── 查询接口 ────────────────────────────────────────────

    def list_tools(self) -> list:
        """返回所有工具的 Anthropic tool_use 格式 schema"""
        return [
            {
                "name": t["name"],
                "description": f"[{t['source']}] {t['description']}",
                "input_schema": t["input_schema"],
            }
            for t in self._tools.values()
        ]

    def list_tool_info(self) -> list:
        """返回所有工具的基本信息（不含 handler）"""
        return [
            {"name": t["name"], "description": t["description"], "source": t["source"]}
            for t in self._tools.values()
        ]

    def get_source(self, name: str) -> str:
        return self._tools.get(name, {}).get("source", "unknown")

    def __len__(self):
        return len(self._tools)

    def __contains__(self, name: str):
        return name in self._tools

    # ── 调用接口 ────────────────────────────────────────────

    def call(self, name: str, arguments: dict) -> str:
        """统一调用接口，屏蔽工具来源差异"""
        if name not in self._tools:
            return f"工具 {name!r} 未注册（已注册：{list(self._tools)}）"
        try:
            result = self._tools[name]["handler"](**arguments)
            return str(result) if result is not None else ""
        except Exception as e:
            return f"[{name}] 执行失败: {e}"


# ── 全局单例 ─────────────────────────────────────────────────

_connector: ToolConnector = None


def get_connector() -> ToolConnector:
    """获取全局 Connector 实例（懒加载）"""
    global _connector
    if _connector is not None:
        return _connector

    _connector = ToolConnector()

    # 注册本地 Agent 工具
    from agent import TOOLS, _execute_tool
    _connector.register_from_agent_tools(TOOLS, _execute_tool)

    print(f"[Connector] 初始化完成，共 {len(_connector)} 个工具")
    return _connector


def reset_connector() -> None:
    """重置单例（用于测试或热重载）"""
    global _connector
    _connector = None
