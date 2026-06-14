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
    else:
        from openai import OpenAI
        kwargs = {"api_key": config.AI_API_KEY}
        if config.AI_BASE_URL:
            kwargs["base_url"] = config.AI_BASE_URL
        _client = OpenAI(**kwargs)
    return _client


def _stream_chunks(messages, system=None, max_tokens=800):
    """统一流式接口，yield 文本片段，屏蔽 SDK 差异"""
    client = _get_client()
    if config.AI_PROVIDER == "anthropic":
        kwargs = {"model": config.AI_MODEL, "max_tokens": max_tokens, "messages": messages}
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
            model=config.AI_MODEL, messages=msgs, max_tokens=max_tokens, stream=True
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
            model=config.AI_MODEL, max_tokens=max_tokens, messages=messages
        )
        return resp.content[0].text.strip()
    else:
        resp = client.chat.completions.create(
            model=config.AI_MODEL, messages=messages, max_tokens=max_tokens, stream=False
        )
        return resp.choices[0].message.content.strip()


def match_score(resume_text: str, jd_text: str) -> dict:
    """计算简历与JD的匹配评分（0-100）"""
    if not resume_text or not jd_text:
        return {"score": 0, "reason": "简历或JD为空", "matched": []}

    prompt = f"""你是一位资深HR，请评估以下简历与岗位的匹配程度。

岗位描述：
{jd_text[:2000]}

求职者简历：
{resume_text[:1500]}

请用JSON格式回答（只返回JSON，不要其他内容）：
{{
  "score": <0-100的整数>,
  "matched": ["已具备的关键技能/经验，最多3条，每条15字内"],
  "reason": "一句话总结匹配情况，30字内"
}}"""

    try:
        text = _call_once([{"role": "user", "content": prompt}], max_tokens=300)
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end])
    except Exception:
        return {"score": 0, "reason": "评分失败", "matched": []}


def gap_analysis_stream(resume_text: str, jd_text: str):
    """流式输出 Gap 分析"""
    if not resume_text or not jd_text:
        yield {"type": "text", "text": "请先在「我的简历」页面填写简历内容。"}
        yield {"type": "done"}
        return

    prompt = f"""你是一位职业发展顾问，请分析求职者简历与目标岗位的差距。

岗位要求：
{jd_text[:2000]}

求职者简历：
{resume_text[:1500]}

请按以下结构输出（Markdown格式）：

## 已具备的优势
列出简历中与JD匹配的技能/经验（3-5条）

## 需要补充的技能
**可快速补充（1-4周）**：通过项目实践可快速掌握的
**需要长期积累（1-3月+）**：需要系统学习的

## 建议行动计划
具体可执行的3步建议

每条不超过30字。"""

    try:
        for text in _stream_chunks([{"role": "user", "content": prompt}], max_tokens=800):
            yield {"type": "text", "text": text}
        yield {"type": "done"}
    except Exception as e:
        yield {"type": "error", "error": str(e)}


def company_intel_stream(jd_text: str, company_name: str, title: str):
    """从JD文本提取公司业务情报（流式）"""
    if not jd_text:
        yield {"type": "text", "text": "暂无岗位描述数据。"}
        yield {"type": "done"}
        return

    prompt = f"""你是一位商业分析师，请根据以下招聘JD推断该公司的核心业务方向。

公司：{company_name}  岗位：{title}
JD：{jd_text[:2000]}

请输出（Markdown格式）：

## 核心业务方向
从JD推断该团队在做什么产品/服务（2-3句）

## 技术栈偏向
提炼JD中核心技术要求，归纳方向

## 岗位真实需求
解读这个岗位实际最看重什么能力

## 面试重点预判
预测面试可能重点考察的2-3个方向"""

    try:
        for text in _stream_chunks([{"role": "user", "content": prompt}], max_tokens=600):
            yield {"type": "text", "text": text}
        yield {"type": "done"}
    except Exception as e:
        yield {"type": "error", "error": str(e)}


def interview_prep_stream(jd_text: str, company_name: str, title: str, resume_text: str = ""):
    """根据JD生成面试题预测和准备建议（流式）"""
    if not jd_text:
        yield {"type": "text", "text": "暂无岗位描述数据。"}
        yield {"type": "done"}
        return

    resume_section = f"\n\n求职者简历：\n{resume_text[:1000]}" if resume_text else ""
    prompt = f"""你是一位资深面试官，请根据以下岗位信息生成面试准备材料。

公司：{company_name}  岗位：{title}
JD要求：{jd_text[:2000]}{resume_section}

请输出（Markdown格式）：

## 核心考察方向（3-5个）
列出该岗位面试最看重的技能/能力方向

## 预测面试题

**技术题（5题）**
1. ...

**场景/行为题（3题）**
1. ...

## 重点备考提示
针对这个岗位的1-2条具体备考建议"""

    try:
        for text in _stream_chunks([{"role": "user", "content": prompt}], max_tokens=1000):
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
