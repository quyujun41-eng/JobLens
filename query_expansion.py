# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""Query Expansion：用 LLM 把用户查询扩展成多个语义等价查询，提升召回率
最终通过 RRF 融合多路检索结果"""

import json
from typing import Optional
import config

_expansion_cache: dict = {}


def expand_query(query: str, n: int = 3) -> list:
    """将查询扩展为 n 个语义等价或相关的查询变体，返回 [原始query, 变体1, 变体2, ...]
    结果带本地缓存（同一个 query 不重复调用 LLM）
    """
    if not query or not query.strip():
        return [query]

    cache_key = f"{query}:{n}"
    if cache_key in _expansion_cache:
        return _expansion_cache[cache_key]

    from prompt_template import library
    messages = library.get("query_expansion").to_messages(query=query, n=n)

    try:
        from ai_features import _call_once
        resp = _call_once(messages, max_tokens=150)
        start = resp.find("[")
        end = resp.rfind("]") + 1
        variants = json.loads(resp[start:end])
        result = [query] + [v for v in variants if isinstance(v, str) and v != query]
    except Exception:
        result = [query]

    _expansion_cache[cache_key] = result
    return result


def multi_query_search(query: str, top_k: int = 50) -> list:
    """扩展查询 → 多路检索 → RRF 融合，返回 job_id 列表"""
    queries = expand_query(query, n=2)

    import search as bm25_mod
    from vector_search import vector_search
    bm25_mod.rebuild_index_if_needed()

    K = 60
    scores: dict = {}

    for q in queries:
        bm25_ids = bm25_mod.search(q, top_k=top_k)
        vec_results = vector_search(q, top_k=top_k)
        vec_ids = [jid for jid, _ in vec_results]

        for rank, jid in enumerate(bm25_ids):
            scores[jid] = scores.get(jid, 0.0) + 1.0 / (K + rank + 1)
        for rank, jid in enumerate(vec_ids):
            scores[jid] = scores.get(jid, 0.0) + 1.0 / (K + rank + 1)

    return sorted(scores, key=lambda x: scores[x], reverse=True)[:top_k]
