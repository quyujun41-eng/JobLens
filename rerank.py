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


def rerank_cohere(query: str, job_ids: list, top_k: int = 10) -> list:
    """Cohere Rerank API 精排（需设置 COHERE_API_KEY 环境变量）
    默认模型 rerank-multilingual-v3.0，支持中文；fallback 到 rerank_score
    """
    if not config.COHERE_API_KEY:
        return rerank_score(query, job_ids, top_k)
    candidates = job_ids[:50]
    if not candidates:
        return []

    from models import Job, app
    docs, doc_ids = [], []
    with app.app_context():
        for jid in candidates:
            job = Job.query.filter_by(job_id=jid).first()
            if not job:
                continue
            tags = json.loads(job.skill_tags) if job.skill_tags else []
            text = f"{job.title} | {' '.join(tags[:6])} | {(job.description or '')[:300]}"
            docs.append(text)
            doc_ids.append(jid)

    if not docs:
        return candidates[:top_k]

    try:
        import cohere
        co = cohere.Client(config.COHERE_API_KEY)
        rerank_model = config.RERANK_MODEL or "rerank-multilingual-v3.0"
        response = co.rerank(query=query, documents=docs, model=rerank_model, top_n=top_k)
        return [doc_ids[r.index] for r in response.results]
    except Exception:
        return rerank_score(query, job_ids, top_k)


def rerank_flagembedding(query: str, job_ids: list, top_k: int = 10) -> list:
    """BGE Reranker 本地精排（需安装 FlagEmbedding，首次下载模型约400MB）
    默认模型 BAAI/bge-reranker-base，支持中英文；fallback 到 rerank_score
    """
    candidates = job_ids[:50]
    if not candidates:
        return []

    from models import Job, app
    docs, doc_ids = [], []
    with app.app_context():
        for jid in candidates:
            job = Job.query.filter_by(job_id=jid).first()
            if not job:
                continue
            text = f"{job.title} {(job.description or '')[:300]}"
            docs.append(text)
            doc_ids.append(jid)

    if not docs:
        return candidates[:top_k]

    try:
        from FlagEmbedding import FlagReranker
        model_name = config.RERANK_MODEL or "BAAI/bge-reranker-base"
        reranker = FlagReranker(model_name, use_fp16=True)
        pairs = [(query, d) for d in docs]
        scores = reranker.compute_score(pairs, normalize=True)
        if isinstance(scores, (int, float)):
            scores = [scores]
        ranked = sorted(zip(doc_ids, scores), key=lambda x: x[1], reverse=True)
        return [jid for jid, _ in ranked[:top_k]]
    except Exception:
        return rerank_score(query, job_ids, top_k)


def rerank(query: str, job_ids: list, top_k: int = 10, provider: str = None) -> list:
    """统一 Rerank 入口：根据 RERANK_PROVIDER 自动选择实现
    provider 参数优先于 RERANK_PROVIDER 环境变量
    可选值：score（默认）| llm | cohere | flagembedding
    """
    p = provider or config.RERANK_PROVIDER
    if p == "cohere":
        return rerank_cohere(query, job_ids, top_k)
    if p == "flagembedding":
        return rerank_flagembedding(query, job_ids, top_k)
    if p == "llm":
        return rerank_llm(query, job_ids, top_k)
    return rerank_score(query, job_ids, top_k)
