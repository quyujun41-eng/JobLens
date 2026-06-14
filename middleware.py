# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""请求拦截器：日志记录 + Token 用量估算 + 敏感词过滤 + 请求计时
通过 Flask before_request / after_request 钩子实现"""

import re
import time
import datetime

# ── 敏感词 / PII 过滤规则 ─────────────────────────────────

_PII_PATTERNS = [
    (re.compile(r'1[3-9]\d{9}'), '***手机号***'),
    (re.compile(r'\d{15,18}[xX]?'), '***身份证***'),
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), '***邮箱***'),
    (re.compile(r'\d{16,19}'), '***银行卡***'),
]

_BLOCKED_KEYWORDS = [
    "忘记密码", "admin", "DROP TABLE", "DELETE FROM", "<script",
    "javascript:", "eval(",
]


def filter_pii(text: str) -> str:
    """脱敏：替换文本中的 PII 信息"""
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def contains_blocked(text: str) -> bool:
    """检测是否含有被屏蔽关键词"""
    lower = text.lower()
    return any(kw.lower() in lower for kw in _BLOCKED_KEYWORDS)


# ── Token 用量估算 ────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """粗估 token 数：中文每字约 1.5 token，英文每词约 1.3 token"""
    chinese = len(re.findall(r'[一-鿿]', text))
    english_words = len(re.findall(r'[A-Za-z]+', text))
    return int(chinese * 1.5 + english_words * 1.3)


# ── Flask 注册函数 ────────────────────────────────────────

def register(app):
    """向 Flask app 注册拦截钩子"""

    @app.before_request
    def before():
        from flask import request, g
        g.start_time = time.time()
        g.request_id = f"{int(time.time()*1000) % 100000:05d}"

        # 只记录 API 请求
        if request.path.startswith("/api/"):
            body = request.get_data(as_text=True)
            tokens_in = estimate_tokens(body) if body else 0
            print(f"[REQ {g.request_id}] {request.method} {request.path} ~{tokens_in}tok")

    @app.after_request
    def after(response):
        from flask import request, g
        if not request.path.startswith("/api/"):
            return response

        latency_ms = int((time.time() - getattr(g, 'start_time', time.time())) * 1000)
        req_id = getattr(g, 'request_id', '?')

        # 估算响应 token（非流式）
        tokens_out = 0
        if response.content_type and 'json' in response.content_type:
            tokens_out = estimate_tokens(response.get_data(as_text=True))

        print(f"[RES {req_id}] {response.status_code} {latency_ms}ms ~{tokens_out}tok")

        # 写入 UsageLog
        try:
            from models import UsageLog, db
            log = UsageLog(
                endpoint=request.path,
                method=request.method,
                status_code=response.status_code,
                latency_ms=latency_ms,
                tokens_estimated=tokens_out,
            )
            db.session.add(log)
            db.session.commit()
        except Exception:
            pass

        return response

    @app.before_request
    def security_check():
        from flask import request, jsonify
        if request.method in ("POST", "PUT"):
            body = request.get_data(as_text=True)
            if body and contains_blocked(body):
                return jsonify({"error": "请求包含不允许的内容"}), 400
