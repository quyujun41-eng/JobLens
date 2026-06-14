# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""向量检索：ChromaDB持久化 + EmbeddingProvider 抽象（TF-IDF/OpenAI/SentenceTransformers）
+ BM25混合RRF融合。切换 EMBED_PROVIDER 环境变量即可更换嵌入后端。"""

import json
import os

import numpy as np

import config
from embedding import EmbeddingProvider, get_embedding_provider

_CHROMA_DIR = os.path.join(config.DATA_DIR, "chroma_db")

# in-memory 回退索引
_provider: EmbeddingProvider = None
_corpus_matrix = None
_job_ids: list = []
_indexed_count: int = -1


import re


def _preprocess(text: str) -> str:
    """分词预处理：中文逐字、英文小写（TF-IDF 使用）"""
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
    """懒加载 ChromaDB collection，使用 EmbeddingProvider 作为 embedding function"""
    global _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection

    try:
        import chromadb
        from chromadb import EmbeddingFunction, Documents, Embeddings

        class ProviderEmbedding(EmbeddingFunction):
            """将 EmbeddingProvider 适配为 ChromaDB EmbeddingFunction 接口"""
            def __call__(self, input: Documents) -> Embeddings:
                rebuild_if_needed()
                ep = get_embedding_provider()
                if ep.provider == "tfidf" and ep._tfidf is None:
                    return [np.zeros(8000).tolist() for _ in input]
                preprocessed = [_preprocess(t) for t in input]
                vecs = ep.embed(preprocessed)
                return [v.tolist() for v in vecs]

        os.makedirs(_CHROMA_DIR, exist_ok=True)
        client = chromadb.PersistentClient(path=_CHROMA_DIR)
        _chroma_collection = client.get_or_create_collection(
            name="jobs",
            embedding_function=ProviderEmbedding(),
            metadata={"hnsw:space": "cosine"},
        )
        print(f"[ChromaDB] 已连接，路径={_CHROMA_DIR}，文档数={_chroma_collection.count()}"
              f"，Embedding={get_embedding_provider().provider_name}")
    except Exception as e:
        print(f"[ChromaDB] 初始化失败，降级为 in-memory: {e}")
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


def chroma_search(query: str, top_k: int = 50, where: dict = None) -> list:
    """ChromaDB 向量检索，支持元数据过滤，返回 [(job_id, score), ...]
    where 示例: {"city": "深圳"} 或 {"$and": [{"city": "深圳"}, {"title": "算法"}]}
    """
    col = _get_chroma_collection()
    if col is None or col.count() == 0:
        return []
    try:
        kwargs = {
            "query_texts": [_preprocess(query)],
            "n_results": min(top_k, col.count()),
        }
        if where:
            kwargs["where"] = where
        results = col.query(**kwargs)
        ids = results["ids"][0]
        distances = results["distances"][0]
        return [(jid, 1.0 - dist) for jid, dist in zip(ids, distances)]
    except Exception as e:
        print(f"[ChromaDB] 检索失败: {e}")
        return []


# ── TF-IDF 后端（fallback）──────────────────────────────────────────────

def build_index():
    """全量重建向量索引（EmbeddingProvider 支持的任意后端），并同步到 ChromaDB"""
    global _provider, _corpus_matrix, _job_ids, _indexed_count
    from models import Job, app
    with app.app_context():
        jobs = Job.query.filter_by(is_active=True).all()
        _indexed_count = len(jobs)
        if not jobs:
            _provider = None
            _corpus_matrix = None
            _job_ids = []
            return

        corpus = [_preprocess(_build_doc(j)) for j in jobs]
        _job_ids = [j.job_id for j in jobs]

        _provider = get_embedding_provider()
        _provider.fit(corpus)              # TF-IDF 需要 fit，其他后端 no-op
        _corpus_matrix = _provider.embed(corpus)

        _sync_chroma(jobs)

    print(f"[向量索引] 已建立 {_indexed_count} 个岗位"
          f"，Embedding={_provider.provider_name}，ChromaDB 已同步")


def rebuild_if_needed():
    global _indexed_count
    from models import Job, app
    with app.app_context():
        current = Job.query.filter_by(is_active=True).count()
    if current != _indexed_count or _provider is None:
        build_index()


def vector_search(query: str, top_k: int = 50, city: str = None, industry: str = None) -> list:
    """向量语义搜索：优先用 ChromaDB（支持元数据过滤），降级为 TF-IDF in-memory
    city / industry 参数用于元数据过滤（仅 ChromaDB 后端支持）
    """
    col = _get_chroma_collection()
    if col is not None and col.count() > 0:
        where = None
        filters = {}
        if city:
            filters["city"] = city
        if len(filters) == 1:
            where = filters
        elif len(filters) > 1:
            where = {"$and": [{k: v} for k, v in filters.items()]}
        return chroma_search(query, top_k, where=where)

    # fallback: in-memory EmbeddingProvider
    rebuild_if_needed()
    if _provider is None or _corpus_matrix is None or not _job_ids:
        return []
    q_vec = _provider.embed_single(_preprocess(query))
    sims = _provider.similarity(q_vec, _corpus_matrix)
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
