# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""Function Calling Agent：Router分流 + 并行工具调用 + SummaryMemory + TokenWindow"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

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


# ── TokenWindow：滑动窗口记忆 ───────────────────────────────────────────

_TOKEN_WINDOW_LIMIT = 3000  # 历史上下文 token 预算


def _count_tokens(text: str) -> int:
    chinese = len(re.findall(r'[一-鿿]', text))
    english = len(re.findall(r'[A-Za-z]+', text))
    return int(chinese * 1.5 + english * 1.3)


def apply_token_window(history: list, max_tokens: int = _TOKEN_WINDOW_LIMIT) -> list:
    """从最新消息往前累计 token，超出预算则截断旧消息"""
    if not history:
        return []
    total, result = 0, []
    for msg in reversed(history):
        t = _count_tokens(msg.get("content", ""))
        if total + t > max_tokens and result:
            break
        result.insert(0, msg)
        total += t
    return result


# ── 工具缓存 ─────────────────────────────────────────────────────────────

_tool_cache: dict = {}
_CACHE_TTL = 300  # 5分钟缓存


def _cached_execute_tool(name: str, inp: dict, resume: str = "") -> str:
    """带缓存和超时的工具执行（只缓存无副作用的查询类工具）"""
    cacheable = {"search_jobs", "get_job_detail", "get_market_stats"}
    cache_key = f"{name}:{json.dumps(inp, sort_keys=True)}"

    if name in cacheable:
        entry = _tool_cache.get(cache_key)
        if entry and (time.time() - entry["ts"] < _CACHE_TTL):
            return entry["result"]

    result = _execute_tool(name, inp, resume)

    if name in cacheable:
        _tool_cache[cache_key] = {"result": result, "ts": time.time()}

    return result


# ── Router：意图分类 ─────────────────────────────────────────────────────

_INTENT_LABELS = {
    "job_search": ["搜索", "找工作", "哪些岗位", "招聘", "职位", "推荐工作", "职缺"],
    "market_analysis": ["行情", "市场", "薪资", "趋势", "热门技能", "平均薪资", "排行", "分布"],
    "resume_match": ["匹配", "简历", "适合", "评分", "gap", "差距", "我的技能"],
    "interview": ["面试", "面经", "准备面试", "面试题", "考察什么"],
}


def classify_intent(question: str) -> str:
    """快速本地意图分类（无需LLM调用），返回 intent label"""
    q = question.lower()
    for intent, keywords in _INTENT_LABELS.items():
        if any(kw in q for kw in keywords):
            return intent
    return "general"


# ── SummaryMemory：长对话压缩 ────────────────────────────────────────────

_SUMMARY_THRESHOLD = 20  # 消息条数超过此值时触发压缩


def _maybe_summarize(session_id: str, history: list) -> list:
    """当历史消息过长时，调用 LLM 压缩旧消息为摘要，保留最近6条"""
    if len(history) <= _SUMMARY_THRESHOLD:
        return history

    from models import ChatSession, db
    old_msgs = history[:-6]
    recent_msgs = history[-6:]

    # 拼接旧消息为文本
    text = "\n".join(
        f"[{m['role']}]: {m['content'][:300]}" for m in old_msgs
    )
    prompt = f"请将以下对话历史压缩为一段100字以内的摘要，保留关键信息：\n\n{text}"
    try:
        from ai_features import _call_once
        summary = _call_once([{"role": "user", "content": prompt}], max_tokens=200)
        with flask_app.app_context():
            sess = ChatSession.query.get(session_id)
            if sess:
                sess.summary = summary
                db.session.commit()
        # 将摘要作为第一条 assistant 消息注入
        summary_msg = {"role": "assistant", "content": f"[对话摘要] {summary}"}
        return [summary_msg] + recent_msgs
    except Exception:
        return recent_msgs


# ── 工具执行 ────────────────────────────────────────────────────────────

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


# ── 并行工具执行 ─────────────────────────────────────────────────────────

_TOOL_TIMEOUT = 15  # 单个工具调用超时秒数


