# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""向量检索：ChromaDB持久化 + TF-IDF自定义嵌入 + BM25混合RRF融合
ChromaDB提供持久化存储（重启无需重建索引），TF-IDF替代大模型embedding（无需下载）"""

import json
import os
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import config

# ── TF-IDF 组件（ChromaDB 的自定义 embedding function 依赖它）────────────

_vectorizer: TfidfVectorizer = None
_matrix = None
_job_ids: list = []
_indexed_count: int = -1

_CHROMA_DIR = os.path.join(config.DATA_DIR, "chroma_db")


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


def _build_doc(job) -> str:
    """将岗位各字段拼接为加权文档字符串（标题×3，技能×2，描述×1）"""
    tags = " ".join(json.loads(job.skill_tags) if job.skill_tags else [])
    return " ".join([
        (job.title or "") * 3,
        tags * 2,
        (job.source_keyword or "") * 2,
        job.description or "",
    ])


# ── ChromaDB 后端 ────────────────────────────────────────────────────────

_chroma_collection = None


def _get_chroma_collection():
    """懒加载 ChromaDB collection，使用自定义 TF-IDF embedding"""
    global _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection

    try:
        import chromadb
        from chromadb import EmbeddingFunction, Documents, Embeddings

        class TfidfEmbedding(EmbeddingFunction):
            """把 TF-IDF 向量适配为 ChromaDB 的 EmbeddingFunction 接口"""
            def __call__(self, input: Documents) -> Embeddings:
                rebuild_if_needed()
                if _vectorizer is None:
                    dim = 8000
                    return [np.zeros(dim).tolist() for _ in input]
                vecs = _vectorizer.transform([_preprocess(t) for t in input])
                return vecs.toarray().tolist()

        os.makedirs(_CHROMA_DIR, exist_ok=True)
        client = chromadb.PersistentClient(path=_CHROMA_DIR)
        _chroma_collection = client.get_or_create_collection(
            name="jobs",
            embedding_function=TfidfEmbedding(),
            metadata={"hnsw:space": "cosine"},
        )
        print(f"[ChromaDB] 已连接，路径={_CHROMA_DIR}，文档数={_chroma_collection.count()}")
    except Exception as e:
        print(f"[ChromaDB] 初始化失败，降级为 in-memory TF-IDF: {e}")
        _chroma_collection = None

    return _chroma_collection


def _sync_chroma(jobs):
    """将岗位数据同步到 ChromaDB（增量 upsert）"""
    col = _get_chroma_collection()
    if col is None:
        return
    try:
        docs, ids, metas = [], [], []
        for j in jobs:
            docs.append(_preprocess(_build_doc(j)))
            ids.append(j.job_id)
            metas.append({"title": j.title or "", "city": j.city or ""})
        if docs:
            col.upsert(documents=docs, ids=ids, metadatas=metas)
        print(f"[ChromaDB] upsert {len(docs)} 条，总计 {col.count()} 条")
    except Exception as e:
        print(f"[ChromaDB] upsert 失败: {e}")


def chroma_search(query: str, top_k: int = 50) -> list:
    """ChromaDB 向量检索，返回 [(job_id, score), ...]"""
    col = _get_chroma_collection()
    if col is None or col.count() == 0:
        return []
    try:
        results = col.query(
            query_texts=[_preprocess(query)],
            n_results=min(top_k, col.count()),
        )
        ids = results["ids"][0]
        distances = results["distances"][0]
        return [(jid, 1.0 - dist) for jid, dist in zip(ids, distances)]
    except Exception as e:
        print(f"[ChromaDB] 检索失败: {e}")
        return []


# ── TF-IDF 后端（fallback）──────────────────────────────────────────────

def build_index():
    """从数据库全量重建 TF-IDF 索引，并同步到 ChromaDB"""
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
            corpus.append(_preprocess(_build_doc(j)))
            ids.append(j.job_id)

        _job_ids = ids
        _vectorizer = TfidfVectorizer(max_features=8000, min_df=1, sublinear_tf=True)
        _matrix = _vectorizer.fit_transform(corpus)

        _sync_chroma(jobs)

    print(f"[向量索引] TF-IDF 已建立 {_indexed_count} 个岗位，ChromaDB 已同步")


def rebuild_if_needed():
    global _indexed_count
    from models import Job, app
    with app.app_context():
        current = Job.query.filter_by(is_active=True).count()
    if current != _indexed_count or _vectorizer is None:
        build_index()


def vector_search(query: str, top_k: int = 50) -> list:
    """向量语义搜索：优先用 ChromaDB，降级为 TF-IDF in-memory"""
    col = _get_chroma_collection()
    if col is not None and col.count() > 0:
        return chroma_search(query, top_k)

    # fallback: TF-IDF in-memory
    rebuild_if_needed()
    if _vectorizer is None or _matrix is None or not _job_ids:
        return []
    q_vec = _vectorizer.transform([_preprocess(query)])
    sims = cosine_similarity(q_vec, _matrix)[0]
    top_idx = np.argsort(sims)[::-1][:top_k]
    return [(_job_ids[i], float(sims[i])) for i in top_idx if sims[i] > 0]


def hybrid_search(query: str, top_k: int = 50) -> list:
    """BM25关键词 + 向量语义 双路 RRF 融合，返回 job_id 列表"""
    import search as bm25_mod
    bm25_mod.rebuild_index_if_needed()
    bm25_ids = bm25_mod.search(query, top_k=top_k)
    vec_ids = [jid for jid, _ in vector_search(query, top_k=top_k)]

    K = 60
    scores: dict = {}
    for rank, jid in enumerate(bm25_ids):
        scores[jid] = scores.get(jid, 0.0) + 1.0 / (K + rank + 1)
    for rank, jid in enumerate(vec_ids):
        scores[jid] = scores.get(jid, 0.0) + 1.0 / (K + rank + 1)

    return sorted(scores, key=lambda x: scores[x], reverse=True)[:top_k]
