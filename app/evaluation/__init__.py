"""Agent 评估模块（第9期）。

提供 Agent 输出质量的评估框架：测试用例管理、自动评分、
多维度指标（准确性、完整性、响应质量）对比分析。

核心组件：
- Sandbox：隔离、可复现地重跑测试集，并采集运行全过程（token / 工具轨迹 / 回答）。
- Evaluator：在采集到的轨迹上做过程层 + 结果层双层评分（代码规则 + LLM judge）。
"""

from app.evaluation.dataset import EvalCase, load_dataset
from app.evaluation.evaluator import EvalResult, Evaluator
from app.evaluation.sandbox import Sandbox
from app.evaluation.trace import LLMCallRecord, RunTrace, ToolObservation

__all__ = [
    "EvalCase",
    "load_dataset",
    "Sandbox",
    "RunTrace",
    "LLMCallRecord",
    "ToolObservation",
    "Evaluator",
    "EvalResult",
]
