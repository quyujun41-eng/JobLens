# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""Evaluator-Optimizer 模式：Agent 生成回答 → Evaluator 打分 → 不达标则附带反馈重生成
最多循环 max_rounds 轮，每轮继承上轮反馈，输出质量递增"""

import json

_EVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "score":    {"type": "integer", "description": "0-10"},
        "passed":   {"type": "boolean", "description": ">=7 视为通过"},
        "feedback": {"type": "string",  "description": "改进建议，50字内"},
    },
    "required": ["score", "passed", "feedback"],
    "additionalProperties": False,
}

_PASS_THRESHOLD = 7


def evaluate_output(question: str, answer: str) -> dict:
    """Evaluator：对 Agent 输出打质量分，返回 {score, passed, feedback}"""
    if not answer.strip():
        return {"score": 0, "passed": False, "feedback": "回答为空"}

    prompt = f"""你是输出质量评审专家，评估AI助手的求职分析回答质量。

用户问题：{question}

AI回答：
{answer[:1500]}

评估维度（各2.5分）：
1. 数据真实性：使用真实数据而非编造
2. 问题针对性：直接回答了用户问题
3. 建议可行性：提供了具体可执行建议
4. 表达简洁性：不冗余，重点突出

只返回JSON：{{"score": 整数0-10, "passed": true/false, "feedback": "改进建议"}}"""

    try:
        from ai_features import _call_structured
        result = _call_structured([{"role": "user", "content": prompt}], _EVAL_SCHEMA, max_tokens=150)
        if result and "score" in result:
            result["passed"] = result["score"] >= _PASS_THRESHOLD
            return result
    except Exception:
        pass
    return {"score": 8, "passed": True, "feedback": ""}


def evaluator_optimizer_stream(
    question: str, history: list, resume: str = "",
    session_id: str = "", max_rounds: int = 3
):
    """Evaluator-Optimizer 主入口：生成→评估→优化循环，yield SSE dict

    SSE 事件类型（新增）：
      eval_round  {round, max}    — 开始第N轮生成
      eval_score  {score, passed, feedback}  — 本轮评分
    """
    from agent import agent_stream

    current_history = list(history)
    answer_so_far = ""

    for round_num in range(max_rounds):
        yield {"type": "eval_round", "round": round_num + 1, "max": max_rounds}

        # 生成本轮回答（复用 agent_stream，转发所有事件给客户端）
        round_answer_parts = []
        for chunk in agent_stream(question, current_history, resume, session_id=session_id):
            yield chunk
            if chunk.get("type") == "text":
                round_answer_parts.append(chunk["text"])
            if chunk.get("type") == "done":
                break

        answer_so_far = "".join(round_answer_parts)

        # 最后一轮不再评估，直接结束
        if round_num == max_rounds - 1:
            break

        # Evaluator 打分
        eval_result = evaluate_output(question, answer_so_far)
        yield {
            "type": "eval_score",
            "round": round_num + 1,
            "score": eval_result["score"],
            "passed": eval_result["passed"],
            "feedback": eval_result["feedback"],
        }

        if eval_result["passed"]:
            break

        # 把本轮回答 + Evaluator 反馈注入历史，驱动下一轮改进
        current_history = list(history) + [
            {"role": "assistant", "content": answer_so_far},
            {"role": "user",      "content": f"你的上一个回答评分 {eval_result['score']}/10，请改进：{eval_result['feedback']}"},
        ]
        question = "请根据反馈改进你的回答，要更准确、更有数据支撑。"

    yield {"type": "eval_done", "rounds_used": round_num + 1}
