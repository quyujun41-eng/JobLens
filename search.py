# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""BM25 语义搜索：对岗位标题+描述建立全文索引，比 SQL LIKE 匹配更精准"""

import json
import re
from rank_bm25 import BM25Okapi

_index = None   # BM25 索引
_job_ids = []   # 与索引行对应的 job_id 列表


def _tokenize(text: str) -> list:
    """简单分词：按非字母数字字符切分 + 保留中文单字"""
    if not text:
        return []
    # 英文/数字按空白和标点切分
    tokens = re.findall(r'[a-zA-Z0-9]+|[一-鿿]', text.lower())
    return tokens


def build_index():
    """从数据库构建 BM25 索引，应用启动时调用一次"""
    global _index, _job_ids
    from models import Job, app
    with app.app_context():
        jobs = Job.query.filter_by(is_active=True).with_entities(
            Job.job_id, Job.title, Job.description, Job.skill_tags
        ).all()

    corpus = []
    _job_ids = []
    for job in jobs:
        tags = ""
        if job.skill_tags:
            try:
                tags = " ".join(json.loads(job.skill_tags))
            except Exception:
                pass
        doc = f"{job.title or ''} {job.title or ''} {tags} {job.description or ''}"
        corpus.append(_tokenize(doc))
        _job_ids.append(job.job_id)

    if corpus:
        _index = BM25Okapi(corpus)
    else:
        _index = None


def search(query: str, top_k: int = 50) -> list:
    """返回按 BM25 相关度排序的 job_id 列表（最多 top_k 条）"""
    if not _index or not query:
        return []
    tokens = _tokenize(query)
    if not tokens:
        return []
    scores = _index.get_scores(tokens)
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    return [_job_ids[i] for i, score in ranked[:top_k] if score > 0]


def rebuild_index_if_needed():
    """岗位数量变化时重建索引"""
    from models import Job, app
    with app.app_context():
        count = Job.query.filter_by(is_active=True).count()
    if count != len(_job_ids):
        build_index()
