# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""TF-IDF向量检索 + BM25混合搜索（RRF融合）
等部署到GPU服务器后可将TF-IDF替换为 sentence-transformers + Qdrant，接口不变"""

import json
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

_vectorizer: TfidfVectorizer = None
_matrix = None
_job_ids: list = []
_indexed_count: int = -1


def _preprocess(text: str) -> str:
    """分词：中文逐字切分，英文/数字保留，转小写"""
    if not text:
        return ""
    tokens = re.findall(r'[一-鿿]+|[A-Za-z][A-Za-z0-9]*|\d+', text)
    result = []
    for t in tokens:
        if any('一' <= c <= '鿿' for c in t):
            result.extend(list(t))
        else:
            result.append(t.lower())
    return " ".join(result)


def build_index():
    """从数据库全量重建TF-IDF索引"""
    global _vectorizer, _matrix, _job_ids, _indexed_count
    from models import Job, app
    with app.app_context():
        jobs = Job.query.filter_by(is_active=True).all()
        _indexed_count = len(jobs)
        if not jobs:
            _vectorizer = None
            _matrix = None
            _job_ids = []
            return

        corpus, ids = [], []
        for j in jobs:
            tags = " ".join(json.loads(j.skill_tags) if j.skill_tags else [])
            # 标题权重×3，技能×2，关键词×2，描述×1
            text = " ".join([
                (j.title or "") * 3,
                tags * 2,
                (j.source_keyword or "") * 2,
                j.description or "",
            ])
            corpus.append(_preprocess(text))
            ids.append(j.job_id)

        _job_ids = ids
        _vectorizer = TfidfVectorizer(max_features=8000, min_df=1, sublinear_tf=True)
        _matrix = _vectorizer.fit_transform(corpus)
    print(f"[向量索引] 已建立 {_indexed_count} 个岗位的TF-IDF索引")


def rebuild_if_needed():
    global _indexed_count
    from models import Job, app
    with app.app_context():
        current = Job.query.filter_by(is_active=True).count()
    if current != _indexed_count or _vectorizer is None:
        build_index()


def vector_search(query: str, top_k: int = 50) -> list:
    """TF-IDF向量语义搜索，返回 [(job_id, score), ...]"""
    rebuild_if_needed()
    if _vectorizer is None or _matrix is None or not _job_ids:
        return []
    q_vec = _vectorizer.transform([_preprocess(query)])
    sims = cosine_similarity(q_vec, _matrix)[0]
    top_idx = np.argsort(sims)[::-1][:top_k]
    return [(_job_ids[i], float(sims[i])) for i in top_idx if sims[i] > 0]


def hybrid_search(query: str, top_k: int = 50) -> list:
    """BM25关键词 + TF-IDF语义 双路 RRF 融合，返回 job_id 列表"""
    import search as bm25_mod
    bm25_mod.rebuild_index_if_needed()
    bm25_ids = bm25_mod.search(query, top_k=top_k)
    vec_ids = [jid for jid, _ in vector_search(query, top_k=top_k)]

    # Reciprocal Rank Fusion, k=60
    K = 60
    scores: dict = {}
    for rank, jid in enumerate(bm25_ids):
        scores[jid] = scores.get(jid, 0.0) + 1.0 / (K + rank + 1)
    for rank, jid in enumerate(vec_ids):
        scores[jid] = scores.get(jid, 0.0) + 1.0 / (K + rank + 1)

    merged = sorted(scores, key=lambda x: scores[x], reverse=True)
    return merged[:top_k]
