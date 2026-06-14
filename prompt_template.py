# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""PromptTemplate：结构化提示词模板管理，支持变量插值、外部文件加载、版本控制
对标 LangChain PromptTemplate / Spring AI PromptTemplate"""

import re
import json
from pathlib import Path


class PromptTemplate:
    """提示词模板，{variable} 格式变量插值"""

    def __init__(self, template: str, input_variables: list = None, name: str = ""):
        self.template = template
        self.name = name
        found = re.findall(r'\{(\w+)\}', template)
        self.input_variables = input_variables or list(dict.fromkeys(found))

    def format(self, **kwargs) -> str:
        """变量插值，未传入的变量保持原样"""
        result = self.template
        for k, v in kwargs.items():
            result = result.replace(f'{{{k}}}', str(v))
        return result

    def to_messages(self, role: str = "user", **kwargs) -> list:
        """格式化后包装为对话消息列表"""
        return [{"role": role, "content": self.format(**kwargs)}]

    def partial(self, **kwargs) -> "PromptTemplate":
        """预填充部分变量，返回新模板（偏函数模式）"""
        new_tpl = self.format(**kwargs)
        remaining = [v for v in self.input_variables if v not in kwargs]
        return PromptTemplate(new_tpl, remaining, self.name)

    def __repr__(self):
        return f"PromptTemplate(name={self.name!r}, vars={self.input_variables})"


class PromptLibrary:
    """提示词库：注册、加载、管理所有模板"""

    def __init__(self):
        self._templates: dict = {}

    def register(self, name: str, template: str, input_variables: list = None) -> PromptTemplate:
        t = PromptTemplate(template, input_variables, name=name)
        self._templates[name] = t
        return t

    def get(self, name: str) -> PromptTemplate:
        if name not in self._templates:
            raise KeyError(f"模板 {name!r} 不存在，已注册：{list(self._templates)}")
        return self._templates[name]

    def load_from_dir(self, dir_path: str) -> int:
        """从目录批量加载 .txt / .json 模板文件"""
        loaded = 0
        for path in Path(dir_path).glob("*.txt"):
            self.register(path.stem, path.read_text(encoding="utf-8"))
            loaded += 1
        for path in Path(dir_path).glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.register(data["name"], data["template"], data.get("input_variables"))
            loaded += 1
        return loaded

    def list_templates(self) -> list:
        return [{"name": t.name, "variables": t.input_variables}
                for t in self._templates.values()]

    def __len__(self):
        return len(self._templates)

    def __contains__(self, name):
        return name in self._templates


# ── 全局提示词库 ───────────────────────────────────────────────

library = PromptLibrary()

library.register(
    "match_score",
    """你是一位资深HR，请评估以下简历与岗位的匹配程度。

岗位描述：
{jd_text}

求职者简历：
{resume_text}

只返回JSON：{{"score": <0-100>, "matched": ["已具备技能，最多3条"], "reason": "一句话总结，30字内"}}""",
    ["jd_text", "resume_text"],
)

library.register(
    "query_expansion",
    """你是搜索引擎优化专家。用户在招聘网站搜索：「{query}」

请生成 {n} 个语义等价或高度相关的搜索变体，涵盖同义词、缩写、相关技术词，适合中文招聘场景，每变体5-15字。

只返回JSON数组：["变体1", "变体2", "变体3"]""",
    ["query", "n"],
)

library.register(
    "interview_prep",
    """你是资深面试官，请根据以下岗位生成面试准备材料。

公司：{company}  岗位：{title}
JD要求：{jd_text}{resume_section}

输出（Markdown格式）：

## 核心考察方向（3-5个）
## 预测面试题
**技术题（5题）**
**场景/行为题（3题）**
## 重点备考提示""",
    ["company", "title", "jd_text", "resume_section"],
)

library.register(
    "gap_analysis",
    """你是职业发展顾问，分析求职者与目标岗位的差距。

岗位要求：
{jd_text}

求职者简历：
{resume_text}

输出（Markdown格式）：

## 已具备的优势
## 需要补充的技能
**可快速补充（1-4周）**
**需要长期积累（1-3月+）**
## 建议行动计划（3步）""",
    ["jd_text", "resume_text"],
)

library.register(
    "summary_memory",
    "请将以下对话历史压缩为100字以内的摘要，保留关键信息（岗位名称、用户偏好、已分析结果）：\n\n{history_text}",
    ["history_text"],
)

library.register(
    "evaluator",
    """你是输出质量评审专家，评估AI求职助手的回答质量。

用户问题：{question}

AI回答：
{answer}

评估维度（各2.5分）：数据真实性、问题针对性、建议可行性、表达简洁性

只返回JSON：{{"score": 整数0-10, "passed": true/false, "feedback": "改进建议50字内"}}""",
    ["question", "answer"],
)

library.register(
    "company_intel",
    """你是商业分析师，根据以下招聘JD推断公司核心业务方向。

公司：{company}  岗位：{title}
JD：{jd_text}

输出（Markdown格式）：

## 核心业务方向
## 技术栈偏向
## 岗位真实需求
## 面试重点预判""",
    ["company", "title", "jd_text"],
)
