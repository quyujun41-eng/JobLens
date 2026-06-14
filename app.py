# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""Flask Web层：JobLens 主应用"""

import json
import traceback

import flask
from flask import Response, jsonify, render_template, request, stream_with_context

import analytics
import config
import search as bm25
from models import Company, Job, app, db

# ── 中间件注册 ────────────────────────────────────────────
import middleware
middleware.register(app)

# ── 页面路由 ──────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── 数据 API ─────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    with app.app_context():
        total_jobs = Job.query.filter_by(is_active=True).count()
        total_companies = db.session.query(Company.id).join(Job).filter(Job.is_active == True).distinct().count()
        salary_data = analytics.salary_distribution()
        avg_salary = None
        if salary_data["labels"]:
            # rough avg from buckets
            total_w = sum(salary_data["counts"])
            if total_w:
                vals = []
                for label, cnt in zip(salary_data["labels"], salary_data["counts"]):
                    try:
                        low = int(label.split("-")[0].replace("K以上", ""))
                        vals.append(low * cnt)
                    except Exception:
                        pass
                avg_salary = round(sum(vals) / total_w, 1) if vals else None
    return jsonify({
        "total_jobs": total_jobs,
        "total_companies": total_companies,
        "avg_salary": avg_salary,
        "cities": list(config.CITIES.keys()),
    })


@app.route("/api/job_list")
def api_job_list():
    page = request.args.get("page", 1, type=int)
    keyword = request.args.get("keyword", "").strip() or None
    company = request.args.get("company", "").strip() or None
    sort = request.args.get("sort", "salary_desc")
    exp = request.args.get("exp", "").strip() or None
    city = request.args.get("city", "").strip() or None
    salary_min = request.args.get("salary_min", type=float)
    salary_max = request.args.get("salary_max", type=float)

    # 有关键词时用混合检索（TF-IDF向量 + BM25 RRF融合）
    bm25_ids = None
    if keyword:
        try:
            from vector_search import hybrid_search
            bm25_ids = hybrid_search(keyword, top_k=100)
        except Exception:
            bm25.rebuild_index_if_needed()
            bm25_ids = bm25.search(keyword, top_k=100)

    return jsonify(analytics.job_list(
        page=page, keyword=keyword, company=company,
        sort=sort, exp=exp, city=city,
        salary_min=salary_min, salary_max=salary_max,
        bm25_ids=bm25_ids,
    ))


@app.route("/api/job_detail/<job_id>")
def api_job_detail(job_id):
    job = Job.query.filter_by(job_id=job_id).first()
    if not job:
        return jsonify({"error": "岗位不存在"}), 404
    import json as _json
    return jsonify({
        "job_id": job.job_id,
        "title": job.title,
        "company_name": job.company.name if job.company else "",
        "company_industry": job.company.industry if job.company else "",
        "company_scale": job.company.scale if job.company else "",
        "company_financing": job.company.financing_stage if job.company else "",
        "city": job.city,
        "area": job.area,
        "work_address": job.work_address,
        "salary": analytics._format_salary(job),
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_months": job.salary_months,
        "experience": analytics._format_experience(job),
        "education": job.education_req,
        "skill_tags": _json.loads(job.skill_tags) if job.skill_tags else [],
        "description": job.description or "",
        "recruiter_info": job.recruiter_info,
        "url": job.url,
        "last_seen_at": job.last_seen_at.strftime("%Y-%m-%d") if job.last_seen_at else None,
    })


@app.route("/api/salary_distribution")
def api_salary_distribution():
    return jsonify(analytics.salary_distribution())


@app.route("/api/skill_ranking")
def api_skill_ranking():
    return jsonify(analytics.skill_ranking())


@app.route("/api/company_salary_ranking")
def api_company_salary_ranking():
    return jsonify(analytics.company_salary_ranking())


@app.route("/api/hiring_trend")
def api_hiring_trend():
    return jsonify(analytics.hiring_trend())


@app.route("/api/keyword_demand_trend")
def api_keyword_demand_trend():
    return jsonify(analytics.keyword_demand_trend())


@app.route("/api/parse_resume", methods=["POST"])
def api_parse_resume():
    """解析上传的 PDF/TXT 简历，返回提取的文本"""
    if "file" not in request.files:
        return jsonify({"error": "请选择文件"}), 400
    f = request.files["file"]
    filename = f.filename.lower()
    try:
        if filename.endswith(".pdf"):
            import pdfplumber, io
            with pdfplumber.open(io.BytesIO(f.read())) as pdf:
                text = "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                ).strip()
        else:
            text = f.read().decode("utf-8", errors="ignore").strip()
        if not text:
            return jsonify({"error": "未能从文件中提取到文字内容"}), 400
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": f"解析失败：{e}"}), 500


