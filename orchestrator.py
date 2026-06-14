# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""Orchestrator-Workers 模式：Orchestrator 将复杂问题分解为子任务，并发派发给专业 Worker
每个 Worker 独立执行、并行运行，Orchestrator 汇总所有结果综合回答"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

_WORKERS = {
    "market_worker":    "获取市场行情：薪资分布、技能热度、招聘趋势",
    "job_search_worker":"搜索匹配岗位：返回职位列表和详情",
    "resume_worker":    "简历匹配分析：评估与岗位的契合度",
    "company_worker":   "企业情报：公司薪资排名、规模、行业",
}

_WORKER_TIMEOUT = 20  # 单个 Worker 超时秒数


# ── Orchestrator：任务分解 ───────────────────────────────────

def decompose_task(question: str) -> list:
    """Orchestrator 分析问题，返回子任务列表 [{worker, task, priority}]"""
    prompt = f"""你是任务调度专家，分析用户问题并分配给合适的Worker。

用户问题：{question}

可用Worker：
{json.dumps(_WORKERS, ensure_ascii=False, indent=2)}

选择1-3个最相关的Worker，给出具体执行指令。只返回JSON数组：
[{{"worker": "worker名称", "task": "具体指令（20字内）", "priority": 1-3}}]
priority越小越重要，1最高。"""

    try:
        from ai_features import _call_once
        resp = _call_once([{"role": "user", "content": prompt}], max_tokens=250)
        start = resp.find("[")
        end = resp.rfind("]") + 1
        tasks = json.loads(resp[start:end])
        return sorted([t for t in tasks if t.get("worker") in _WORKERS],
                      key=lambda x: x.get("priority", 2))
    except Exception:
        return [{"worker": "job_search_worker", "task": question[:30], "priority": 1}]


# ── Workers：专业执行单元 ────────────────────────────────────

def _run_market_worker(task: str) -> str:
    from agent import _execute_tool
    parts = []
    for stat in ["salary", "skills", "trend"]:
        try:
            parts.append(_execute_tool("get_market_stats", {"stat_type": stat}))
        except Exception:
            pass
    return "\n\n".join(parts) or "暂无市场数据"


def _run_job_search_worker(task: str) -> str:
    from agent import _execute_tool
    try:
        return _execute_tool("search_jobs", {"keyword": task[:40], "top_k": 8})
    except Exception as e:
        return f"搜索失败: {e}"


def _run_resume_worker(task: str, resume: str) -> str:
    from agent import _execute_tool
    if not resume:
        return "未提供简历，跳过匹配分析"
    try:
        job_result = _execute_tool("search_jobs", {"keyword": task[:30], "top_k": 3})
        for line in job_result.split("\n")[1:]:
            if line.startswith("["):
                job_id = line[1:line.index("]")]
                return _execute_tool("match_resume", {"job_id": job_id, "resume": resume})
        return "未找到可匹配岗位"
    except Exception as e:
        return f"匹配失败: {e}"


def _run_company_worker(task: str) -> str:
    from agent import _execute_tool
    try:
        return _execute_tool("get_market_stats", {"stat_type": "companies"})
    except Exception as e:
        return f"获取企业数据失败: {e}"


def _dispatch_worker(worker: str, task: str, resume: str = "") -> str:
    """路由到对应 Worker"""
    from models import app as flask_app
    with flask_app.app_context():
        if worker == "market_worker":
            return _run_market_worker(task)
        elif worker == "job_search_worker":
            return _run_job_search_worker(task)
        elif worker == "resume_worker":
            return _run_resume_worker(task, resume)
        elif worker == "company_worker":
            return _run_company_worker(task)
    return f"未知Worker: {worker}"


# ── 主入口 ───────────────────────────────────────────────────

def orchestrate_stream(question: str, history: list, resume: str = ""):
    """Orchestrator-Workers 主入口，yield SSE dict

    SSE 事件类型（新增）：
      orchestrate_tasks  {tasks}          — 分解出的子任务列表
      worker_done        {worker, preview} — 某 Worker 完成
      worker_error       {worker, error}   — 某 Worker 失败
      orchestrate_synth  {}               — 开始综合
    """
    # Step 1: Orchestrator 分解任务
    yield {"type": "orchestrate_tasks", "tasks": [], "status": "分解中..."}
    tasks = decompose_task(question)
    yield {"type": "orchestrate_tasks", "tasks": tasks, "status": "已分解"}

    # Step 2: 并行 Worker 执行
    worker_results: dict = {}
    with ThreadPoolExecutor(max_workers=min(len(tasks), 4)) as pool:
        futures = {
            pool.submit(_dispatch_worker, t["worker"], t["task"], resume): t
            for t in tasks
        }
        for future in as_completed(futures, timeout=_WORKER_TIMEOUT + 5):
            task = futures[future]
            try:
                result = future.result(timeout=_WORKER_TIMEOUT)
                worker_results[task["worker"]] = result
                yield {"type": "worker_done", "worker": task["worker"],
                       "preview": result[:150]}
            except TimeoutError:
                worker_results[task["worker"]] = "Worker 执行超时"
                yield {"type": "worker_error", "worker": task["worker"], "error": "超时"}
            except Exception as e:
                worker_results[task["worker"]] = f"执行出错: {e}"
                yield {"type": "worker_error", "worker": task["worker"], "error": str(e)}

    # Step 3: Orchestrator 综合所有 Worker 输出
    yield {"type": "orchestrate_synth"}
    context = "\n\n".join(
        f"【{w}】\n{r}" for w, r in worker_results.items()
    )
    history_msgs = [{"role": h["role"], "content": h["content"]} for h in history[-4:]]
    synth_msg = (
        f"以下是各专业Worker收集的数据：\n\n{context[:3000]}\n\n"
        f"用户原始问题：{question}\n\n"
        "请综合上述数据给出完整回答，重要数据加粗，层次清晰。"
    )
    history_msgs.append({"role": "user", "content": synth_msg})

    try:
        from ai_features import _stream_chunks
        for text in _stream_chunks(history_msgs, max_tokens=1200):
            yield {"type": "text", "text": text}
    except Exception as e:
        yield {"type": "error", "error": str(e)}

    yield {"type": "done"}
