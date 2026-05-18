"""Multi-Agent 协作模块。

实现客服路由与多 Agent 调度：
- Router：意图分类，按用户意图路由到专业子 Agent
- SubAgent：专业子 Agent（售前咨询、售后处理、投诉升级）
- MultiAgentOrchestrator：编排器，协调路由和执行
"""

from app.multi_agent.agents import SubAgent
from app.multi_agent.orchestrator import MultiAgentOrchestrator
from app.multi_agent.router import Router

__all__ = ["MultiAgentOrchestrator", "Router", "SubAgent"]