@app.route("/api/filtered_job_list")
def api_filtered_job_list():
    page = request.args.get("page", 1, type=int)
    return jsonify(analytics.filtered_job_list(page=page))


@app.route("/api/company_benchmark")
def api_company_benchmark():
    name = request.args.get("company", "").strip()
    if not name:
        return jsonify({"error": "缺少 company 参数"}), 400
    result = analytics.company_benchmark(name)
    if result is None:
        return jsonify({"error": "未找到该公司的可比薪资数据"}), 404
    return jsonify(result)


# ── AI 功能 API ──────────────────────────────────────────

@app.route("/api/match", methods=["POST"])
def api_match():
    body = request.get_json(silent=True) or {}
    resume = body.get("resume", "").strip()
    job_id = body.get("job_id", "").strip()
    if not resume or not job_id:
        return jsonify({"error": "缺少参数"}), 400
    job = Job.query.filter_by(job_id=job_id).first()
    if not job:
        return jsonify({"error": "岗位不存在"}), 404
    from ai_features import match_score
    result = match_score(resume, job.description or "")
    return jsonify(result)


@app.route("/api/gap")
def api_gap():
    job_id = request.args.get("job_id", "").strip()
    resume = request.args.get("resume", "").strip()
    if not job_id or not resume:
        return Response(
            'data: {"type":"error","error":"缺少参数"}\n\n',
            content_type="text/event-stream"
        )
    job = Job.query.filter_by(job_id=job_id).first()
    if not job:
        return Response(
            'data: {"type":"error","error":"岗位不存在"}\n\n',
            content_type="text/event-stream"
        )

    from ai_features import gap_analysis_stream

    def generate():
        try:
            for chunk in gap_analysis_stream(resume, job.description or ""):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            traceback.print_exc()
            yield f"data: {json.dumps({'type':'error','error':str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/company_intel")
def api_company_intel():
    job_id = request.args.get("job_id", "").strip()
    if not job_id:
        return Response(
            'data: {"type":"error","error":"缺少参数"}\n\n',
            content_type="text/event-stream"
        )
    job = Job.query.filter_by(job_id=job_id).first()
    if not job:
        return Response(
            'data: {"type":"error","error":"岗位不存在"}\n\n',
            content_type="text/event-stream"
        )

    from ai_features import company_intel_stream

    def generate():
        try:
            for chunk in company_intel_stream(
                job.description or "",
                job.company.name if job.company else "",
                job.title or "",
            ):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            traceback.print_exc()
            yield f"data: {json.dumps({'type':'error','error':str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/ask", methods=["POST"])
def api_ask():
    import uuid
    from models import ChatSession, ChatMessage, db
    body = request.get_json(silent=True) or {}
    question = body.get("question", "").strip()
    session_id = body.get("session_id", "").strip() or None
    resume = body.get("resume", "").strip()
    mode = body.get("mode", "standard")  # standard | evaluator | orchestrator
    if not question:
        return jsonify({"error": "请输入问题"}), 400

    # 获取或创建会话
    with app.app_context():
        session = ChatSession.query.get(session_id) if session_id else None
        if not session:
            session = ChatSession(id=str(uuid.uuid4()), title=question[:40])
            db.session.add(session)
            db.session.commit()
            session_id = session.id

        # 保存用户消息
        db.session.add(ChatMessage(session_id=session_id, role="user", content=question))
        db.session.commit()

        # 加载历史（不含本条）
        all_msgs = ChatMessage.query.filter_by(session_id=session_id).order_by(
            ChatMessage.created_at).all()
        history = [{"role": m.role, "content": m.content} for m in all_msgs[:-1]]

    if mode == "evaluator":
        from evaluator_optimizer import evaluator_optimizer_stream as _stream_fn
        _gen_args = (question, history, resume, session_id)
    elif mode == "orchestrator":
        from orchestrator import orchestrate_stream as _stream_fn
        _gen_args = (question, history, resume)
    else:
        from agent import agent_stream as _stream_fn
        _gen_args = (question, history, resume)

    accumulated_text = []
    accumulated_tools = []

    def generate():
        try:
            for chunk in _stream_fn(*_gen_args):
                if chunk.get("type") == "text":
                    accumulated_text.append(chunk["text"])
                elif chunk.get("type") in ("tool_call", "tool_result"):
                    accumulated_tools.append(chunk)
                payload = dict(chunk, session_id=session_id)
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as e:
            traceback.print_exc()
            yield f"data: {json.dumps({'type':'error','error':str(e)})}\n\n"
        finally:
            try:
                with app.app_context():
                    db.session.add(ChatMessage(
                        session_id=session_id,
                        role="assistant",
                        content="".join(accumulated_text),
                        tool_calls_json=json.dumps(accumulated_tools, ensure_ascii=False) if accumulated_tools else None,
                    ))
                    db.session.commit()
            except Exception as e:
                print(f"[警告] 保存助手消息失败: {e}")

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/chat_sessions")
def api_chat_sessions():
    from models import ChatSession
    sessions = ChatSession.query.order_by(ChatSession.created_at.desc()).limit(30).all()
    return jsonify([{
        "id": s.id,
        "title": s.title or "新对话",
        "created_at": s.created_at.strftime("%m-%d %H:%M") if s.created_at else "",
    } for s in sessions])


