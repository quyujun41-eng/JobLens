# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""JobLens MCP Server — 把岗位数据库能力暴露为 MCP 工具
Claude Desktop / Cursor 等 MCP 客户端可直接接入查询招聘数据

启动方式（stdio，供 Claude Desktop 使用）：
  python mcp_server.py

Claude Desktop 配置（~/.claude/claude_desktop_config.json）：
  {
    "mcpServers": {
      "joblens": {
        "command": "python",
        "args": ["/absolute/path/to/JobLens/mcp_server.py"]
      }
    }
  }
"""

import asyncio
import json
import sys
import os

# 将项目根目录加入 path，确保能 import 本项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

import analytics
import config
from models import Job, app as flask_app

server = Server("joblens")

# ── 工具定义 ─────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_jobs",
            description="搜索 JobLens 岗位库，支持关键词、城市、薪资筛选，返回匹配的招聘岗位列表",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词，如 RAG、Agent、Python"},
                    "city": {"type": "string", "description": "城市，如 深圳、北京、上海"},
                    "salary_min": {"type": "number", "description": "最低薪资 K/月"},
                    "salary_max": {"type": "number", "description": "最高薪资 K/月"},
                    "top_k": {"type": "integer", "description": "返回数量，默认10"},
                },
            },
        ),
        types.Tool(
            name="get_job_detail",
            description="获取单个招聘岗位的完整 JD、技能要求、公司信息",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "岗位ID，从 search_jobs 结果中获取"},
                },
                "required": ["job_id"],
            },
        ),
        types.Tool(
            name="get_market_stats",
            description="获取招聘市场统计数据：薪资分布、热门技能排行、企业薪资排名、招聘趋势",
            inputSchema={
                "type": "object",
                "properties": {
                    "stat_type": {
                        "type": "string",
                        "enum": ["salary", "skills", "companies", "trend"],
                        "description": "salary=薪资分布, skills=技能排行, companies=企业排名, trend=招聘趋势",
                    },
                },
                "required": ["stat_type"],
            },
        ),
        types.Tool(
            name="get_coverage_status",
            description="查询 JobLens 当前数据覆盖情况：哪些城市×行业组合已有数据",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        types.Tool(
            name="get_overview",
            description="获取 JobLens 数据库总览：岗位总数、公司数、平均薪资、已覆盖城市",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


# ── 工具执行 ─────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, _sync_execute, name, arguments
        )
        return [types.TextContent(type="text", text=result)]
    except Exception as e:
        return [types.TextContent(type="text", text=f"工具执行失败: {e}")]


def _sync_execute(name: str, args: dict) -> str:
    with flask_app.app_context():
        if name == "search_jobs":
            keyword = args.get("keyword")
            bm25_ids = None
            if keyword:
                try:
                    from vector_search import hybrid_search
                    bm25_ids = hybrid_search(keyword, top_k=50)
                except Exception:
                    import search as bm25
                    bm25.rebuild_index_if_needed()
                    bm25_ids = bm25.search(keyword, top_k=50)

            result = analytics.job_list(
                page=1, per_page=min(int(args.get("top_k", 10)), 50),
                keyword=keyword, city=args.get("city"),
                salary_min=args.get("salary_min"), salary_max=args.get("salary_max"),
                bm25_ids=bm25_ids,
            )
            items = result.get("items", [])
            if not items:
                return f"未找到匹配岗位（共检索 {result['total']} 条）"
            lines = [f"共 {result['total']} 个匹配岗位，返回前 {len(items)} 条：\n"]
            for j in items:
                lines.append(
                    f"• [{j['job_id']}] **{j['title']}** @ {j['company_name']}\n"
                    f"  薪资：{j['salary']} | 城市：{j['city']} {j.get('area','')} | "
                    f"经验：{j['experience']} | 技能：{', '.join(j['skill_tags'][:4])}"
                )
            return "\n".join(lines)

        elif name == "get_job_detail":
            job = Job.query.filter_by(job_id=args.get("job_id", "")).first()
            if not job:
                return "岗位不存在"
            tags = json.loads(job.skill_tags) if job.skill_tags else []
            return json.dumps({
                "title": job.title,
                "company": job.company.name if job.company else "",
                "company_industry": job.company.industry if job.company else "",
                "company_scale": job.company.scale if job.company else "",
                "salary": analytics._format_salary(job),
                "city": job.city, "area": job.area,
                "experience": analytics._format_experience(job),
                "education": job.education_req,
                "skill_tags": tags,
                "description": job.description or "",
                "url": job.url,
            }, ensure_ascii=False, indent=2)

        elif name == "get_market_stats":
            st = args.get("stat_type", "salary")
            if st == "salary":
                d = analytics.salary_distribution()
                lines = ["## 薪资分布（K/月）\n"]
                for label, cnt in zip(d["labels"], d["counts"]):
                    bar = "█" * min(cnt, 30)
                    lines.append(f"{label:>12}  {bar} {cnt}")
                return "\n".join(lines)

            elif st == "skills":
                d = analytics.skill_ranking(top_n=20)
                lines = ["## 技能需求排行 TOP 20\n"]
                for i, (label, cnt) in enumerate(zip(d["labels"], d["counts"]), 1):
                    lines.append(f"{i:>2}. {label:<20} {cnt} 个岗位")
                return "\n".join(lines)

            elif st == "companies":
                d = analytics.company_salary_ranking(top_n=15)
                lines = ["## 企业薪资排行 TOP 15\n"]
                for i, (name, sal, cnt) in enumerate(
                    zip(d["labels"], d["avg_salary"], d["job_count"]), 1
                ):
                    lines.append(f"{i:>2}. {name:<20} 均薪 {sal}K  ({cnt} 个岗位)")
                return "\n".join(lines)

            elif st == "trend":
                d = analytics.hiring_trend()
                if not d.get("labels"):
                    return "暂无趋势数据"
                lines = ["## 招聘量 & 薪资趋势（按月）\n", f"{'月份':<10} {'岗位数':>6} {'均薪(K)':>8}"]
                lines.append("-" * 30)
                for m, cnt, sal in zip(d["labels"], d["job_count"], d["avg_salary"]):
                    sal_str = f"{sal:.1f}" if sal else "  -"
                    lines.append(f"{m:<10} {cnt:>6} {sal_str:>8}")
                return "\n".join(lines)

            return "未知统计类型"

        elif name == "get_coverage_status":
            from models import CoverageRequest
            core_pairs = {(c["city"], c["industry"]) for c in config.CORE_COMBOS}
            done_pairs = {
                (r.city, r.industry)
                for r in CoverageRequest.query.filter_by(status="done").all()
            }
            covered = core_pairs | done_pairs

            lines = ["## JobLens 数据覆盖状态\n"]
            lines.append(f"核心组合：{len(config.CORE_COMBOS)} 个（{len(config.CORE_INDUSTRIES)}行业 × {len(config.CORE_CITIES)}城市）\n")
            lines.append(f"{'行业':<14} " + "  ".join(f"{c:<4}" for c in config.CORE_CITIES))
            lines.append("-" * 50)
            for ind in config.CORE_INDUSTRIES:
                row = f"{ind:<14} "
                for city in config.CORE_CITIES:
                    row += "✅  " if (city, ind) in covered else "🔒  "
                lines.append(row)
            lines.append(f"\n完整覆盖：{len(covered)} / {len(config.INDUSTRIES) * len(config.CITIES)} 个组合")
            return "\n".join(lines)

        elif name == "get_overview":
            from models import Company
            from sqlalchemy import func as sqlfunc
            total_jobs = Job.query.filter_by(is_active=True).count()
            total_cos = (
                flask_app.extensions["sqlalchemy"].session
                .query(Company.id).join(Job).filter(Job.is_active.is_(True)).distinct().count()
            )
            sal = analytics.salary_distribution()
            total_w = sum(sal["counts"]) if sal["counts"] else 0
            avg_sal = None
            if total_w:
                vals = []
                for label, cnt in zip(sal["labels"], sal["counts"]):
                    try:
                        low = int(label.split("-")[0].replace("K以上", ""))
                        vals.append(low * cnt)
                    except Exception:
                        pass
                avg_sal = round(sum(vals) / total_w, 1) if vals else None

            return (
                f"## JobLens 数据总览\n\n"
                f"- 在招岗位：{total_jobs} 个\n"
                f"- 在招公司：{total_cos} 家\n"
                f"- 平均薪资：{avg_sal}K/月\n"
                f"- 核心城市：{', '.join(config.CORE_CITIES.keys())}\n"
                f"- 核心行业：{', '.join(config.CORE_INDUSTRIES)}\n"
                f"- 数据更新：每天凌晨 {config.CRAWL_CRON_HOUR}:00 自动爬取"
            )

    return "未知工具"


# ── Resources（可选）────────────────────────────────────

@server.list_resources()
async def list_resources() -> list[types.Resource]:
    return [
        types.Resource(
            uri="joblens://overview",
            name="JobLens 数据总览",
            description="当前数据库岗位数量、公司数、平均薪资等概览信息",
            mimeType="text/plain",
        ),
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    if str(uri) == "joblens://overview":
        return _sync_execute("get_overview", {})
    return "资源不存在"


# ── 启动 ─────────────────────────────────────────────────

async def _run_stdio():
    """stdio 传输：供 Claude Desktop / Cursor 等 MCP 客户端使用"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


