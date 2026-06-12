# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""分析查询模块：把数据库中的岗位数据聚合成各类图表所需的JSON结构"""

import json
from collections import Counter

from sqlalchemy import func

from models import Company, FilteredJob, Job, db

# 月薪类岗位（K/月）是分析的主体，元/天、元/时等计价方式不参与薪资类统计，避免量纲混淆
_MONTHLY_SALARY_FILTER = (
    Job.is_active.is_(True),
    Job.salary_unit == "K/月",
    Job.salary_min.isnot(None),
    Job.salary_max.isnot(None),
)
_SALARY_MID = (Job.salary_min + Job.salary_max) / 2.0


def salary_distribution(bucket_size=5, max_bucket=80):
    """薪资分布直方图：按(下限+上限)/2均值分桶统计岗位数"""
    jobs = Job.query.filter(*_MONTHLY_SALARY_FILTER).all()
    buckets = Counter()
    for job in jobs:
        mid = (job.salary_min + job.salary_max) / 2
        bucket = min(int(mid // bucket_size) * bucket_size, max_bucket)
        buckets[bucket] += 1

    labels, counts = [], []
    for b in sorted(buckets):
        label = f"{b}K以上" if b >= max_bucket else f"{b}-{b + bucket_size}K"
        labels.append(label)
        counts.append(buckets[b])
    return {"labels": labels, "counts": counts}


def skill_ranking(top_n=20):
    """高频技能标签排行榜（取自岗位详情页已结构化的技能标签）"""
    counter = Counter()
    rows = db.session.query(Job.skill_tags).filter(Job.is_active.is_(True)).all()
    for (tags_json,) in rows:
        if not tags_json:
            continue
        for tag in json.loads(tags_json):
            counter[tag] += 1

    top = counter.most_common(top_n)
    return {"labels": [t for t, _ in top], "counts": [c for _, c in top]}


def company_salary_ranking(top_n=15):
    """企业薪资横向对比：按平均薪资降序排列"""
    rows = (
        db.session.query(
            Company.name,
            func.avg(_SALARY_MID).label("avg_salary"),
            func.count(Job.id).label("job_count"),
        )
        .join(Job, Job.company_id == Company.id)
        .filter(*_MONTHLY_SALARY_FILTER)
        .group_by(Company.id)
        .order_by(func.avg(_SALARY_MID).desc())
        .limit(top_n)
        .all()
    )
    return {
        "labels": [r.name for r in rows],
        "avg_salary": [round(r.avg_salary, 1) for r in rows],
        "job_count": [r.job_count for r in rows],
    }


def hiring_trend():
    """招聘量与平均薪资趋势（按岗位首次抓到的月份聚合）"""
    rows = (
        db.session.query(
            func.strftime("%Y-%m", Job.first_seen_at).label("month"),
            func.count(Job.id).label("job_count"),
            func.avg(_SALARY_MID).label("avg_salary"),
        )
        .filter(*_MONTHLY_SALARY_FILTER)
        .group_by("month")
        .order_by("month")
        .all()
    )
    return {
        "labels": [r.month for r in rows],
        "job_count": [r.job_count for r in rows],
        "avg_salary": [round(r.avg_salary, 1) if r.avg_salary is not None else None for r in rows],
    }


def company_list():
    """有在招岗位的公司名称列表，供HR视图选择对标公司"""
    rows = (
        db.session.query(Company.name)
        .join(Job, Job.company_id == Company.id)
        .filter(Job.is_active.is_(True))
        .distinct()
        .order_by(Company.name)
        .all()
    )
    return [r[0] for r in rows]


def company_benchmark(company_name):
    """HR视图核心：选定公司 vs 深圳市场整体的薪资对标，返回 None 表示该公司无可比数据"""
    company_jobs = (
        Job.query.join(Company)
        .filter(Company.name == company_name, *_MONTHLY_SALARY_FILTER)
        .all()
    )
    if not company_jobs:
        return None

    def _avg_mid(jobs):
        return round(sum((j.salary_min + j.salary_max) / 2 for j in jobs) / len(jobs), 1)

    market_jobs = Job.query.filter(*_MONTHLY_SALARY_FILTER).all()

    return {
        "company_name": company_name,
        "company_avg_salary": _avg_mid(company_jobs),
        "company_job_count": len(company_jobs),
        "company_min": min(j.salary_min for j in company_jobs),
        "company_max": max(j.salary_max for j in company_jobs),
        "market_avg_salary": _avg_mid(market_jobs),
        "market_job_count": len(market_jobs),
    }


def _format_salary(job):
    if job.salary_min is None or job.salary_max is None:
        return "面议"
    text = f"{int(job.salary_min)}-{int(job.salary_max)}{job.salary_unit or ''}"
    if job.salary_months:
        text += f"·{job.salary_months}薪"
    return text


def _format_experience(job):
    if job.experience_min is None:
        return "经验不限"
    if job.experience_min == 0 and job.experience_max == 0:
        return "经验不限/应届"
    if job.experience_max is None:
        return f"{job.experience_min}年以上"
    return f"{job.experience_min}-{job.experience_max}年"


def job_list(page=1, per_page=20, keyword=None, company=None, sort="salary_desc",
            exp=None, city=None, salary_min=None, salary_max=None):
    """全量岗位招聘信息汇总（前端列表页用），支持按岗位关键词/公司名/城市/薪资筛选、排序、分页"""
    from sqlalchemy import case, nulls_last
    query = Job.query.join(Company).filter(Job.is_active.is_(True))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(db.or_(Job.title.like(like), Job.source_keyword.like(like),
                                    Job.description.like(like)))
    if company:
        query = query.filter(Company.name.like(f"%{company}%"))
    if city:
        query = query.filter(Job.city == city)
    if salary_min is not None:
        query = query.filter(Job.salary_min >= salary_min)
    if salary_max is not None:
        query = query.filter(Job.salary_max <= salary_max)
    if exp == "campus":
        query = query.filter(Job.experience_min == 0)
    elif exp == "experienced":
        query = query.filter(Job.experience_min > 0)

    monthly_first = db.case((Job.salary_unit == "K/月", 0), else_=1)
    if sort == "salary_desc":
        query = query.order_by(monthly_first, Job.salary_max.desc().nulls_last(), Job.salary_min.desc().nulls_last())
    elif sort == "salary_asc":
        query = query.order_by(monthly_first, Job.salary_max.asc().nulls_last(), Job.salary_min.asc().nulls_last())
    elif sort == "title_asc":
        query = query.order_by(Job.title.asc())
    elif sort == "title_desc":
        query = query.order_by(Job.title.desc())
    else:
        query = query.order_by(Job.last_seen_at.desc())

    total = query.count()
    jobs = query.offset((page - 1) * per_page).limit(per_page).all()

    items = [{
        "job_id": j.job_id,
        "title": j.title,
        "company_name": j.company.name,
        "city": j.city,
        "area": j.area,
        "salary": _format_salary(j),
        "salary_max": j.salary_max,
        "experience": _format_experience(j),
        "education": j.education_req,
        "skill_tags": json.loads(j.skill_tags) if j.skill_tags else [],
        "url": j.url,
        "last_seen_at": j.last_seen_at.strftime("%Y-%m-%d") if j.last_seen_at else None,
    } for j in jobs]

    return {"total": total, "page": page, "per_page": per_page, "sort": sort, "items": items}


def filtered_job_list(page=1, per_page=20):
    """被过滤规则排除、未正式入库的岗位列表（前端用于核对过滤效果是否符合预期）"""
    query = FilteredJob.query.order_by(FilteredJob.filtered_at.desc())
    total = query.count()
    rows = query.offset((page - 1) * per_page).limit(per_page).all()

    items = [{
        "job_id": r.job_id,
        "title": r.title,
        "company_name": r.company_name,
        "reason": r.reason,
        "source_keyword": r.source_keyword,
        "url": r.url,
        "filtered_at": r.filtered_at.strftime("%Y-%m-%d %H:%M") if r.filtered_at else None,
    } for r in rows]

    return {"total": total, "page": page, "per_page": per_page, "items": items}


def keyword_demand_trend():
    """各搜索关键词命中的岗位量按月走势，反映不同AI岗位方向的需求热度变化"""
    rows = (
        db.session.query(
            func.strftime("%Y-%m", Job.first_seen_at).label("month"),
            Job.source_keyword,
            func.count(Job.id).label("job_count"),
        )
        .group_by("month", Job.source_keyword)
        .order_by("month")
        .all()
    )
    months = sorted({r.month for r in rows})
    keywords = sorted({r.source_keyword for r in rows if r.source_keyword})
    month_index = {m: i for i, m in enumerate(months)}

    series = {kw: [0] * len(months) for kw in keywords}
    for r in rows:
        if r.source_keyword in series:
            series[r.source_keyword][month_index[r.month]] = r.job_count

    return {"months": months, "series": series}
