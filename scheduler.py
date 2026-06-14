# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""定时调度：每天凌晨滚动爬取核心组合，并处理用户「申请开通」队列

用法：
  python scheduler.py          常驻运行，凌晨 2 点自动触发
  python scheduler.py --once   立即手动触发一次（调试用），跑完即退出
  python scheduler.py --combo 深圳 AI/大模型  手动指定城市+行业单跑
"""

import datetime
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from crawler import boss_crawler
from models import CoverageRequest, CrawlLog, app
from storage import mark_inactive_before


def get_todays_core_combos():
    """按日期偏移从20个核心组合中取今天要爬的几个（滚动覆盖，约一周一轮）"""
    n = len(config.CORE_COMBOS)
    if n == 0:
        return []
    offset = datetime.date.today().toordinal() % n
    indices = [(offset + i) % n for i in range(config.COMBOS_PER_DAY)]
    return [config.CORE_COMBOS[i] for i in indices]


def crawl_combo(city: str, city_code: str, industry: str):
    """爬取指定城市+行业组合的全部关键词"""
    keywords = config.INDUSTRY_KEYWORDS.get(industry, [industry])
    print(f"  → 爬取 {city}·{industry}（{len(keywords)} 个关键词）")
    try:
        boss_crawler.run(
            keywords=keywords,
            with_detail=True,
            save_to_db=True,
            city_code=city_code,
        )
    except Exception as e:
        print(f"  [错误] {city}·{industry} 爬取异常: {e}")


def run_crawl_job():
    """凌晨批次：先跑今天的滚动核心组合，再处理待处理的申请开通请求"""
    started = datetime.datetime.now()
    print(f"\n========== [{started}] 凌晨爬取批次开始 ==========")

    # 1. 今天的滚动核心组合
    todays = get_todays_core_combos()
    print(f"[核心] 今日轮到 {len(todays)} 个组合: "
          + ", ".join(f"{c['city']}·{c['industry']}" for c in todays))
    for combo in todays:
        crawl_combo(combo["city"], combo["city_code"], combo["industry"])

    # 2. 处理申请开通队列（pending 状态）
    with app.app_context():
        pending = CoverageRequest.query.filter_by(status="pending").all()
        if pending:
            print(f"[队列] 处理 {len(pending)} 个申请开通请求")
        for req in pending:
            req.status = "crawling"
            from models import db
            db.session.commit()

            city_code = config.CITIES.get(req.city) or config.CORE_CITIES.get(req.city)
            if not city_code:
                print(f"  [跳过] 未知城市: {req.city}")
                req.status = "pending"
                db.session.commit()
                continue

            crawl_combo(req.city, city_code, req.industry)
            req.status = "done"
            req.crawled_at = datetime.datetime.now()
            db.session.commit()
            print(f"  [完成] {req.city}·{req.industry} 已入库，申请标记为 done")

    # 3. 把超过半年未再出现的岗位标记为已下线
    cutoff = started - datetime.timedelta(days=config.DATA_RETENTION_MONTHS * 30)
    with app.app_context():
        inactive_count = mark_inactive_before(cutoff)
    print(f"[维护] 已将 {cutoff.date()} 之前未再出现的 {inactive_count} 个岗位标记为已下线")

    finished = datetime.datetime.now()
    print(f"========== [{finished}] 批次结束，耗时 {finished - started} ==========\n")


def main():
    if "--once" in sys.argv:
        print("手动触发：立即执行一次完整批次")
        run_crawl_job()
        return

    # 支持手动指定 --combo 城市 行业 单跑一个组合
    if "--combo" in sys.argv:
        idx = sys.argv.index("--combo")
        try:
            city = sys.argv[idx + 1]
            industry = sys.argv[idx + 2]
        except IndexError:
            print("用法: python scheduler.py --combo 深圳 AI/大模型")
            sys.exit(1)
        city_code = config.CITIES.get(city) or config.CORE_CITIES.get(city)
        if not city_code:
            print(f"未知城市: {city}，可选: {list(config.CITIES.keys())}")
            sys.exit(1)
        crawl_combo(city, city_code, industry)
        return

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        run_crawl_job,
        trigger=CronTrigger(hour=config.CRAWL_CRON_HOUR, minute=0),
        id="boss_daily_crawl",
        max_instances=1,
    )
    print(f"调度已启动：每天凌晨 {config.CRAWL_CRON_HOUR}:00 执行，"
          f"今日核心组合: {[c['city']+'·'+c['industry'] for c in get_todays_core_combos()]}")
    print("Ctrl+C 退出")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("调度已停止")


if __name__ == "__main__":
    main()