async def _run_sse(host: str = "0.0.0.0", port: int = 8765):
    """SSE 传输：通过 HTTP 暴露 MCP Server，供 Web 客户端或远程调用使用
    端点：GET /sse  —— 建立 SSE 连接
    端点：POST /messages  —— 发送 JSON-RPC 消息
    """
    try:
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route, Mount
        import uvicorn

        sse_transport = SseServerTransport("/messages")

        async def handle_sse(request):
            async with sse_transport.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await server.run(
                    streams[0], streams[1],
                    server.create_initialization_options()
                )

        starlette_app = Starlette(routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages", app=sse_transport.handle_post_message),
        ])

        print(f"[MCP SSE] 启动于 http://{host}:{port}/sse")
        config_uvicorn = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
        await uvicorn.Server(config_uvicorn).serve()
    except ImportError as e:
        print(f"[MCP SSE] 缺少依赖 ({e})，请安装: pip install uvicorn starlette")


async def main():
    """默认以 stdio 模式启动；--sse 参数启动 SSE 模式"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sse", action="store_true", help="以 SSE HTTP 模式启动")
    parser.add_argument("--port", type=int, default=8765, help="SSE 端口（默认 8765）")
    args = parser.parse_args()

    if args.sse:
        await _run_sse(port=args.port)
    else:
        await _run_stdio()


if __name__ == "__main__":
    asyncio.run(main())
