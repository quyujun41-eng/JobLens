# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""Flask Web层：求职者视图 + HR/企业视图，图表数据通过JSON接口供前端ECharts渲染"""

import flask

import analytics
from models import app


@app.route("/")
def index():
    return flask.redirect(flask.url_for("seeker_view"))


@app.route("/seeker")
def seeker_view():
    return flask.render_template("seeker.html")


@app.route("/hr")
def hr_view():
    return flask.render_template("hr.html", companies=analytics.company_list())


@app.route("/jobs")
def jobs_view():
    return flask.render_template("jobs.html")


@app.route("/api/job_list")
def api_job_list():
    page = flask.request.args.get("page", 1, type=int)
    keyword = flask.request.args.get("keyword", "").strip() or None
    company = flask.request.args.get("company", "").strip() or None
    sort = flask.request.args.get("sort", "salary_desc")
    exp = flask.request.args.get("exp", "").strip() or None
    return flask.jsonify(analytics.job_list(page=page, keyword=keyword, company=company, sort=sort, exp=exp))


@app.route("/api/filtered_job_list")
def api_filtered_job_list():
    page = flask.request.args.get("page", 1, type=int)
    return flask.jsonify(analytics.filtered_job_list(page=page))


@app.route("/api/salary_distribution")
def api_salary_distribution():
    return flask.jsonify(analytics.salary_distribution())


@app.route("/api/skill_ranking")
def api_skill_ranking():
    return flask.jsonify(analytics.skill_ranking())


@app.route("/api/company_salary_ranking")
def api_company_salary_ranking():
    return flask.jsonify(analytics.company_salary_ranking())


@app.route("/api/hiring_trend")
def api_hiring_trend():
    return flask.jsonify(analytics.hiring_trend())


@app.route("/api/company_benchmark")
def api_company_benchmark():
    name = flask.request.args.get("company", "").strip()
    if not name:
        return flask.jsonify({"error": "缺少 company 参数"}), 400
    result = analytics.company_benchmark(name)
    if result is None:
        return flask.jsonify({"error": "未找到该公司的可比薪资数据"}), 404
    return flask.jsonify(result)


@app.route("/api/keyword_demand_trend")
def api_keyword_demand_trend():
    return flask.jsonify(analytics.keyword_demand_trend())


if __name__ == "__main__":
    app.run(debug=True, port=5000)
