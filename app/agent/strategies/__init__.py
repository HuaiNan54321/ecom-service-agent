"""Agent 执行策略模块。

包含多种 Agent 执行范式：
- Plan-and-Execute：先规划再执行，适合复杂多步骤请求
- Reflexion：自我评估与迭代改进
- REWOO：预规划 + 批量执行，高效处理并行任务

每种策略实现统一接口，可由 EcomAgent 按需切换。
"""
