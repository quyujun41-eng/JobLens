# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""Embedding 模型抽象层：TF-IDF（默认）/ OpenAI API / SentenceTransformers（本地）
通过 EMBED_PROVIDER 环境变量无缝切换，屏蔽后端差异

EMBED_PROVIDER=tfidf              默认，无需下载任何模型
EMBED_PROVIDER=openai             调用 OpenAI text-embedding-3-small API
EMBED_PROVIDER=sentence_transformers  下载本地模型（首次~400MB）
EMBED_MODEL=paraphrase-multilingual-MiniLM-L12-v2   SentenceTransformers 模型名
"""

import os
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

EMBED_PROVIDER = os.environ.get("EMBED_PROVIDER", "tfidf")
EMBED_MODEL     = os.environ.get("EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
EMBED_DIM       = int(os.environ.get("EMBED_DIM", "8000"))  # TF-IDF 最大特征数

_st_model = None


def _load_st_model():
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer
        print(f"[Embedding] 加载 SentenceTransformer 模型: {EMBED_MODEL}（首次需下载）")
        _st_model = SentenceTransformer(EMBED_MODEL)
    return _st_model


class EmbeddingProvider:
    """统一嵌入接口，支持三种后端

    TF-IDF:              需要先 fit(corpus)，无需外部依赖
    OpenAI:              直接 embed()，需要 AI_API_KEY
    SentenceTransformers: 直接 embed()，需要安装 sentence-transformers
    """

    def __init__(self, provider: str = EMBED_PROVIDER):
        self.provider = provider
        self._tfidf: TfidfVectorizer = None

    # ── TF-IDF ────────────────────────────────────────────────

    def fit(self, texts: list) -> "EmbeddingProvider":
        """TF-IDF 需要先用语料库 fit（其他 provider 无需调用）"""
        if self.provider == "tfidf":
            self._tfidf = TfidfVectorizer(
                max_features=EMBED_DIM, min_df=1, sublinear_tf=True
            )
            self._tfidf.fit(texts)
        return self

    # ── 核心 embed 方法 ───────────────────────────────────────

    def embed(self, texts: list) -> np.ndarray:
        """将文本列表转为 embedding 矩阵 [N, dim]"""
        if not texts:
            return np.array([])
        if self.provider == "sentence_transformers":
            return _load_st_model().encode(texts, normalize_embeddings=True,
                                           show_progress_bar=False)
        elif self.provider == "openai":
            return self._embed_openai(texts)
        else:
            if self._tfidf is None:
                raise RuntimeError("TF-IDF 未初始化，请先调用 fit(corpus)")
            return self._tfidf.transform(texts).toarray()

    def embed_single(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def _embed_openai(self, texts: list) -> np.ndarray:
        import config
        from openai import OpenAI
        client = OpenAI(api_key=config.AI_API_KEY,
                        base_url=config.AI_BASE_URL or None)
        model = "text-embedding-3-small"
        resp = client.embeddings.create(model=model, input=texts)
        return np.array([d.embedding for d in resp.data])

    # ── 相似度计算 ────────────────────────────────────────────

    def similarity(self, query_vec: np.ndarray, corpus_matrix: np.ndarray) -> np.ndarray:
        """返回 query 向量与语料库矩阵的余弦相似度数组"""
        return cosine_similarity(query_vec.reshape(1, -1), corpus_matrix)[0]

    def top_k(self, query: str, corpus_texts: list, job_ids: list,
              top_k: int = 50) -> list:
        """端到端搜索：query → embedding → 余弦相似度排序 → [(job_id, score)]"""
        if not corpus_texts or len(corpus_texts) != len(job_ids):
            return []
        corpus_matrix = self.embed(corpus_texts)
        query_vec = self.embed_single(query)
        sims = self.similarity(query_vec, corpus_matrix)
        idx = np.argsort(sims)[::-1][:top_k]
        return [(job_ids[i], float(sims[i])) for i in idx if sims[i] > 0]

    @property
    def provider_name(self) -> str:
        if self.provider == "sentence_transformers":
            return f"SentenceTransformers ({EMBED_MODEL})"
        elif self.provider == "openai":
            return "OpenAI text-embedding-3-small"
        return "TF-IDF"

    def __repr__(self):
        return f"EmbeddingProvider(provider={self.provider!r}, model={EMBED_MODEL!r})"


# ── 全局单例 ─────────────────────────────────────────────────

_instance: EmbeddingProvider = None


def get_embedding_provider() -> EmbeddingProvider:
    global _instance
    if _instance is None:
        _instance = EmbeddingProvider()
    return _instance
