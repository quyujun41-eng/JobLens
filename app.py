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

    # BM25 语义搜索：有关键词时用 BM25 拿到排序后的 job_id 列表，再按此顺序分页
    bm25_ids = None
    if keyword:
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
    body = request.get_json(silent=True) or {}
    question = body.get("question", "").strip()
    history = body.get("history", [])
    if not question:
        return jsonify({"error": "请输入问题"}), 400

    # 传入部分岗位数据作为上下文
    jobs_data = analytics.job_list(per_page=20)
    from ai_features import chat_stream

    def generate():
        try:
            for chunk in chat_stream(question, history, jobs_data.get("items", [])):
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
