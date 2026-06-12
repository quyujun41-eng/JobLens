# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""AI 功能模块：匹配评分、Gap 分析、公司情报、AI 对话（均基于 Claude API）"""

import json
import anthropic
import config

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(
            api_key=config.ANTHROPIC_API_KEY,
            base_url=config.ANTHROPIC_BASE_URL,
        )
    return _client


def match_score(resume_text: str, jd_text: str) -> dict:
    """计算简历与JD的匹配评分（0-100），返回分数和简短理由"""
    if not resume_text or not jd_text:
        return {"score": 0, "reason": "简历或JD为空"}

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
        resp = _get_client().messages.create(
            model=config.AI_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # 提取JSON
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end])
    except Exception:
        return {"score": 0, "reason": "评分失败", "matched": []}


def gap_analysis_stream(resume_text: str, jd_text: str):
    """流式输出 Gap 分析结果（SSE 格式的 generator）"""
    if not resume_text or not jd_text:
        yield {"type": "text", "text": "请先在「我的简历」页面填写简历内容。"}
        yield {"type": "done"}
        return

    prompt = f"""你是一位职业发展顾问，请分析求职者简历与目标岗位的差距。

岗位要求：
{jd_text[:2000]}

求职者简历：
{resume_text[:1500]}

请按以下结构输出分析（使用 Markdown 格式）：

## 已具备的优势
列出简历中与JD匹配的技能/经验（3-5条）

## 需要补充的技能
分两级：
**可快速补充（1-4周）**：列出可以通过项目实践快速掌握的技能
**需要长期积累（1-3月+）**：列出需要系统学习的技能

## 建议行动计划
给出具体可执行的3步建议

保持语言精炼，每条不超过30字。"""

    try:
        with _get_client().messages.stream(
            model=config.AI_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                yield {"type": "text", "text": text}
        yield {"type": "done"}
    except Exception as e:
        yield {"type": "error", "error": str(e)}


def company_intel_stream(jd_text: str, company_name: str, title: str):
    """从JD文本中提取公司业务情报（流式）"""
    if not jd_text:
        yield {"type": "text", "text": "暂无岗位描述数据。"}
        yield {"type": "done"}
        return

    prompt = f"""你是一位商业分析师，请根据以下招聘JD推断该公司的核心业务方向和技术栈。

公司名称：{company_name}
岗位：{title}
JD内容：
{jd_text[:2000]}

请输出（Markdown格式，语言精炼）：

## 核心业务方向
从JD中推断该公司/团队主要在做什么产品或服务（2-3句）

## 技术栈偏向
提炼JD中提到的核心技术要求，归纳技术方向

## 岗位真实需求
解读这个岗位实际上最看重什么能力（区别于表面要求）

## 面试重点预判
根据JD和业务方向，预测面试可能重点考察的2-3个方向"""

    try:
        with _get_client().messages.stream(
            model=config.AI_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                yield {"type": "text", "text": text}
        yield {"type": "done"}
    except Exception as e:
        yield {"type": "error", "error": str(e)}


def chat_stream(question: str, history: list, context_jobs: list = None):
    """AI 对话流式输出，可附带岗位数据作为上下文"""
    system = """你是 JobLens 的 AI 求职助手，专注于帮助用户分析招聘市场、解读岗位要求、制定求职策略。
回答要简洁专业，多用数据和具体建议，避免空话。"""

    context_text = ""
    if context_jobs:
        context_text = "\n\n当前数据库中的岗位摘要：\n"
        for j in context_jobs[:10]:
            context_text += f"- {j.get('title')} @ {j.get('company_name')} | {j.get('salary')} | {j.get('city')}\n"

    messages = []
    for h in history[-6:]:
        messages.append({"role": h["role"], "content": h["content"]})

    user_content = question
    if context_text:
        user_content = f"{question}\n{context_text}"
    messages.append({"role": "user", "content": user_content})

    try:
        with _get_client().messages.stream(
            model=config.AI_MODEL,
            max_tokens=800,
            system=system,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield {"type": "text", "text": text}
        yield {"type": "done"}
    except Exception as e:
        yield {"type": "error", "error": str(e)}
