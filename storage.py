# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""入库流程：把解析后的岗位字典按 job_id 去重，写入/更新 Job、Company、JobSnapshot，并记录 CrawlLog"""

import datetime
import json

import config
from crawler.parser import is_java_backend_heavy_job
from models import CrawlLog, Company, FilteredJob, Job, JobSnapshot, app, db


def _record_filtered(parsed: dict, reason: str) -> None:
    """记录被过滤掉、未正式入库的岗位及过滤原因，供前端核对过滤效果"""
    db.session.add(FilteredJob(
        job_id=parsed.get("job_id"),
        title=parsed.get("title"),
        company_name=parsed.get("company_name"),
        reason=reason,
        source_keyword=parsed.get("source_keyword"),
        url=parsed.get("url"),
    ))


def _get_or_create_company(name: str) -> Company:
    company = Company.query.filter_by(name=name).first()
    now = datetime.datetime.now()
    if company is None:
        company = Company(name=name, first_seen_at=now, last_seen_at=now)
        db.session.add(company)
        db.session.flush()  # 拿到 company.id 供 Job 外键引用
    else:
        company.last_seen_at = now
    return company


def save_job(parsed: dict) -> str:
    """保存单条解析后的岗位数据，返回 'new' / 'updated' / 'skipped'（缺少必要字段时跳过）"""
    job_id = parsed.get("job_id")
    company_name = parsed.get("company_name")
    if not job_id or not company_name:
        return "skipped"

    # 用户只关注AI开发相关岗位，明确要求大量Java后端知识的岗位不在范围内，过滤掉不入库（但保留记录供核对）
    if is_java_backend_heavy_job(parsed.get("description")):
        _record_filtered(parsed, "Java后端要求过高")
        return "skipped"

    now = datetime.datetime.now()
    company = _get_or_create_company(company_name)

    job = Job.query.filter_by(job_id=job_id).first()
    is_new = job is None
    if job is None:
        job = Job(job_id=job_id, company_id=company.id, first_seen_at=now)
        db.session.add(job)

    job.title = parsed.get("title")
    job.company_id = company.id
    job.city = parsed.get("city") or config.CITY_NAME
    job.area = parsed.get("area_raw")
    job.work_address = parsed.get("work_address")

    job.salary_min = parsed.get("salary_min")
    job.salary_max = parsed.get("salary_max")
    job.salary_unit = parsed.get("salary_unit")
    job.salary_months = parsed.get("salary_months")

    job.experience_min = parsed.get("experience_min")
    job.experience_max = parsed.get("experience_max")
    job.education_req = parsed.get("education_req")

    job.skill_tags = json.dumps(parsed.get("skill_tags") or [], ensure_ascii=False)
    job.description = parsed.get("description")
    job.recruiter_info = parsed.get("recruiter_info_raw")

    job.source_keyword = parsed.get("source_keyword")
    job.url = parsed.get("url")

    job.last_seen_at = now
    job.is_active = True

    db.session.flush()  # 确保新建的 job 拿到 id，供快照外键引用

    db.session.add(JobSnapshot(
        job_id=job.id,
        salary_raw=parsed.get("salary_raw"),
        salary_min=parsed.get("salary_min"),
        salary_max=parsed.get("salary_max"),
        captured_at=now,
    ))

    return "new" if is_new else "updated"


def save_batch(keyword: str, parsed_jobs: list) -> dict:
    """保存一批解析结果（同一关键词的一次抓取），写入 CrawlLog 并返回统计信息"""
    log = CrawlLog(keyword=keyword, started_at=datetime.datetime.now(), status="running")
    db.session.add(log)
    db.session.flush()

    new_count = 0
    updated_count = 0
    try:
        for parsed in parsed_jobs:
            outcome = save_job(parsed)
            if outcome == "new":
                new_count += 1
            elif outcome == "updated":
                updated_count += 1

        log.total_found = len(parsed_jobs)
        log.new_count = new_count
        log.updated_count = updated_count
        log.status = "success"
        log.finished_at = datetime.datetime.now()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log.status = "failed"
        log.error_msg = str(e)[:500]
        log.finished_at = datetime.datetime.now()
        db.session.add(log)
        db.session.commit()
        raise

    return {
        "keyword": keyword,
        "total_found": len(parsed_jobs),
        "new_count": new_count,
        "updated_count": updated_count,
    }


def mark_inactive_before(cutoff: datetime.datetime) -> int:
    """把超过 cutoff 仍未出现过的岗位标记为已下线（is_active=False），返回受影响数量"""
    jobs = Job.query.filter(Job.last_seen_at < cutoff, Job.is_active.is_(True)).all()
    for job in jobs:
        job.is_active = False
    db.session.commit()
    return len(jobs)


if __name__ == "__main__":
    with app.app_context():
        print("storage 模块自检：当前数据库中共有 {} 条岗位记录".format(Job.query.count()))