@app.route("/api/chat_history/<session_id>")
def api_chat_history(session_id):
    from models import ChatSession, ChatMessage
    session = ChatSession.query.get(session_id)
    if not session:
        return jsonify({"error": "会话不存在"}), 404
    msgs = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.created_at).all()
    return jsonify({
        "session_id": session_id,
        "title": session.title or "新对话",
        "messages": [{
            "role": m.role,
            "content": m.content,
            "tool_calls": json.loads(m.tool_calls_json) if m.tool_calls_json else [],
            "created_at": m.created_at.strftime("%H:%M") if m.created_at else "",
        } for m in msgs],
    })


@app.route("/api/interview_prep")
def api_interview_prep():
    job_id = request.args.get("job_id", "").strip()
    resume = request.args.get("resume", "").strip()
    if not job_id:
        return Response('data: {"type":"error","error":"缺少job_id"}\n\n', content_type="text/event-stream")
    job = Job.query.filter_by(job_id=job_id).first()
    if not job:
        return Response('data: {"type":"error","error":"岗位不存在"}\n\n', content_type="text/event-stream")

    from ai_features import interview_prep_stream

    def generate():
        try:
            for chunk in interview_prep_stream(
                job.description or "", job.company.name if job.company else "", job.title or "", resume
            ):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            traceback.print_exc()
            yield f"data: {json.dumps({'type':'error','error':str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/request_coverage", methods=["POST"])
def api_request_coverage():
    from models import CoverageRequest, db
    body = request.get_json(silent=True) or {}
    city = body.get("city", "").strip()
    industry = body.get("industry", "").strip()
    email = body.get("email", "").strip()
    if not city or not industry:
        return jsonify({"error": "请选择城市和行业"}), 400

    # 核心组合已覆盖，无需申请
    core_pairs = {(c["city"], c["industry"]) for c in config.CORE_COMBOS}
    if (city, industry) in core_pairs:
        return jsonify({"success": True, "message": f"{city}·{industry} 是核心组合，每周自动更新"})

    # 已有记录则不重复写入
    existing = CoverageRequest.query.filter_by(city=city, industry=industry).filter(
        CoverageRequest.status.in_(["pending", "crawling", "done"])
    ).first()
    if existing:
        status_text = {"pending": "已在队列中", "crawling": "正在爬取", "done": "已完成"}.get(existing.status, "")
        return jsonify({"success": True, "message": f"{city}·{industry} {status_text}，次日凌晨更新"})

    req = CoverageRequest(city=city, industry=industry, email=email or None)
    db.session.add(req)
    db.session.commit()
    print(f"[申请开通] 城市={city} 行业={industry} 邮箱={email}，已加入爬取队列")
    return jsonify({"success": True, "message": f"已收到申请，{city}·{industry} 将在次日凌晨爬取，约1天内上线"})


@app.route("/api/coverage")
def api_coverage():
    from models import CoverageRequest

    core_pairs = {(c["city"], c["industry"]) for c in config.CORE_COMBOS}
    done_pairs = {
        (r.city, r.industry)
        for r in CoverageRequest.query.filter_by(status="done").all()
    }
    crawling_pairs = {
        (r.city, r.industry)
        for r in CoverageRequest.query.filter_by(status="crawling").all()
    }

    result = []
    for industry in config.CORE_INDUSTRIES:
        row = {"industry": industry, "cities": {}}
        for city in config.CITIES.keys():  # 全部5个城市都展示，非核心城市显示locked
            pair = (city, industry)
            if pair in core_pairs or pair in done_pairs:
                row["cities"][city] = "active"
            elif pair in crawling_pairs:
                row["cities"][city] = "progress"
            else:
                row["cities"][city] = "locked"
        result.append(row)
    return jsonify(result)


