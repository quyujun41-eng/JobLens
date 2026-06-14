# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""文档智能分块：三种策略
  - fixed:     固定字符数 + 重叠窗口
  - recursive: 递归分隔符（LangChain风格），段落→换行→句号→空格→字符
  - chinese:   中文专属，按句子边界切分，尊重自然语义单元
"""

import re
from typing import Callable


# ── 策略1：固定大小分块 ──────────────────────────────────────

def chunk_fixed(text: str, chunk_size: int = 500, overlap: int = 50) -> list:
    """按字符数等长切分，带重叠窗口防止语义断裂"""
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + chunk_size].strip())
        start += chunk_size - overlap
    return [c for c in chunks if c]


# ── 策略2：递归字符分块 ──────────────────────────────────────

_DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]


def chunk_recursive(text: str, chunk_size: int = 500, overlap: int = 50,
                    separators: list = None) -> list:
    """递归分隔符分块（LangChain RecursiveCharacterTextSplitter 同款算法）
    按优先级尝试分隔符：找到第一个能将文本分割得合理的即停止"""
    seps = separators or _DEFAULT_SEPARATORS

    def _split(t: str, sep_list: list) -> list:
        if not sep_list or len(t) <= chunk_size:
            return [t] if t.strip() else []
        sep = sep_list[0]
        parts = re.split(re.escape(sep), t) if sep else list(t)

        result, current = [], ""
        for part in parts:
            piece = (current + sep + part) if current else part
            if len(piece) <= chunk_size:
                current = piece
            else:
                if current:
                    result.append(current)
                if len(part) > chunk_size:
                    result.extend(_split(part, sep_list[1:]))
                    current = ""
                else:
                    current = part
        if current:
            result.append(current)
        return result

    raw = _split(text, seps)

    # 合并过小碎片
    merged, buf = [], ""
    for chunk in raw:
        if len(buf) + len(chunk) + 1 < chunk_size:
            buf = (buf + " " + chunk).strip() if buf else chunk
        else:
            if buf:
                merged.append(buf)
            buf = chunk
    if buf:
        merged.append(buf)

    if overlap <= 0:
        return [c.strip() for c in merged if c.strip()]

    # 添加重叠
    overlapped = []
    for i, chunk in enumerate(merged):
        prefix = merged[i - 1][-overlap:] if i > 0 else ""
        overlapped.append((prefix + chunk).strip())
    return [c for c in overlapped if c]


# ── 策略3：中文专属分块 ──────────────────────────────────────

_CN_SENTENCE_END = re.compile(r'(?<=[。！？…]{1,2})')
_CN_CLAUSE_END   = re.compile(r'(?<=[；，])')


def chunk_chinese(text: str, min_size: int = 100, max_size: int = 600,
                  overlap: int = 50) -> list:
    """中文专属分块：按句子边界切分，合并短句，尊重段落结构
    优先按句末标点（。！？）切，过长则按逗号/分号再切"""
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
    sentences = []
    for para in paragraphs:
        parts = _CN_SENTENCE_END.split(para)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if len(p) > max_size:
                # 句子过长，再按从句切
                sub = _CN_CLAUSE_END.split(p)
                sentences.extend(s.strip() for s in sub if s.strip())
            else:
                sentences.append(p)

    chunks, current = [], ""
    for sent in sentences:
        candidate = current + sent
        if len(candidate) <= max_size:
            current = candidate
        else:
            if len(current) >= min_size:
                chunks.append(current)
                # 重叠：把当前块末尾 overlap 字符带入下一块
                current = (current[-overlap:] if overlap else "") + sent
            else:
                current = candidate  # 当前块太短，继续合并

    if current and len(current) >= min_size // 2:
        chunks.append(current)

    return chunks


# ── 统一入口 ─────────────────────────────────────────────────

_STRATEGIES: dict = {
    "fixed":     chunk_fixed,
    "recursive": chunk_recursive,
    "chinese":   chunk_chinese,
}


def chunk_text(text: str, strategy: str = "chinese", **kwargs) -> list:
    """统一分块接口
    strategy: "fixed" | "recursive" | "chinese"
    """
    if strategy not in _STRATEGIES:
        raise ValueError(f"未知策略 {strategy!r}，可选：{list(_STRATEGIES)}")
    return _STRATEGIES[strategy](text, **kwargs)


def chunk_with_metadata(text: str, source: str = "",
                         strategy: str = "chinese", **kwargs) -> list:
    """分块 + 附加元数据（来源、序号、字符偏移量）"""
    chunks = chunk_text(text, strategy, **kwargs)
    result, offset = [], 0
    for i, chunk in enumerate(chunks):
        idx = text.find(chunk[:20], offset)
        result.append({
            "content": chunk,
            "metadata": {
                "source":        source,
                "chunk_index":   i,
                "total_chunks":  len(chunks),
                "char_start":    idx if idx >= 0 else offset,
                "char_length":   len(chunk),
                "strategy":      strategy,
            },
        })
        if idx >= 0:
            offset = idx + len(chunk) // 2
    return result
