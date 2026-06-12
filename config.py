# !/usr/bin/env python
# _*_ coding: utf-8 _*_

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

EDGE_PROFILE_DIR = os.path.join(DATA_DIR, "edge_profile")
RAW_DUMP_DIR = os.path.join(DATA_DIR, "raw")

# Claude API
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
AI_MODEL = "claude-haiku-4-5-20251001"

PORT = int(os.environ.get("PORT", 5000))

# 城市配置
CITIES = {
    "深圳": "101280600",
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "杭州": "101210100",
}

# 当前爬取目标（单次任务用）
CITY_NAME = os.environ.get("CRAWL_CITY", "深圳")
CITY_CODE = CITIES.get(CITY_NAME, "101280600")

# 已覆盖的城市+行业组合（用于覆盖矩阵展示）
COVERED_COMBOS = [
    {"city": "深圳", "industry": "AI/大模型"},
    {"city": "深圳", "industry": "后端开发"},
    {"city": "北京", "industry": "AI/大模型"},
    {"city": "北京", "industry": "后端开发"},
    {"city": "上海", "industry": "AI/大模型"},
]

# 行业分类（15大类）
INDUSTRIES = [
    "AI/大模型", "后端开发", "前端开发", "数据分析", "算法工程师",
    "产品经理", "运营", "测试/QA", "DevOps/运维", "安全",
    "嵌入式/硬件", "游戏开发", "UI/设计", "市场/销售", "管理/其他",
]

# 行业关键词映射
INDUSTRY_KEYWORDS = {
    "AI/大模型": ["AI应用开发", "大模型应用开发", "LLM应用开发", "AI Agent开发", "提示词工程"],
    "后端开发": ["Python后端", "Go后端", "Java后端", "后端开发工程师"],
    "前端开发": ["前端开发", "React", "Vue前端", "TypeScript"],
    "数据分析": ["数据分析师", "BI工程师", "数据挖掘"],
    "算法工程师": ["推荐算法", "NLP算法", "CV算法", "搜索算法"],
    "产品经理": ["产品经理", "AI产品经理", "B端产品"],
    "运营": ["内容运营", "用户运营", "增长运营"],
    "测试/QA": ["测试工程师", "自动化测试"],
    "DevOps/运维": ["DevOps", "运维工程师", "k8s"],
    "安全": ["安全工程师", "渗透测试"],
    "嵌入式/硬件": ["嵌入式工程师", "FPGA"],
    "游戏开发": ["Unity开发", "游戏客户端"],
    "UI/设计": ["UI设计师", "UX设计"],
    "市场/销售": ["市场营销", "BD", "销售"],
    "管理/其他": ["项目经理", "技术总监"],
}

SEARCH_KEYWORDS = INDUSTRY_KEYWORDS.get(
    os.environ.get("CRAWL_INDUSTRY", "AI/大模型"),
    INDUSTRY_KEYWORDS["AI/大模型"]
)

JAVA_BACKEND_SIGNAL_KEYWORDS = ["Java", "SpringBoot", "Spring Boot", "SpringCloud", "Spring Cloud", "MyBatis", "JVM"]
JAVA_BACKEND_SIGNAL_MIN_HITS = 2

MAX_PAGES_PER_KEYWORD = 5
REQUEST_DELAY_RANGE = (2, 8)
PAGE_DELAY_RANGE = (5, 12)

SKILL_KEYWORDS = [
    "Python", "Java", "Go", "C++",
    "LangChain", "LlamaIndex", "RAG", "Agent", "Prompt Engineering", "提示词工程",
    "向量数据库", "Embedding", "微调", "Fine-tuning", "LoRA",
    "PyTorch", "TensorFlow", "Transformer",
    "FastAPI", "Flask", "Django",
    "Docker", "Kubernetes", "微服务",
    "OpenAI", "GPT", "通义千问", "文心一言", "Claude", "LLaMA",
]

EDUCATION_KEYWORDS = ["博士", "硕士", "本科", "大专", "中专", "学历不限"]
CRAWL_INTERVAL_HOURS = 6
DATA_RETENTION_MONTHS = 6
