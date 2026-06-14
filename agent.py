# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""Function Calling Agent：5个工具让Claude自主决定调用顺序和次数"""

import json
import config
import analytics
from models import Job, app as flask_app

TOOLS = [
    {
        "name": "search_jobs",
        "description": "搜索招聘岗位，支持关键词、城市、薪资筛选，返回岗位列表（含job_id）",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词，如 RAG、Agent、Python"},
                "city": {"type": "string", "description": "城市，如 深圳、北京、上海"},
                "salary_min": {"type": "number", "description": "最低薪资 K/月"},
                "salary_max": {"type": "number", "description": "最高薪资 K/月"},
                "top_k": {"type": "integer", "description": "返回数量，默认10，最多50"},
            },
        },
    },
    {
        "name": "get_job_detail",
        "description": "获取单个岗位的完整JD、技能要求、公司信息",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "岗位ID，从search_jobs结果中获取"},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "match_resume",
        "description": "将用户简历与指定岗位JD做匹配评分（0-100分），输出已具备/缺失技能",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "岗位ID"},
                "resume": {"type": "string", "description": "简历文本，不传则使用用户已上传的简历"},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "get_market_stats",
        "description": "获取市场统计：薪资分布、热门技能排行、企业薪资排名、招聘趋势",
        "input_schema": {
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
    },
    {
        "name": "generate_interview_prep",
        "description": "根据岗位JD生成面试题预测和准备建议，可结合简历给出针对性指导",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "岗位ID"},
                "resume": {"type": "string", "description": "用户简历（可选）"},
            },
            "required": ["job_id"],
        },
    },
]


def _execute_tool(name: str, inp: dict, resume: str = "") -> str:
    """执行工具，返回结果文本"""
    with flask_app.app_context():
        if name == "search_jobs":
            keyword = inp.get("keyword")
            bm25_ids = None
            if keyword:
                try:
                    from vector_search import hybrid_search
                    bm25_ids = hybrid_search(keyword, top_k=50)
                except Exception:
                    try:
                        import search as bm25
                        bm25.rebuild_index_if_needed()
                        bm25_ids = bm25.search(keyword, top_k=50)
                    except Exception:
                        pass
            result = analytics.job_list(
                page=1, per_page=min(int(inp.get("top_k", 10)), 50),
                keyword=keyword, city=inp.get("city"),
                salary_min=inp.get("salary_min"), salary_max=inp.get("salary_max"),
                bm25_ids=bm25_ids,
            )
            items = result.get("items", [])
            lines = [f"共 {result['total']} 个匹配岗位，返回前 {len(items)} 条："]
            for j in items:
                lines.append(f"[{j['job_id']}] {j['title']} @ {j['company_name']} | {j['salary']} | {j['city']}")
            return "\n".join(lines)

        elif name == "get_job_detail":
            job = Job.query.filter_by(job_id=inp.get("job_id", "")).first()
            if not job:
                return "岗位不存在"
            tags = json.loads(job.skill_tags) if job.skill_tags else []
            return json.dumps({
                "title": job.title,
                "company": job.company.name if job.company else "",
                "salary": analytics._format_salary(job),
                "city": job.city,
                "experience": analytics._format_experience(job),
                "education": job.education_req,
                "skill_tags": tags,
                "description": (job.description or "")[:2000],
            }, ensure_ascii=False, indent=2)

        elif name == "match_resume":
            job = Job.query.filter_by(job_id=inp.get("job_id", "")).first()
            if not job:
                return "岗位不存在"
            resume_text = inp.get("resume") or resume
            if not resume_text:
                return "用户未上传简历，无法评分"
            from ai_features import match_score
            result = match_score(resume_text, job.description or "")
            return json.dumps(result, ensure_ascii=False)

        elif name == "get_market_stats":
            st = inp.get("stat_type", "salary")
            if st == "salary":
                d = analytics.salary_distribution()
                return "薪资分布：\n" + "\n".join(
                    f"  {l}: {c}个岗位" for l, c in zip(d["labels"], d["counts"]))
            elif st == "skills":
                d = analytics.skill_ranking(top_n=15)
                return "技能需求TOP15：\n" + "\n".join(
                    f"  {i+1}. {l}（{c}个岗位）"
                    for i, (l, c) in enumerate(zip(d["labels"], d["counts"])))
            elif st == "companies":
                d = analytics.company_salary_ranking(top_n=10)
                return "企业薪资TOP10：\n" + "\n".join(
                    f"  {i+1}. {n}（均薪{s}K，{c}个岗位）"
                    for i, (n, s, c) in enumerate(zip(d["labels"], d["avg_salary"], d["job_count"])))
            elif st == "trend":
                d = analytics.hiring_trend()
                if not d.get("labels"):
                    return "暂无趋势数据"
                lines = ["招聘趋势（按月）："]
                for m, cnt, sal in zip(d["labels"], d["job_count"], d["avg_salary"]):
                    sal_str = f"均薪{sal}K" if sal else "薪资待定"
                    lines.append(f"  {m}: {cnt}个岗位，{sal_str}")
                return "\n".join(lines)
            return "未知统计类型"

        elif name == "generate_interview_prep":
            job = Job.query.filter_by(job_id=inp.get("job_id", "")).first()
            if not job:
                return "岗位不存在"
            tags = json.loads(job.skill_tags) if job.skill_tags else []
            return json.dumps({
                "job_title": job.title,
                "company": job.company.name if job.company else "",
                "skill_tags": tags,
                "description": (job.description or "")[:2000],
                "has_resume": bool(inp.get("resume") or resume),
            }, ensure_ascii=False)

    return "工具执行失败"


