# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""AI 功能模块：支持 Anthropic Claude 和 OpenAI 兼容接口（DeepSeek 等）
通过 AI_PROVIDER 环境变量切换：anthropic（默认） / openai"""

import json
import config

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if config.AI_PROVIDER == "anthropic":
        import anthropic
        kwargs = {"api_key": config.AI_API_KEY}
        if config.AI_BASE_URL:
            kwargs["base_url"] = config.AI_BASE_URL
        _client = anthropic.Anthropic(**kwargs)
    elif config.AI_PROVIDER == "ollama":
        from openai import OpenAI
        _client = OpenAI(
            api_key="ollama",
            base_url=config.OLLAMA_BASE_URL,
        )
    else:
        from openai import OpenAI
        kwargs = {"api_key": config.AI_API_KEY}
        if config.AI_BASE_URL:
            kwargs["base_url"] = config.AI_BASE_URL
        _client = OpenAI(**kwargs)
    return _client


def _effective_model():
    if config.AI_PROVIDER == "ollama":
        return config.OLLAMA_MODEL
    return config.AI_MODEL


def _stream_chunks(messages, system=None, max_tokens=800):
    """统一流式接口，yield 文本片段，屏蔽 SDK 差异"""
    client = _get_client()
    if config.AI_PROVIDER == "anthropic":
        kwargs = {"model": _effective_model(), "max_tokens": max_tokens, "messages": messages}
        if system:
            kwargs["system"] = system
        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text
    else:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        stream = client.chat.completions.create(
            model=_effective_model(), messages=msgs, max_tokens=max_tokens, stream=True
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


def _call_once(messages, max_tokens=300):
    """非流式单次调用，返回文本"""
    client = _get_client()
    if config.AI_PROVIDER == "anthropic":
        resp = client.messages.create(
            model=_effective_model(), max_tokens=max_tokens, messages=messages
        )
        return resp.content[0].text.strip()
    else:
        resp = client.chat.completions.create(
            model=_effective_model(), messages=messages, max_tokens=max_tokens, stream=False
        )
        return resp.choices[0].message.content.strip()


def _call_structured(messages, schema: dict, max_tokens=500) -> dict:
    """结构化输出：强制模型按 JSON Schema 返回，失败时 fallback 到正则提取"""
    client = _get_client()
    if config.AI_PROVIDER == "anthropic":
        resp = client.messages.create(
            model=_effective_model(), max_tokens=max_tokens, messages=messages
        )
        raw = resp.content[0].text.strip()
    elif config.AI_PROVIDER == "openai" and config.AI_BASE_URL == "":
        # OpenAI 原生支持 response_format=json_schema
        resp = client.chat.completions.create(
            model=_effective_model(), messages=messages, max_tokens=max_tokens,
            response_format={"type": "json_schema", "json_schema": {"name": "output", "schema": schema, "strict": True}},
        )
        raw = resp.choices[0].message.content.strip()
    else:
        resp = client.chat.completions.create(
            model=_effective_model(), messages=messages, max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content.strip()
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        return json.loads(raw[start:end])
    except Exception:
        return {}


_MATCH_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "description": "匹配分数 0-100"},
        "matched": {"type": "array", "items": {"type": "string"}, "description": "已具备的关键技能，最多3条"},
        "reason": {"type": "string", "description": "一句话总结，30字内"},
    },
    "required": ["score", "matched", "reason"],
    "additionalProperties": False,
}


def match_score(resume_text: str, jd_text: str) -> dict:
    """计算简历与JD的匹配评分（0-100），使用 PromptTemplate + 结构化输出"""
    if not resume_text or not jd_text:
        return {"score": 0, "reason": "简历或JD为空", "matched": []}

    from prompt_template import library
    messages = library.get("match_score").to_messages(
        jd_text=jd_text[:2000],
        resume_text=resume_text[:1500],
    )
    try:
        result = _call_structured(messages, _MATCH_SCORE_SCHEMA, max_tokens=300)
        if result and "score" in result:
            return result
        raise ValueError("empty")
    except Exception:
        return {"score": 0, "reason": "评分失败", "matched": []}


def gap_analysis_stream(resume_text: str, jd_text: str):
    """流式输出 Gap 分析（使用 PromptTemplate）"""
    if not resume_text or not jd_text:
        yield {"type": "text", "text": "请先在「我的简历」页面填写简历内容。"}
        yield {"type": "done"}
        return

    from prompt_template import library
    messages = library.get("gap_analysis").to_messages(
        jd_text=jd_text[:2000],
        resume_text=resume_text[:1500],
    )
    try:
        for text in _stream_chunks(messages, max_tokens=800):
            yield {"type": "text", "text": text}
        yield {"type": "done"}
    except Exception as e:
        yield {"type": "error", "error": str(e)}


def company_intel_stream(jd_text: str, company_name: str, title: str):
    """从JD文本提取公司业务情报（流式，使用 PromptTemplate）"""
    if not jd_text:
        yield {"type": "text", "text": "暂无岗位描述数据。"}
        yield {"type": "done"}
        return

    from prompt_template import library
    messages = library.get("company_intel").to_messages(
        company=company_name,
        title=title,
        jd_text=jd_text[:2000],
    )
    try:
        for text in _stream_chunks(messages, max_tokens=600):
            yield {"type": "text", "text": text}
        yield {"type": "done"}
    except Exception as e:
        yield {"type": "error", "error": str(e)}


def interview_prep_stream(jd_text: str, company_name: str, title: str, resume_text: str = ""):
    """根据JD生成面试题预测和准备建议（流式，使用 PromptTemplate）"""
    if not jd_text:
        yield {"type": "text", "text": "暂无岗位描述数据。"}
        yield {"type": "done"}
        return

    from prompt_template import library
    resume_section = f"\n\n求职者简历：\n{resume_text[:1000]}" if resume_text else ""
    messages = library.get("interview_prep").to_messages(
        company=company_name,
        title=title,
        jd_text=jd_text[:2000],
        resume_section=resume_section,
    )
    try:
        for text in _stream_chunks(messages, max_tokens=1000):
            yield {"type": "text", "text": text}
        yield {"type": "done"}
    except Exception as e:
        yield {"type": "error", "error": str(e)}


def chat_stream(question: str, history: list, context_jobs: list = None):
    """AI 对话流式输出"""
    system = "你是 JobLens 的 AI 求职助手，专注于帮用户分析招聘市场、解读岗位要求、制定求职策略。回答简洁专业，多用数据和具体建议。"

    context_text = ""
    if context_jobs:
        context_text = "\n\n当前岗位数据摘要：\n"
        for j in context_jobs[:10]:
            context_text += f"- {j.get('title')} @ {j.get('company_name')} | {j.get('salary')} | {j.get('city')}\n"

    messages = [{"role": h["role"], "content": h["content"]} for h in history[-6:]]
    messages.append({"role": "user", "content": question + context_text})

    try:
        for text in _stream_chunks(messages, system=system, max_tokens=800):
            yield {"type": "text", "text": text}
        yield {"type": "done"}
    except Exception as e:
        yield {"type": "error", "error": str(e)}
