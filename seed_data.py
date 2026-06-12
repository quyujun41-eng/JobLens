# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""生成演示用样本数据（20条真实感AI岗位），供本地开发和展示用"""

import json
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SAMPLE_JOBS = [
    {
        "job_id": "demo_001", "title": "AI应用开发工程师", "company_name": "字节跳动",
        "city": "深圳", "area": "南山区", "salary_min": 25, "salary_max": 45, "salary_unit": "K/月", "salary_months": 15,
        "experience_min": 1, "experience_max": 3, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "LangChain", "RAG", "FastAPI", "Docker"]),
        "description": "负责基于大语言模型的AI应用开发，包括RAG检索增强生成系统、AI Agent设计与实现。要求熟悉Python，有LangChain或LlamaIndex实践经验，了解向量数据库（Milvus/Qdrant），能独立完成从需求到上线的全流程。加分项：有生产环境AI应用落地经验，熟悉Prompt Engineering最佳实践。",
        "source_keyword": "AI应用开发", "url": "https://job.toutiao.com/demo_001",
    },
    {
        "job_id": "demo_002", "title": "大模型应用开发工程师", "company_name": "腾讯",
        "city": "深圳", "area": "南山区", "salary_min": 30, "salary_max": 55, "salary_unit": "K/月", "salary_months": 16,
        "experience_min": 2, "experience_max": 5, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "Agent", "LangChain", "向量数据库", "Embedding", "微服务"]),
        "description": "负责腾讯云AI产品的大模型应用开发，设计并实现多Agent协作系统，构建企业级RAG知识库。技术要求：Python 3年+，熟悉主流LLM API（OpenAI/Claude/通义千问），有Agent开发经验，了解MCP协议优先，熟悉Docker/k8s部署。",
        "source_keyword": "大模型应用开发", "url": "https://careers.tencent.com/demo_002",
    },
    {
        "job_id": "demo_003", "title": "LLM工程师", "company_name": "阿里云",
        "city": "深圳", "area": "福田区", "salary_min": 28, "salary_max": 50, "salary_unit": "K/月", "salary_months": 14,
        "experience_min": 2, "experience_max": 4, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "通义千问", "RAG", "Fine-tuning", "LoRA", "FastAPI"]),
        "description": "负责通义千问系列模型的应用层开发，包括模型微调（LoRA/QLoRA）、RAG系统优化、Prompt工程。熟悉大模型训练和推理框架（vLLM、TGI），有企业级NLP项目经验。了解阿里云PAI/DLC平台者优先。",
        "source_keyword": "LLM应用开发", "url": "https://talent.alibaba.com/demo_003",
    },
    {
        "job_id": "demo_004", "title": "AI Agent开发工程师", "company_name": "华为",
        "city": "深圳", "area": "龙岗区", "salary_min": 22, "salary_max": 40, "salary_unit": "K/月", "salary_months": 13,
        "experience_min": 1, "experience_max": 3, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "Agent", "Function Call", "LangChain", "Docker", "微服务"]),
        "description": "参与华为企业智能助手产品开发，基于Function Call/Tool Use构建多步推理Agent，设计工具链和记忆系统。要求：扎实Python基础，熟悉Anthropic Claude或OpenAI API，了解Agent设计模式（ReAct/CoT），有实际项目经验者优先。",
        "source_keyword": "AI Agent开发", "url": "https://career.huawei.com/demo_004",
    },
    {
        "job_id": "demo_005", "title": "提示词工程师（Prompt Engineer）", "company_name": "OPPO",
        "city": "深圳", "area": "南山区", "salary_min": 18, "salary_max": 35, "salary_unit": "K/月", "salary_months": 13,
        "experience_min": 0, "experience_max": 2, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "Prompt Engineering", "LLM", "Claude", "GPT", "评估框架"]),
        "description": "负责OPPO AI助手的Prompt设计与优化，构建自动化评估体系，推动模型能力在产品中落地。职责：系统性Prompt迭代、建立评估基准、与产品/算法协作。要求：对LLM有深入理解，有Prompt Engineering实战经验，良好的文字表达能力。应届生可投。",
        "source_keyword": "提示词工程", "url": "https://careers.oppo.com/demo_005",
    },
    {
        "job_id": "demo_006", "title": "AI全栈工程师", "company_name": "美团",
        "city": "深圳", "area": "福田区", "salary_min": 25, "salary_max": 45, "salary_unit": "K/月", "salary_months": 14,
        "experience_min": 2, "experience_max": 5, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "React", "FastAPI", "LangChain", "RAG", "Docker", "Redis"]),
        "description": "全栈负责美团AI产品开发，前端React/Vue，后端FastAPI/Flask，AI层接入大模型API。要求有完整AI产品从0到1经验，熟悉RAG架构，了解向量数据库，能独立设计和实现AI功能模块。",
        "source_keyword": "AI应用开发", "url": "https://zhaopin.meituan.com/demo_006",
    },
    {
        "job_id": "demo_007", "title": "AI产品经理（大模型方向）", "company_name": "百度",
        "city": "深圳", "area": "南山区", "salary_min": 25, "salary_max": 50, "salary_unit": "K/月", "salary_months": 15,
        "experience_min": 2, "experience_max": 5, "education_req": "本科",
        "skill_tags": json.dumps(["文心一言", "大模型", "RAG", "Prompt Engineering", "产品设计"]),
        "description": "负责文心一言企业版产品规划，深入理解大模型能力边界，设计AI原生产品功能。要求有SaaS/AI产品经验，能读懂技术方案，有Prompt Engineering基础，具备用户研究能力。",
        "source_keyword": "AI产品经理", "url": "https://talent.baidu.com/demo_007",
    },
    {
        "job_id": "demo_008", "title": "Python后端开发工程师（AI方向）", "company_name": "商汤科技",
        "city": "深圳", "area": "南山区", "salary_min": 20, "salary_max": 38, "salary_unit": "K/月", "salary_months": 14,
        "experience_min": 1, "experience_max": 3, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "FastAPI", "Django", "Docker", "Kubernetes", "MySQL", "Redis"]),
        "description": "负责AI平台后端API开发，与算法团队对接模型服务，设计高可用微服务架构。技术栈：Python/FastAPI，MySQL/PostgreSQL，Redis，Docker/k8s，有AI服务化经验优先。",
        "source_keyword": "Python AI开发", "url": "https://career.sensetime.com/demo_008",
    },
    {
        "job_id": "demo_009", "title": "AI应用开发实习生", "company_name": "旷视科技",
        "city": "北京", "area": "海淀区", "salary_min": 6, "salary_max": 10, "salary_unit": "K/月", "salary_months": None,
        "experience_min": 0, "experience_max": 0, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "LangChain", "RAG", "Embedding"]),
        "description": "参与AI应用产品开发实习，学习RAG系统构建，协助完成Prompt调试和模型评估。要求：在校生，Python基础扎实，有个人AI项目经验（GitHub有repo），对大模型有热情。可转正。",
        "source_keyword": "AI开发 校招", "url": "https://jobs.megvii.com/demo_009",
    },
    {
        "job_id": "demo_010", "title": "大模型工程师（应届）", "company_name": "小米",
        "city": "北京", "area": "海淀区", "salary_min": 18, "salary_max": 30, "salary_unit": "K/月", "salary_months": 15,
        "experience_min": 0, "experience_max": 1, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "PyTorch", "Transformer", "LLM", "微调", "LoRA"]),
        "description": "小米AI团队招聘应届大模型工程师，参与手机AI助手的模型部署与优化。要求：985/211本科及以上，熟悉Transformer架构，有LLM微调经验（LoRA/PEFT），了解模型量化推理。",
        "source_keyword": "大模型 校招", "url": "https://hr.xiaomi.com/demo_010",
    },
    {
        "job_id": "demo_011", "title": "AI Agent研发工程师", "company_name": "深信服",
        "city": "深圳", "area": "南山区", "salary_min": 20, "salary_max": 38, "salary_unit": "K/月", "salary_months": 13,
        "experience_min": 1, "experience_max": 3, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "Agent", "RAG", "向量数据库", "LangChain", "安全"]),
        "description": "基于LLM开发安全运营AI助手，构建面向企业的安全知识RAG系统和自动化分析Agent。要求Python 2年+，了解安全领域（SOC/SIEM）优先，熟悉向量数据库（Weaviate/Milvus），有多Agent协作经验加分。",
        "source_keyword": "AI Agent开发", "url": "https://hr.sangfor.com/demo_011",
    },
    {
        "job_id": "demo_012", "title": "NLP/大模型算法工程师", "company_name": "平安科技",
        "city": "深圳", "area": "福田区", "salary_min": 25, "salary_max": 50, "salary_unit": "K/月", "salary_months": 14,
        "experience_min": 2, "experience_max": 5, "education_req": "硕士",
        "skill_tags": json.dumps(["Python", "PyTorch", "Transformer", "Fine-tuning", "LoRA", "文本分类"]),
        "description": "负责金融领域大模型微调与应用，包括文档理解、智能客服、风险识别。要求：硕士及以上，扎实NLP基础，熟悉主流LLM微调方法，有金融NLP项目经验优先，能阅读英文论文。",
        "source_keyword": "大模型应用开发", "url": "https://talent.pingan.com/demo_012",
    },
    {
        "job_id": "demo_013", "title": "AI应用工程师（知识库方向）", "company_name": "腾讯云",
        "city": "上海", "area": "浦东新区", "salary_min": 28, "salary_max": 48, "salary_unit": "K/月", "salary_months": 15,
        "experience_min": 2, "experience_max": 4, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "RAG", "向量数据库", "Embedding", "Milvus", "LangChain", "知识图谱"]),
        "description": "负责腾讯云知识库产品的核心功能开发，优化RAG检索效果，设计混合检索方案（BM25+向量）。要求：有RAG工程化经验，熟悉向量数据库（Milvus/Pinecone/Qdrant），了解RRF/重排序算法，有大规模知识库落地经验优先。",
        "source_keyword": "AI应用开发", "url": "https://cloud.tencent.com/jobs/demo_013",
    },
    {
        "job_id": "demo_014", "title": "LLM应用开发工程师", "company_name": "网易",
        "city": "杭州", "area": "滨江区", "salary_min": 22, "salary_max": 40, "salary_unit": "K/月", "salary_months": 14,
        "experience_min": 1, "experience_max": 3, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "LangChain", "LlamaIndex", "RAG", "Agent", "FastAPI"]),
        "description": "参与网易AI产品线开发，基于LangChain/LlamaIndex构建游戏AI助手和内容生成工具。要求：Python扎实，有LLM应用开发经验，了解流式输出（SSE/WebSocket），能独立负责AI模块从设计到上线。",
        "source_keyword": "LLM应用开发", "url": "https://hr.netease.com/demo_014",
    },
    {
        "job_id": "demo_015", "title": "AI工程师（MCP/工具链方向）", "company_name": "蚂蚁集团",
        "city": "杭州", "area": "西湖区", "salary_min": 30, "salary_max": 55, "salary_unit": "K/月", "salary_months": 16,
        "experience_min": 3, "experience_max": 6, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "MCP", "Agent", "Function Call", "Tool Use", "分布式系统"]),
        "description": "负责蚂蚁AI基础设施建设，基于MCP协议构建工具生态，设计高可用Agent编排框架。要求：3年+后端/AI工程经验，深度理解Function Call/Tool Use机制，有分布式系统经验，了解MCP协议者强烈优先。",
        "source_keyword": "AI Agent开发", "url": "https://talent.antgroup.com/demo_015",
    },
    {
        "job_id": "demo_016", "title": "AI产品研发工程师（校招）", "company_name": "快手",
        "city": "北京", "area": "海淀区", "salary_min": 20, "salary_max": 35, "salary_unit": "K/月", "salary_months": 15,
        "experience_min": 0, "experience_max": 1, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "LLM", "推荐算法", "RAG", "Docker"]),
        "description": "快手AI团队校招，参与短视频AI助手、内容理解等产品开发。要求：本科及以上，有AI相关实习或项目经验，Python熟练，能快速学习新技术，有开源贡献优先。",
        "source_keyword": "AI应用 应届", "url": "https://jobs.kuaishou.com/demo_016",
    },
    {
        "job_id": "demo_017", "title": "高级AI应用架构师", "company_name": "中兴通讯",
        "city": "深圳", "area": "南山区", "salary_min": 35, "salary_max": 65, "salary_unit": "K/月", "salary_months": 13,
        "experience_min": 5, "experience_max": 10, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "架构设计", "LLM", "RAG", "Agent", "Kubernetes", "微服务"]),
        "description": "负责中兴AI平台整体架构设计，主导大模型应用的生产化落地，制定技术选型和工程规范。要求：5年+AI应用开发经验，有大规模LLM系统架构经验，熟悉高可用分布式架构，有带团队经验优先。",
        "source_keyword": "AI应用开发", "url": "https://hr.zte.com.cn/demo_017",
    },
    {
        "job_id": "demo_018", "title": "RAG系统工程师", "company_name": "百川智能",
        "city": "北京", "area": "朝阳区", "salary_min": 28, "salary_max": 50, "salary_unit": "K/月", "salary_months": 14,
        "experience_min": 2, "experience_max": 5, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "RAG", "向量数据库", "BM25", "Embedding", "Reranking", "LlamaIndex"]),
        "description": "专注RAG系统研发，优化检索精度和生成质量，研究混合检索、查询改写、重排序等技术。要求：深度理解RAG全链路，有从0到1搭建RAG系统经验，了解BM25/DPR/ColBERT等检索模型，能独立调优生产环境检索效果。",
        "source_keyword": "AI应用开发", "url": "https://careers.baichuan.com/demo_018",
    },
    {
        "job_id": "demo_019", "title": "AI运维工程师（MLOps）", "company_name": "京东",
        "city": "上海", "area": "静安区", "salary_min": 22, "salary_max": 40, "salary_unit": "K/月", "salary_months": 14,
        "experience_min": 2, "experience_max": 4, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "Docker", "Kubernetes", "CI/CD", "监控", "LLM", "模型部署"]),
        "description": "负责京东AI平台的模型服务化部署和运维，建设MLOps工作流，保障大模型服务稳定性。要求：熟悉k8s/Docker，有模型服务化经验（TorchServe/Triton/vLLM），了解Prometheus/Grafana监控体系。",
        "source_keyword": "Python AI开发", "url": "https://zhaopin.jd.com/demo_019",
    },
    {
        "job_id": "demo_020", "title": "AI应用开发工程师（初级）", "company_name": "深圳AI独角兽",
        "city": "深圳", "area": "宝安区", "salary_min": 12, "salary_max": 20, "salary_unit": "K/月", "salary_months": 12,
        "experience_min": 0, "experience_max": 2, "education_req": "本科",
        "skill_tags": json.dumps(["Python", "LangChain", "Flask", "RAG", "Docker"]),
        "description": "初创AI公司招聘初级工程师，参与企业AI助手产品开发。要求：Python基础扎实，了解LangChain框架，有个人AI项目经验（能展示代码），对AI充满热情，有快速学习能力。应届生/1年经验均可。",
        "source_keyword": "AI应用 应届", "url": "https://example.com/demo_020",
    },
]