@app.route("/api/voice_to_text", methods=["POST"])
def api_voice_to_text():
    """语音转文字：接收音频文件，用 faster-whisper 转录为文本"""
    if "file" not in request.files:
        return jsonify({"error": "请上传音频文件"}), 400
    f = request.files["file"]
    try:
        import io
        import tempfile
        import os
        # 写到临时文件（faster-whisper 需要文件路径）
        suffix = os.path.splitext(f.filename or "audio.wav")[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            f.save(tmp.name)
            tmp_path = tmp.name
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel("tiny", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(tmp_path, language="zh")
            text = "".join(seg.text for seg in segments).strip()
        finally:
            os.unlink(tmp_path)
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": f"转录失败：{e}"}), 500


@app.route("/api/usage_stats")
def api_usage_stats():
    """可观测性：返回 API 用量统计（最近7天）"""
    from models import UsageLog
    from sqlalchemy import func
    import datetime

    since = datetime.datetime.now() - datetime.timedelta(days=7)
    logs = UsageLog.query.filter(UsageLog.created_at >= since).all()

    total = len(logs)
    avg_latency = round(sum(l.latency_ms or 0 for l in logs) / total, 1) if total else 0
    total_tokens = sum(l.tokens_estimated or 0 for l in logs)

    # 按端点聚合
    endpoint_stats: dict = {}
    for l in logs:
        ep = l.endpoint or "unknown"
        if ep not in endpoint_stats:
            endpoint_stats[ep] = {"count": 0, "errors": 0, "total_latency": 0}
        endpoint_stats[ep]["count"] += 1
        if l.status_code and l.status_code >= 400:
            endpoint_stats[ep]["errors"] += 1
        endpoint_stats[ep]["total_latency"] += l.latency_ms or 0

    endpoints = [
        {
            "endpoint": ep,
            "count": v["count"],
            "error_rate": round(v["errors"] / v["count"] * 100, 1),
            "avg_latency_ms": round(v["total_latency"] / v["count"], 1),
        }
        for ep, v in sorted(endpoint_stats.items(), key=lambda x: -x[1]["count"])
    ]

    return jsonify({
        "period": "7d",
        "total_requests": total,
        "avg_latency_ms": avg_latency,
        "total_tokens_estimated": total_tokens,
        "endpoints": endpoints[:20],
    })


@app.route("/api/rag_eval")
def api_rag_eval():
    """RAG 评估：对指定查询计算 Precision@K 等指标"""
    query = request.args.get("query", "").strip()
    top_k = request.args.get("k", 10, type=int)
    if not query:
        return jsonify({"error": "缺少 query 参数"}), 400

    # 取各路检索结果
    import search as bm25_mod
    from vector_search import vector_search as vec_search, hybrid_search

    bm25_mod.rebuild_index_if_needed()
    bm25_ids = bm25_mod.search(query, top_k=top_k)
    vec_results = vec_search(query, top_k=top_k)
    vec_ids = [jid for jid, _ in vec_results]
    hybrid_ids = hybrid_search(query, top_k=top_k)

    # 用 Rerank 启发式得分作为相关性标注（代替人工标注）
    from rerank import rerank_score
    gold_ids = set(rerank_score(query, hybrid_ids, top_k=top_k))

    def precision_at_k(retrieved: list, relevant: set, k: int) -> float:
        hits = sum(1 for jid in retrieved[:k] if jid in relevant)
        return round(hits / k, 3) if k else 0.0

    def recall_at_k(retrieved: list, relevant: set, k: int) -> float:
        if not relevant:
            return 0.0
        hits = sum(1 for jid in retrieved[:k] if jid in relevant)
        return round(hits / len(relevant), 3)

    return jsonify({
        "query": query,
        "k": top_k,
        "bm25": {
            "precision": precision_at_k(bm25_ids, gold_ids, top_k),
            "recall": recall_at_k(bm25_ids, gold_ids, top_k),
            "ids": bm25_ids[:5],
        },
        "vector": {
            "precision": precision_at_k(vec_ids, gold_ids, top_k),
            "recall": recall_at_k(vec_ids, gold_ids, top_k),
            "ids": vec_ids[:5],
        },
        "hybrid": {
            "precision": precision_at_k(hybrid_ids, gold_ids, top_k),
            "recall": recall_at_k(hybrid_ids, gold_ids, top_k),
            "ids": hybrid_ids[:5],
        },
    })


@app.route("/api/connector/tools")
def api_connector_tools():
    """列出 Connector 中注册的所有工具（来源：local / mcp / external）"""
    from connector import get_connector
    c = get_connector()
    return jsonify({"total": len(c), "tools": c.list_tool_info()})


@app.route("/api/connector/call", methods=["POST"])
def api_connector_call():
    """通过 Connector 调用任意工具（统一入口，屏蔽来源差异）"""
    from connector import get_connector
    body = request.get_json(silent=True) or {}
    name = body.get("tool", "").strip()
    arguments = body.get("arguments", {})
    if not name:
        return jsonify({"error": "缺少 tool 参数"}), 400
    c = get_connector()
    if name not in c:
        return jsonify({"error": f"工具 {name!r} 不存在", "available": c.list_tool_info()}), 404
    result = c.call(name, arguments)
    return jsonify({"tool": name, "source": c.get_source(name), "result": result})


@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    import os
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with app.app_context():
        from models import db as _db
        _db.create_all()
    app.run(host="0.0.0.0", debug=False, port=config.PORT)
