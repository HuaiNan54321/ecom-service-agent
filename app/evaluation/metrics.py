"""评估指标：过程指标 + 结果指标（代码规则 + LLM judge）（第9期）。

分两层、两类（与 README 的 2×2 对应）：

            代码规则                          LLM judge
过程指标   tool_accuracy / tool_efficiency    judge_process_soundness
           / token_cost_pass / route_match
结果指标   intent_match / keyword_coverage    judge_answer_quality
           / requires_human_match             / judge_faithfulness

代码规则评分统一约定：返回 float | None。None 表示该用例未指定此维度（如问候用例
没有 expected_tools），聚合时应跳过而不是记 0，避免拖垮均值。
LLM judge 仿照 app/agent/memory/extraction.py 的「格式化 → 调用 LLM → 解析 JSON」
自由函数风格，temperature=0.0，解析失败有兜底返回。
"""

from __future__ import annotations

import json

from openai import OpenAI

from app.prompts.evaluation import (
    ANSWER_QUALITY_PROMPT,
    HALLUCINATION_PROMPT,
    PROCESS_SOUNDNESS_PROMPT,
)
from app.evaluation.trace import ToolObservation


# ============================================================
# 过程指标（代码规则）
# ============================================================
def tool_accuracy(expected: list[str], called: list[str]) -> float | None:
    """工具调用准确率：期望工具被实际调用的比例。expected 为空返回 None。"""
    if not expected:
        return None
    called_set = set(called)
    hit = sum(1 for t in expected if t in called_set)
    return hit / len(expected)


def tool_efficiency(min_calls: int | None, actual: int) -> float | None:
    """工具调用效率：理论最少次数 / 实际次数，越接近 1 越高效。

    min_calls 为 None 返回 None。actual 为 0 时：若理论也为 0 则满分，否则返回 None
    （没调用工具无从谈效率，交给其他维度判断）。
    """
    if min_calls is None:
        return None
    if actual <= 0:
        return 1.0 if min_calls == 0 else None
    return min(1.0, min_calls / actual)


def token_cost_pass(total_tokens: int, budget: int | None) -> bool | None:
    """token 消耗是否在预算内。budget 为 None 返回 None（不设上限）。"""
    if budget is None:
        return None
    return total_tokens <= budget


def route_match(expected: str | None, actual: str | None) -> float | None:
    """（多 Agent）路由是否命中。expected 为 None 返回 None。"""
    if expected is None:
        return None
    return 1.0 if expected == actual else 0.0


# ============================================================
# 结果指标（代码规则）
# ============================================================
def intent_match(expected: str | None, actual: str) -> float | None:
    """意图识别是否命中。expected 为 None 返回 None。"""
    if expected is None:
        return None
    return 1.0 if expected == actual else 0.0


def keyword_coverage(expected: list[str], reply: str) -> float | None:
    """关键信息完整性：期望关键词在 reply 中出现的比例。expected 为空返回 None。"""
    if not expected:
        return None
    hit = sum(1 for kw in expected if kw in reply)
    return hit / len(expected)


def requires_human_match(expected: bool | None, actual: bool) -> float | None:
    """转人工判断是否正确。expected 为 None 返回 None。"""
    if expected is None:
        return None
    return 1.0 if expected == actual else 0.0


# ============================================================
# LLM judge 共用：解析 JSON（剥离可能的 ```代码块）
# ============================================================
def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(raw)


# ============================================================
# 结果指标（LLM judge）
# ============================================================
def judge_answer_quality(
    client: OpenAI,
    model: str,
    user_input: str,
    reply: str,
    reference: list[str] | None = None,
) -> tuple[float, str]:
    """回答质量 judge：返回 (score 1-5, reason)。解析失败返回 (0.0, 原因)。"""
    ref_text = "、".join(reference) if reference else "（无）"
    prompt = ANSWER_QUALITY_PROMPT.format(
        user_input=user_input, reply=reply, reference=ref_text
    )
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json(response.choices[0].message.content or "")
        return float(data["score"]), data.get("reason", "")
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        return 0.0, f"质量评分解析失败: {e}"


def judge_faithfulness(
    client: OpenAI,
    model: str,
    reply: str,
    observations: list[ToolObservation],
) -> tuple[float, str]:
    """幻觉检测 judge：对照工具返回核查 reply 是否忠实。

    返回 (1.0 忠实 / 0.0 有幻觉, reason)。解析失败返回 (0.0, 原因)。
    """
    if observations:
        obs_text = "\n".join(
            f"- {obs.name}({obs.arguments}) → {obs.result}" for obs in observations
        )
    else:
        obs_text = "（本次会话未调用任何工具）"
    prompt = HALLUCINATION_PROMPT.format(reply=reply, observations=obs_text)
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json(response.choices[0].message.content or "")
        faithful = bool(data["faithful"])
        return (1.0 if faithful else 0.0), data.get("reason", "")
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        return 0.0, f"幻觉检测解析失败: {e}"


# ============================================================
# 过程指标（LLM judge）
# ============================================================
def judge_process_soundness(
    client: OpenAI,
    model: str,
    user_input: str,
    tool_sequence: list[str],
) -> tuple[float, str]:
    """推理过程合理性 judge：判断工具选择/顺序是否合理。

    返回 (score 1-5, reason)。解析失败返回 (0.0, 原因)。
    """
    seq_text = " → ".join(tool_sequence) if tool_sequence else "（未调用任何工具）"
    prompt = PROCESS_SOUNDNESS_PROMPT.format(
        user_input=user_input, tool_sequence=seq_text
    )
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json(response.choices[0].message.content or "")
        return float(data["score"]), data.get("reason", "")
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        return 0.0, f"过程评分解析失败: {e}"
