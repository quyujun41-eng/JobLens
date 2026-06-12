# !/usr/bin/env python
# _*_ coding: utf-8 _*_

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# 持久化浏览器配置目录：登录态（cookies等）随浏览器配置文件自动保存，
# 登录脚本和爬虫共用同一个目录即可免去手动导出/导入登录态
EDGE_PROFILE_DIR = os.path.join(DATA_DIR, "edge_profile")
RAW_DUMP_DIR = os.path.join(DATA_DIR, "raw")

# 目标城市（深圳）
CITY_NAME = "深圳"
CITY_CODE = "101280600"  # Boss直聘城市编码

# 搜索关键词列表：聚焦Python方向的AI应用开发岗位（不含算法研发类方向）
SEARCH_KEYWORDS = [
    "AI应用开发",
    "Python AI开发",
    "大模型应用开发",
    "LLM应用开发",
    "AI Agent开发",
    "提示词工程",
    "AI产品经理",
    # 校招专用关键词，补充普通搜索里排序靠后的应届/校招岗位
    "AI开发 校招",
    "AI应用 应届",
    "大模型 校招",
]

# JD正文里高频出现Java生态关键词、且全文未提及Python时，
# 判定为"任职要求明确要大量Java后端知识"的岗位，抓到后不入库
JAVA_BACKEND_SIGNAL_KEYWORDS = ["Java", "SpringBoot", "Spring Boot", "SpringCloud", "Spring Cloud", "MyBatis", "JVM"]
JAVA_BACKEND_SIGNAL_MIN_HITS = 2

# 每个关键词最多翻页数（避免抓取过深、控制单批次数据量）
MAX_PAGES_PER_KEYWORD = 5

# 抓取节奏控制（秒），用于随机延时模拟人类操作
REQUEST_DELAY_RANGE = (2, 8)
PAGE_DELAY_RANGE = (5, 12)

# JD 技能标签词典：用于从岗位描述中抽取结构化技能标签
SKILL_KEYWORDS = [
    "Python", "Java", "Go", "C++",
    "LangChain", "LlamaIndex", "RAG", "Agent", "Prompt Engineering", "提示词工程",
    "向量数据库", "Embedding", "微调", "Fine-tuning", "LoRA",
    "PyTorch", "TensorFlow", "Transformer",
    "FastAPI", "Flask", "Django",
    "Docker", "Kubernetes", "微服务",
    "OpenAI", "GPT", "通义千问", "文心一言", "Claude", "LLaMA",
]

# 学历要求关键词（按出现顺序匹配第一个命中的）
EDUCATION_KEYWORDS = ["博士", "硕士", "本科", "大专", "中专", "学历不限"]

# 定时增量抓取的间隔（小时），4-6小时一次足以覆盖岗位更新节奏，避免过于频繁触发风控
CRAWL_INTERVAL_HOURS = 6

# 数据保留范围（月）：超过这个时长未再出现的岗位标记为"已下线"（is_active=False），
# 仅影响展示口径，不做物理删除，便于保留历史趋势数据
DATA_RETENTION_MONTHS = 6
