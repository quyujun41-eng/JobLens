# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""
Boss直聘 AI应用开发岗位爬虫原型（阶段一）

仅做"抓取 -> 解析 -> 落盘JSON"，不入库，用于先验证：
  1. 登录态是否可复用
  2. 选择器是否能正确定位列表/详情页元素
  3. 抓到的数据字段是否完整

使用前提：先运行 crawler/login.py 完成一次手动登录（登录态会保存在 data/edge_profile 目录）

注意：Boss直聘页面结构可能随时调整，下面的CSS选择器需要结合实际页面
（按 F12 查看元素）做核对和调整，已在每处标注用途方便定位维护。
"""

import json
import os
import random
import sys
import time
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from patchright.sync_api import TimeoutError as PWTimeoutError, sync_playwright

import config
from crawler.ocr import recognize_element_text
from crawler.parser import parse_job_card

SEARCH_URL_TEMPLATE = (
    "https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}"
)


def _random_sleep(low_high):
    time.sleep(random.uniform(*low_high))


def _is_login_page(page) -> bool:
    """检测是否被重定向到登录页（登录态失效的标志）"""
    return "login" in page.url


def collect_job_cards(page, keyword: str) -> list:
    """在搜索结果列表页收集岗位卡片基础信息（标题/公司/薪资/链接等）"""
    cards = []
    for page_no in range(1, config.MAX_PAGES_PER_KEYWORD + 1):
        url = SEARCH_URL_TEMPLATE.format(keyword=keyword, city_code=config.CITY_CODE)
        if page_no > 1:
            url += f"&page={page_no}"

        page.goto(url)
        page.wait_for_load_state("domcontentloaded")

        if _is_login_page(page):
            print(f"[警告] 检测到跳转登录页，登录态已失效，请重新运行 crawler/login.py")
            return cards

        # 岗位卡片容器，需根据实际页面结构核对（F12查看 class 名）
        try:
            page.wait_for_selector(".job-card-wrap", timeout=20000)
        except PWTimeoutError:
            # 选择器可能已过期：把当前页面HTML落盘，便于核对真实的class结构并修正选择器
            dump_path = os.path.join(config.RAW_DUMP_DIR, f"page_dump_{keyword}_{page_no}.html")
            os.makedirs(config.RAW_DUMP_DIR, exist_ok=True)
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"[{keyword}] 第{page_no}页未找到岗位卡片，选择器可能需要调整。"
                  f"已将页面HTML保存到: {dump_path}")
            break

        card_elements = page.query_selector_all(".job-card-wrap")
        if not card_elements:
            break

        for el in card_elements:
            try:
                title_el = el.query_selector("a.job-name")
                salary_el = el.query_selector(".job-salary")
                tag_els = el.query_selector_all(".tag-list li")
                company_el = el.query_selector(".boss-name")
                location_el = el.query_selector(".company-location")

                href = title_el.get_attribute("href") if title_el else None
                job_url = f"https://www.zhipin.com{href}" if href else None
                # 从详情页链接中截取岗位ID作为去重键，例如 /job_detail/abcdef123.html
                job_id = None
                if job_url:
                    job_id = job_url.split("/")[-1].replace(".html", "")

                tags = [t.inner_text().strip() for t in tag_els] if tag_els else []
                # 列表卡片的标签固定顺序为 [经验要求, 学历要求]
                experience_raw = tags[0] if len(tags) > 0 else ""
                education_raw = tags[1] if len(tags) > 1 else ""

                # 薪资文字被字体混淆，HTML文本是占位编码，需截图+OCR还原真实数字
                salary_text = recognize_element_text(salary_el)

                cards.append({
                    "job_id": job_id,
                    "title": title_el.inner_text().strip() if title_el else None,
                    "company_name": company_el.inner_text().strip() if company_el else None,
                    "salary_raw": salary_text,
                    "area_raw": location_el.inner_text().strip() if location_el else None,
                    "experience_raw": experience_raw,
                    "education_raw": education_raw,
                    "url": job_url,
                    "source_keyword": keyword,
                    "captured_at": datetime.now().isoformat(),
                })
            except Exception as e:
                print(f"[警告] 解析卡片失败: {e}")
                continue

        print(f"[{keyword}] 第{page_no}页抓到 {len(card_elements)} 条")
        _random_sleep(config.PAGE_DELAY_RANGE)

    return cards


def fetch_job_detail(page, card: dict) -> dict:
    """访问岗位详情页，补全JD全文、技能标签、招聘方信息、工作地址等字段"""
    if not card.get("url"):
        return card

    try:
        page.goto(card["url"], timeout=30000)
        page.wait_for_load_state("domcontentloaded")
    except PWTimeoutError:
        print(f"[跳过] 详情页导航超时，跳过该岗位: {card.get('url')}")
        return card

    if _is_login_page(page):
        card["_login_expired"] = True
        return card

    try:
        page.wait_for_selector(".job-sec-text", timeout=20000)
    except PWTimeoutError:
        dump_path = os.path.join(
            config.RAW_DUMP_DIR, f"detail_dump_{card.get('job_id')}.html"
        )
        os.makedirs(config.RAW_DUMP_DIR, exist_ok=True)
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"[警告] 详情页未加载出内容: {card.get('url')} | 当前URL: {page.url} | 已落盘: {dump_path}")
        return card

    # 页面结构已变化（原 .job-detail-box / .job-label-list 等选择器已失效，
    # 通过HTML落盘核对得到下面的最新选择器，2026-06核对）
    # JD正文：BOSS直聘会在文本中插入大量 display:none 的"垃圾span"做反爬，
    # inner_text() 会和浏览器一样遵循CSS可见性规则，自动过滤掉这些隐藏内容
    desc_el = page.query_selector(".job-sec-text")
    # 技能标签：网站已结构化好，直接使用，无需再靠关键词词典猜测
    skill_els = page.query_selector_all(".job-keyword-list li")
    city_el = page.query_selector(".text-desc.text-city")
    experience_el = page.query_selector(".text-desc.text-experiece")
    education_el = page.query_selector(".text-desc.text-degree")
    # 招聘方信息："公司名 · 部门"
    boss_attr_el = page.query_selector(".job-boss-info .boss-info-attr")
    address_el = page.query_selector(".location-address")
    salary_el = page.query_selector(".job-primary.detail-box .salary")

    if experience_el:
        card["experience_raw"] = experience_el.inner_text().strip()
    if education_el:
        card["education_raw"] = education_el.inner_text().strip()
    card["city"] = city_el.inner_text().strip() if city_el else None

    card["description"] = desc_el.inner_text().strip() if desc_el else None
    card["skill_tags"] = [s.inner_text().strip() for s in skill_els] if skill_els else []
    card["recruiter_info_raw"] = boss_attr_el.inner_text().strip() if boss_attr_el else None
    card["work_address"] = address_el.inner_text().strip() if address_el else None

    # 详情页薪资是明文（未做字体混淆），直接读取即可，无需OCR；
    # 仅当详情页缺失时才退化使用列表页OCR结果
    if salary_el:
        detail_salary = salary_el.inner_text().strip()
        if detail_salary:
            card["salary_raw"] = detail_salary

    _random_sleep(config.REQUEST_DELAY_RANGE)
    return card


def run(keywords=None, with_detail=True, save_to_db=False):
    """爬虫主入口：按关键词列表搜索 -> 抓详情 -> 解析 -> 落盘JSON（save_to_db=True 时同步入库并写CrawlLog）"""
    keywords = keywords or config.SEARCH_KEYWORDS

    if not os.path.exists(config.EDGE_PROFILE_DIR):
        print("未找到登录态目录，请先运行: python crawler/login.py 完成一次手动登录")
        return

    os.makedirs(config.RAW_DUMP_DIR, exist_ok=True)
    all_results = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            config.EDGE_PROFILE_DIR,
            channel="msedge",
            headless=False,
            viewport={"width": 1366, "height": 768},
            locale="zh-CN",
            # 提高设备像素比，让薪资等小号文字截图时更清晰，OCR识别准确率更高
            device_scale_factor=3,
        )
        page = context.pages[0] if context.pages else context.new_page()

        for keyword in keywords:
            print(f"\n=== 开始搜索关键词: {keyword} ===")
            cards = collect_job_cards(page, keyword)
            print(f"[{keyword}] 共收集 {len(cards)} 条基础信息")

            if with_detail:
                if save_to_db:
                    from models import app as flask_app, Job
                    with flask_app.app_context():
                        known_ids = {j.job_id for j in Job.query.with_entities(Job.job_id).all()}
                else:
                    known_ids = set()

                skipped_known = 0
                for i, card in enumerate(cards, 1):
                    if card.get("job_id") in known_ids:
                        skipped_known += 1
                        continue
                    print(f"  -> 抓取详情 {i}/{len(cards)}: {card.get('title')} @ {card.get('company_name')}")
                    try:
                        fetch_job_detail(page, card)
                    except Exception as e:
                        print(f"  [跳过] 详情页异常，跳过该岗位: {e}")
                        continue
                    if card.get("_login_expired"):
                        print("[警告] 登录态已失效，终止本次抓取，请重新登录")
                        break
                if skipped_known:
                    print(f"  [跳过] {skipped_known} 条已在库中，无需重新抓取详情")

            parsed = [parse_job_card(c) for c in cards]
            all_results.extend(parsed)

            if save_to_db:
                from models import app as flask_app
                from storage import save_batch
                with flask_app.app_context():
                    stats = save_batch(keyword, parsed)
                    print(f"[{keyword}] 入库完成: 新增 {stats['new_count']} 条，"
                          f"更新 {stats['updated_count']} 条，共 {stats['total_found']} 条")

            _random_sleep(config.PAGE_DELAY_RANGE)

        context.close()

    out_path = os.path.join(
        config.RAW_DUMP_DIR, f"jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n共抓取 {len(all_results)} 条岗位数据，已保存到: {out_path}")
    return all_results


if __name__ == "__main__":
    run()
