# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""Rerank 模块：对混合检索召回的候选集做二次精排
提供两种实现：
  - rerank_score: 基于关键词密度 + 位置权重的轻量启发式排序（无需 API）
  - rerank_llm:   调用 LLM 对 top-N 逐条打分（高质量但有延迟）
"""

import json
import re
from typing import Optional

import config


def _tokenize(text: str) -> set:
    """简单分词，返回词集合"""
    return set(re.findall(r'[一-鿿]+|[A-Za-z0-9]+', text.lower()))


def rerank_score(query: str, job_ids: list, top_k: int = 20) -> list:
    """启发式 Rerank：计算查询词在标题/技能/描述中的覆盖度，对候选重排
    返回重排后的 job_id 列表（长度 <= top_k）
    """
    if not job_ids:
        return []

    from models import Job, app
    query_tokens = _tokenize(query)
    if not query_tokens:
        return job_ids[:top_k]

    scored = []
    with app.app_context():
        for rank, jid in enumerate(job_ids[:top_k * 3]):
            job = Job.query.filter_by(job_id=jid).first()
            if not job:
                continue

            title_tokens = _tokenize(job.title or "")
            tags = json.loads(job.skill_tags) if job.skill_tags else []
            tag_tokens = _tokenize(" ".join(tags))
            desc_tokens = _tokenize((job.description or "")[:500])

            # 分层覆盖率：标题命中权重最高
            title_cov = len(query_tokens & title_tokens) / max(len(query_tokens), 1)
            tag_cov = len(query_tokens & tag_tokens) / max(len(query_tokens), 1)
            desc_cov = len(query_tokens & desc_tokens) / max(len(query_tokens), 1)

            # 位置衰减：原始排名越靠前得分越高
            position_score = 1.0 / (rank + 1)

            final = title_cov * 3.0 + tag_cov * 2.0 + desc_cov * 1.0 + position_score * 0.5
            scored.append((jid, final))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [jid for jid, _ in scored[:top_k]]


def rerank_llm(query: str, job_ids: list, top_k: int = 10) -> list:
    """LLM Rerank：让模型对 top-N 候选逐条打相关性分（0-10），精排后返回
    仅对前 15 条候选执行，避免 token 消耗过大
    """
    candidates = job_ids[:15]
    if not candidates:
        return []

    from models import Job, app
    import analytics

    items = []
    with app.app_context():
        for jid in candidates:
            job = Job.query.filter_by(job_id=jid).first()
            if not job:
                continue
            tags = json.loads(job.skill_tags) if job.skill_tags else []
            items.append({
                "id": jid,
                "title": job.title,
                "company": job.company.name if job.company else "",
                "salary": analytics._format_salary(job),
                "tags": tags[:6],
                "desc_snippet": (job.description or "")[:200],
            })

    if not items:
        return candidates[:top_k]

    prompt = f"""用户搜索意图：{query}

以下是 {len(items)} 个候选岗位，请对每个岗位与用户意图的相关性打分（0-10），只返回 JSON 数组：

{json.dumps(items, ensure_ascii=False)}

返回格式（只返回JSON）：
[{{"id": "job_id", "score": 8}}, ...]
按 score 降序排列。"""

    try:
        from ai_features import _call_once
        resp = _call_once([{"role": "user", "content": prompt}], max_tokens=400)
        start = resp.find("[")
        end = resp.rfind("]") + 1
        ranked = json.loads(resp[start:end])
        ordered_ids = [r["id"] for r in ranked if r.get("id")]
        # 补全未被 LLM 返回的 id
        seen = set(ordered_ids)
        for jid in candidates:
            if jid not in seen:
                ordered_ids.append(jid)
        return ordered_ids[:top_k]
    except Exception:
        return candidates[:top_k]