def seed():
    from models import Company, Job, app, db
    with app.app_context():
        existing = {j.job_id for j in Job.query.with_entities(Job.job_id).all()}
        now = datetime.datetime.now()
        added = 0
        for d in SAMPLE_JOBS:
            if d["job_id"] in existing:
                continue
            # 公司
            company = Company.query.filter_by(name=d["company_name"]).first()
            if not company:
                company = Company(name=d["company_name"], first_seen_at=now, last_seen_at=now)
                db.session.add(company)
                db.session.flush()

            job = Job(
                job_id=d["job_id"],
                title=d["title"],
                company_id=company.id,
                city=d["city"],
                area=d["area"],
                salary_min=d["salary_min"],
                salary_max=d["salary_max"],
                salary_unit=d["salary_unit"],
                salary_months=d["salary_months"],
                experience_min=d["experience_min"],
                experience_max=d["experience_max"],
                education_req=d["education_req"],
                skill_tags=d["skill_tags"],
                description=d["description"],
                source_keyword=d["source_keyword"],
                url=d["url"],
                first_seen_at=now,
                last_seen_at=now,
                is_active=True,
            )
            db.session.add(job)
            added += 1

        db.session.commit()
        print(f"种子数据写入完成，新增 {added} 条岗位")


if __name__ == "__main__":
    seed()
