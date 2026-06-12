# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""定时增量抓取调度：每隔 config.CRAWL_INTERVAL_HOURS 小时跑一次完整的"抓取->解析->入库"流程

用法：
  python scheduler.py          常驻运行，按设定间隔周期性抓取
  python scheduler.py --once   立即手动触发一次抓取（调试/补抓用），跑完即退出
"""

import datetime
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

import config
from crawler import boss_crawler
from models import app
from storage import mark_inactive_before


def run_crawl_job():
    """执行一次完整的增量抓取批次：按关键词列表抓取入库，并维护半年范围内的在招状态"""
    started = datetime.datetime.now()
    print(f"\n========== [{started}] 开始定时抓取批次 ==========")

    try:
        boss_crawler.run(keywords=config.SEARCH_KEYWORDS, with_detail=True, save_to_db=True)
    except Exception as e:
        print(f"[错误] 抓取批次执行异常: {e}")

    cutoff = started - datetime.timedelta(days=config.DATA_RETENTION_MONTHS * 30)
    with app.app_context():
        inactive_count = mark_inactive_before(cutoff)
    print(f"[维护] 已将 {cutoff.date()} 之前未再出现的 {inactive_count} 个岗位标记为已下线")

    finished = datetime.datetime.now()
    print(f"========== [{finished}] 批次结束，耗时 {finished - started} ==========\n")


def main():
    if "--once" in sys.argv:
        print("手动触发模式：立即执行一次抓取")
        run_crawl_job()
        return

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        run_crawl_job,
        trigger=IntervalTrigger(hours=config.CRAWL_INTERVAL_HOURS),
        next_run_time=datetime.datetime.now(),  # 启动后立即先跑一次，之后再按间隔周期执行
        id="boss_incremental_crawl",
        max_instances=1,  # 避免上一批还没跑完时下一批又被触发，对目标站点造成压力
    )
    print(f"调度已启动：每隔 {config.CRAWL_INTERVAL_HOURS} 小时执行一次增量抓取，Ctrl+C 退出")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("调度已停止")


if __name__ == "__main__":
    main()