def _execute_tools_parallel(tool_blocks, resume: str) -> dict:
    """并行执行多个工具调用（带缓存+超时），返回 {tool_use_id: result}"""
    results = {}
    with ThreadPoolExecutor(max_workers=len(tool_blocks)) as pool:
        futures = {
            pool.submit(_cached_execute_tool, b.name, b.input, resume): b
            for b in tool_blocks
        }
        for future in as_completed(futures, timeout=_TOOL_TIMEOUT + 5):
            b = futures[future]
            try:
                results[b.id] = future.result(timeout=_TOOL_TIMEOUT)
            except Exception as e:
                results[b.id] = f"工具执行出错: {e}"
    return results


def _execute_oai_tools_parallel(tool_calls, resume: str) -> dict:
    """OpenAI 格式并行工具执行（带缓存+超时），返回 {tool_call_id: result}"""
    results = {}
    with ThreadPoolExecutor(max_workers=len(tool_calls)) as pool:
        futures = {
            pool.submit(_cached_execute_tool, tc.function.name,
                        json.loads(tc.function.arguments), resume): tc
            for tc in tool_calls
        }
        for future in as_completed(futures, timeout=_TOOL_TIMEOUT + 5):
            tc = futures[future]
            try:
                results[tc.id] = future.result(timeout=_TOOL_TIMEOUT)
            except Exception as e:
                results[tc.id] = f"工具执行出错: {e}"
    return results


# ── Agent 主入口 ─────────────────────────────────────────────────────────

def agent_stream(question: str, history: list, resume: str = "", session_id: str = ""):
    """Agent主入口，yield dict：tool_call / tool_result / text / done
    自动路由意图，对长对话应用 SummaryMemory 压缩"""
    intent = classify_intent(question)

    system = (
        "你是 JobLens AI 求职助手，拥有实时岗位数据库访问权限。\n"
        "规则：\n"
        "1. 优先调用工具获取真实数据，不编造岗位或薪资数字\n"
        "2. 问具体岗位时先 search_jobs，需要详情再 get_job_detail\n"
        "3. 用户问匹配度时调用 match_resume\n"
        "4. 回答简洁专业，用数据支撑观点，重点加粗"
    )

    # SummaryMemory：消息数过多时压缩旧历史
    if session_id and len(history) > _SUMMARY_THRESHOLD:
        history = _maybe_summarize(session_id, history)

    # TokenWindow：在 SummaryMemory 之后再做 token 预算裁剪
    history = apply_token_window(history)

    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": question})

    yield {"type": "intent", "intent": intent}

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

        # 并行执行所有工具调用
        for b in tool_blocks:
            yield {"type": "tool_call", "tool": b.name, "input": b.input}

        parallel_results = _execute_tools_parallel(tool_blocks, resume)

        tool_results = []
        for b in tool_blocks:
            result = parallel_results.get(b.id, "执行超时")
            yield {"type": "tool_result", "tool": b.name, "preview": result[:200]}
            tool_results.append({"type": "tool_result", "tool_use_id": b.id, "content": result})

        # 构建下一轮消息（ContentBlock → dict）
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
    model = config.OLLAMA_MODEL if config.AI_PROVIDER == "ollama" else config.AI_MODEL
    base_url = config.OLLAMA_BASE_URL if config.AI_PROVIDER == "ollama" else (config.AI_BASE_URL or None)
    api_key = "ollama" if config.AI_PROVIDER == "ollama" else config.AI_API_KEY
    client = OpenAI(api_key=api_key, base_url=base_url)

    oai_tools = [{"type": "function", "function": {
        "name": t["name"], "description": t["description"],
        "parameters": t["input_schema"],
    }} for t in TOOLS]
    msgs = [{"role": "system", "content": system}] + list(messages)

    for _round in range(6):
        resp = client.chat.completions.create(
            model=model, max_tokens=1500,
            tools=oai_tools, messages=msgs,
        )
        msg = resp.choices[0].message
        msgs.append(msg)

        if not msg.tool_calls:
            for ch in (msg.content or ""):
                yield {"type": "text", "text": ch}
            yield {"type": "done"}
            return

        # 并行执行所有工具调用
        for tc in msg.tool_calls:
            inp = json.loads(tc.function.arguments)
            yield {"type": "tool_call", "tool": tc.function.name, "input": inp}

        parallel_results = _execute_oai_tools_parallel(msg.tool_calls, resume)

        for tc in msg.tool_calls:
            result = parallel_results.get(tc.id, "执行超时")
            yield {"type": "tool_result", "tool": tc.function.name, "preview": result[:200]}
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    yield {"type": "text", "text": "（已完成多轮工具调用）"}
    yield {"type": "done"}
