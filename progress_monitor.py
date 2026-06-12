# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""轮询数据库，按关键词完成情况和总量变化打印抓取进度（供 Monitor 实时展示）"""

import sys
import time

import config
from models import app, CrawlLog, FilteredJob, Job

POLL_SECONDS = 30

with app.app_context():
    seen_log_ids = set()
    last_job_count = -1
    last_filtered_count = -1

    while True:
        job_count = Job.query.count()
        filtered_count = FilteredJob.query.count()

        for log in CrawlLog.query.order_by(CrawlLog.id.asc()).all():
            if log.id in seen_log_ids:
                continue
            if log.status in ("success", "failed"):
                seen_log_ids.add(log.id)
                print(f"[关键词完成] {log.keyword} | 状态={log.status} | 本次发现={log.total_found} | 新增={log.new_count}", flush=True)

        if job_count != last_job_count or filtered_count != last_filtered_count:
            print(f"[累计] 已入库岗位={job_count} | 已过滤岗位={filtered_count}", flush=True)
            last_job_count = job_count
            last_filtered_count = filtered_count

        if seen_log_ids and len(seen_log_ids) >= len(config.SEARCH_KEYWORDS):
            print("[完成] 全部关键词抓取结束", flush=True)
            sys.stdout.flush()
            break

        time.sleep(POLL_SECONDS)
