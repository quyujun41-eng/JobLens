# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""薪资解析与JD结构化标签抽取"""

import re

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# 匹配 "15-25K" / "15-25K·14薪" / "200-230元/天" / "30-50元/时" 等薪资格式
SALARY_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(K|k|Ｋ|元/天|元/时)(?:·(\d+)薪)?"
)

# 匹配 "3-5年" 这类经验格式
EXPERIENCE_PATTERN = re.compile(r"(\d+)-(\d+)年|(\d+)年以上|经验不限|应届")


def parse_salary(raw_text: str) -> dict:
    """将 '15-25K·14薪' / '200-230元/天' 解析为 {salary_min, salary_max, salary_unit, salary_months}"""
    result = {"salary_min": None, "salary_max": None, "salary_unit": None, "salary_months": None}
    if not raw_text:
        return result

    match = SALARY_PATTERN.search(raw_text)
    if not match:
        return result

    result["salary_min"] = float(match.group(1))
    result["salary_max"] = float(match.group(2))
    unit = match.group(3)
    result["salary_unit"] = "K/月" if unit.upper() == "K" else unit
    if match.group(4):
        result["salary_months"] = int(match.group(4))
    return result


def parse_experience(raw_text: str) -> dict:
    """将 '3-5年' / '5年以上' / '经验不限' / '应届' 解析为 {experience_min, experience_max}"""
    result = {"experience_min": None, "experience_max": None}
    if not raw_text:
        return result

    if "经验不限" in raw_text or "应届" in raw_text:
        result["experience_min"] = 0
        result["experience_max"] = 0
        return result

    match = EXPERIENCE_PATTERN.search(raw_text)
    if not match:
        return result

    if match.group(1) and match.group(2):
        result["experience_min"] = int(match.group(1))
        result["experience_max"] = int(match.group(2))
    elif match.group(3):
        result["experience_min"] = int(match.group(3))
        result["experience_max"] = None

    return result


def is_java_backend_heavy_job(description: str) -> bool:
    """根据JD正文判断是否为明确要求大量Java后端知识的岗位
    （Java生态关键词命中次数达到阈值，且全文未提及Python）"""
    if not description:
        return False
    if "python" in description.lower():
        return False
    hits = sum(description.lower().count(kw.lower()) for kw in config.JAVA_BACKEND_SIGNAL_KEYWORDS)
    return hits >= config.JAVA_BACKEND_SIGNAL_MIN_HITS


def parse_education(raw_text: str) -> str:
    """从文本中匹配学历要求关键词，返回第一个命中的"""
    if not raw_text:
        return None
    for keyword in config.EDUCATION_KEYWORDS:
        if keyword in raw_text:
            return keyword
    return None


def extract_skill_tags(jd_text: str) -> list:
    """从JD全文中按技能词典抽取出现过的技能标签（去重，保持词典顺序）"""
    if not jd_text:
        return []
    found = []
    for skill in config.SKILL_KEYWORDS:
        if skill.lower() in jd_text.lower():
            found.append(skill)
    return found


def parse_job_card(card: dict) -> dict:
    """对一条原始岗位数据做统一解析，返回结构化字典"""
    parsed = dict(card)
    parsed.update(parse_salary(card.get("salary_raw", "")))
    parsed.update(parse_experience(card.get("experience_raw", "")))
    parsed["education_req"] = parse_education(card.get("education_raw", ""))
    # 优先使用网站自带的结构化技能标签，没有时才退化为关键词词典匹配
    if not parsed.get("skill_tags"):
        parsed["skill_tags"] = extract_skill_tags(card.get("description", ""))
    return parsed