def agent_stream(question: str, history: list, resume: str = ""):
    """Agent主入口，yield dict：tool_call / tool_result / text / done"""
    system = (
        "你是 JobLens AI 求职助手，拥有实时岗位数据库访问权限。\n"
        "规则：\n"
        "1. 优先调用工具获取真实数据，不编造岗位或薪资数字\n"
        "2. 问具体岗位时先 search_jobs，需要详情再 get_job_detail\n"
        "3. 用户问匹配度时调用 match_resume\n"
        "4. 回答简洁专业，用数据支撑观点，重点加粗"
    )
    messages = [{"role": h["role"], "content": h["content"]} for h in history[-8:]]
    messages.append({"role": "user", "content": question})

    if config.AI_PROVIDER == "anthropic":
        yield from _anthropic_loop(messages, system, resume)
    else:
        yield from _openai_loop(messages, system, resume)


def _anthropic_loop(messages, system, resume):
    import anthropic
    client = anthropic.Anthropic(api_key=config.AI_API_KEY)
    msgs = list(messages)

    for _round in range(6):
        resp = client.messages.create(
            model=config.AI_MODEL, max_tokens=1500,
            system=system, tools=TOOLS, messages=msgs,
        )
        tool_blocks = [b for b in resp.content if b.type == "tool_use"]
        text_blocks = [b for b in resp.content if b.type == "text"]

        if not tool_blocks:
            for b in text_blocks:
                yield {"type": "text", "text": b.text}
            yield {"type": "done"}
            return

        # 执行工具
        tool_results = []
        for b in tool_blocks:
            yield {"type": "tool_call", "tool": b.name, "input": b.input}
            result = _execute_tool(b.name, b.input, resume)
            yield {"type": "tool_result", "tool": b.name, "preview": result[:200]}
            tool_results.append({"type": "tool_result", "tool_use_id": b.id, "content": result})

        # 构建下一轮消息（把ContentBlock转为dict）
        assistant_content = []
        for b in resp.content:
            if b.type == "text":
                assistant_content.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                assistant_content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        msgs.append({"role": "assistant", "content": assistant_content})
        msgs.append({"role": "user", "content": tool_results})

    yield {"type": "text", "text": "（已完成多轮工具调用）"}
    yield {"type": "done"}


def _openai_loop(messages, system, resume):
    from openai import OpenAI
    client = OpenAI(api_key=config.AI_API_KEY, base_url=config.AI_BASE_URL or None)
    oai_tools = [{"type": "function", "function": {
        "name": t["name"], "description": t["description"],
        "parameters": t["input_schema"],
    }} for t in TOOLS]
    msgs = [{"role": "system", "content": system}] + list(messages)

    for _round in range(6):
        resp = client.chat.completions.create(
            model=config.AI_MODEL, max_tokens=1500,
            tools=oai_tools, messages=msgs,
        )
        msg = resp.choices[0].message
        msgs.append(msg)

        if not msg.tool_calls:
            for ch in (msg.content or ""):
                yield {"type": "text", "text": ch}
            yield {"type": "done"}
            return

        for tc in msg.tool_calls:
            inp = json.loads(tc.function.arguments)
            yield {"type": "tool_call", "tool": tc.function.name, "input": inp}
            result = _execute_tool(tc.function.name, inp, resume)
            yield {"type": "tool_result", "tool": tc.function.name, "preview": result[:200]}
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    yield {"type": "text", "text": "（已完成多轮工具调用）"}
    yield {"type": "done"}
