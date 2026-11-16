"""评估指标：过程指标 + 结果指标（代码规则 + LLM judge）（第9期）。

分两层、两类（与 README 的 2×2 对应）：

            代码规则                          LLM judge
过程指标   tool_accuracy / tool_efficiency    judge_process_soundness
           / token_cost_pass / route_match
结果指标   intent_match / keyword_coverage    judge_answer_quality
           / requires_human_match             / judge_faithfulness

代码规则评分统一约定：返回 float | None。None 表示该用例未指定此维度（如问候用例
没有 expected_tools），聚合时应跳过而不是记 0，避免拖垮均值。
语言裁判使用独立量表和逐字引文；缺少证据、协议错误、接口异常时返回待复核原因。
"""

from __future__ import annotations

import json

from openai import APIError, OpenAI

from app.prompts.evaluation import (
    ANSWER_QUALITY_PROMPT,
    BUSINESS_CLAIM_PROMPT,
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


def token_cost_pass(total_tokens: int | None, budget: int | None) -> bool | None:
    """未设预算或缺少用量时返回未知。"""
    if budget is None or total_tokens is None:
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


def _judge(client, model, rubric, data, evidence, field) -> tuple[float | None, str]:
    """校验裁判的分值与原文引用；未知结果连同原因交给人工复核。"""
    try:
        response = client.chat.completions.create(
            model=model, temperature=0.0,
            messages=[{"role": "system", "content": rubric},
                      {"role": "user", "content": json.dumps({**data, "evidence": evidence}, ensure_ascii=False)}],
        )
        choice = response.choices[0]
        if choice.finish_reason != "stop" or getattr(choice.message, "refusal", None):
            return None, "待复核：裁判拒答或回复未完整结束"
        verdict = json.loads(choice.message.content)
        if not isinstance(verdict, dict) or field not in verdict:
            return None, "待复核：裁判缺少结论字段"
        reason = verdict.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return None, "待复核：裁判未给出理由"
        value = verdict[field]
        if value is None:
            return None, f"待复核：{reason}"
        if field in ("faithful", "has_claim"):
            valid = type(value) is bool
        else:
            valid = type(value) is int and 1 <= value <= 5
        if not valid:
            return None, "待复核：裁判结论的类型或分值不符合量表"
        source, quote = verdict.get("source"), verdict.get("quote")
        if (not isinstance(source, str) or source not in evidence
                or not isinstance(quote, str) or not quote.strip() or quote not in evidence[source]):
            return None, "待复核：裁判的来源或引文无法在评审材料中定位"
        if field == "has_claim" and quote != evidence["reply"]:
            return None, "待复核：识别业务断言时须引用完整回复"
        return float(value), f"{reason} [{source}：{quote}]"
    except APIError as exc:
        return None, f"待复核：裁判接口异常（{type(exc).__name__}）"
    except (AttributeError, IndexError, TypeError, ValueError):
        return None, "待复核：裁判回复格式无效"


def judge_answer_quality(client: OpenAI, model: str, user_input: str, reply: str,
                         reference: list[str] | None = None) -> tuple[float | None, str]:
    """评阅回答的清晰与完整程度，保留作为评分依据的回复原文。"""
    return _judge(client, model, ANSWER_QUALITY_PROMPT,
                  {"question": user_input, "reference": reference or []}, {"reply": reply}, "score")


def judge_faithfulness(client: OpenAI, model: str, reply: str,
                       observations: list[ToolObservation]) -> tuple[float | None, str]:
    """核对业务断言，事实引文必须出自实际工具返回。"""
    evidence = {f"T{i}": obs.result for i, obs in enumerate(observations, 1)}
    if not evidence:
        return None, "待复核：本次没有工具返回可供核查"
    tools = {f"T{i}": obs.name for i, obs in enumerate(observations, 1)}
    return _judge(client, model, HALLUCINATION_PROMPT,
                  {"reply": reply, "tools": tools}, evidence, "faithful")


def judge_process_soundness(client: OpenAI, model: str, user_input: str,
                            tool_sequence: list[str]) -> tuple[float | None, str]:
    """评阅工具选择与先后次序，工具名按实际调用逐项编号。"""
    evidence = {"question": user_input, **{f"T{i}": name for i, name in enumerate(tool_sequence, 1)}}
    return _judge(client, model, PROCESS_SOUNDNESS_PROMPT, {"tool_sequence": tool_sequence}, evidence, "score")


def judge_greeting_claim(client: OpenAI, model: str, reply: str) -> tuple[float | None, str]:
    """在无工具的问候题上识别答复中额外添加的业务断言。"""
    return _judge(client, model, BUSINESS_CLAIM_PROMPT, {}, {"reply": reply}, "has_claim")
