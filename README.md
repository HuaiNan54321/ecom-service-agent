# Ecom-Service-Agent: 从0到1实战企业级电商客服Agent系统

## 求职辅导

我目前也在做 **AI 方向的求职辅导**，服务内容包括：

- 简历精修（针对 AI / Agent 岗位优化）
- 项目包装（这是最核心的，根据你过往的工作/实习和项目经历，定制化包装成agent项目，尽量多地融入agent主流技术，以及给你一份面试时口述的逐字稿）
- 模拟面试（结合你的项目经历和大厂常问的问题进行深挖）
- 全程陪跑（从投递到拿 offer）

有需要的同学可以添加我的微信：**HuaiNan54321**，备注「求职辅导」。

---

## 快速开始（Quick Start）

跑起来只需要一个 OpenAI API Key，5 分钟即可看到「小夕」上线对话。

```bash
# 1. 进入项目并创建虚拟环境（Python 3.11+）
cd ecom-service-agent
python3.11 -m venv .venv && source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env，至少填入：
#   OPENAI_API_KEY=sk-你的key
#   （可选）OPENAI_BASE_URL=https://... 如用中转/代理
#   （可选）MODEL_NAME=gpt-4o-mini

# 4. 构建知识库索引（RAG 检索需要，首次运行一次即可）
python -m app.scripts.build_kb_index

# 5. 启动对话
python main.py
```

启动后直接输入问题即可，试试这些：

- `我的订单还没发货，怎么回事？` —— 触发订单 + 物流查询
- `有没有宽松透气的裤子推荐？` —— 触发商品推荐技能
- `这件衣服质量有问题，我要退货` —— 触发退货退款流程

每条回复底部会显示 `[意图 | 置信度 | 是否转人工]`。对话中还支持这些命令：

| 命令 | 作用 |
|------|------|
| `skills` | 查看已加载的技能模块 |
| `memory` | 查看短期 / 长期记忆 |
| `reset` | 清空当前会话 |
| `quit` / `exit` | 退出 |

**开启进阶能力**（可选，改 `.env` 后重启即可）：

- `MULTI_AGENT_ENABLED=true` —— 多 Agent 协作（售前/售后/投诉分流）
- `MCP_ENABLED=true` —— 通过 MCP 协议调用工具（需另起 `python mcp_server/server.py`）
- `RAG_BACKEND=chroma` —— 换用 Chroma 向量数据库（需 `pip install chromadb`）

**跑评估 & 测试**：

```bash
python -m app.scripts.run_eval        # 离线评估（沙箱重跑黄金测试集 + LLM judge）
pytest                                # 运行全部单元测试
```

---

## 背景

大家好，我是淮南，Top 985科班出身，有多家大厂后端 & AI Agent 研发经验。

我在小红书上运营着一个 **AI Agent 面经系列**，分享了我面试字节、阿里、MiniMax 等多家公司 AI Agent 岗位的真实面经，目前已经积累了 5000+ 粉丝。在和大家交流的过程中，我发现很多同学对 Agent 相关技术很感兴趣，但苦于没有一个**完整的、可跟着动手的实战项目**。

所以我决定做这件事 —— **以电商客服为场景，从0到1带大家实战一个企业级 Agent 系统**。

### 为什么选电商客服？

电商客服是 Agent 最经典的落地场景之一：业务逻辑清晰（查订单、退换货、推荐商品、售后处理），大家容易理解，面试中也经常被问到。做完这个项目，你不仅能掌握 Agent 核心技术栈，还能直接写进简历。

### 更新方式

我会在小红书上**每期更新一个 Agent 相关技术**，对应本仓库的一个 commit / tag。特别复杂的技术点会拆成 2 期。你可以跟着每期笔记，checkout 到对应的 tag，一步一步跟着做。

**扫码关注我的小红书，获取每期更新通知：**

<p align="center">
  <img src="./淮南-小红书.jpg" alt="淮南-小红书" width="300" />
</p>

### 技术演进路线（更新预告）

本项目会按照由浅入深的节奏，逐步叠加 Agent 相关技术：

**基础篇**
- 纯 Prompt 实现客服对话
- 结构化输出（Structured Output）
- 多轮对话管理

**进阶篇**
- ReAct 范式的 Agent（思考-行动交替，最经典的 Agent 范式）
- 工具调用 / Function Calling（查订单、查库存等）
- MCP（Model Context Protocol）集成
- RAG 检索增强生成（接入商品库、FAQ、退换货政策等）

**高级篇**
- Multi-Agent 协作（客服路由、售前售后分流）
- Memory：短期记忆 & 长期记忆
- Skill：可复用的能力模块（退货处理、订单跟踪等标准化流程）✅
- Agent 评估体系 ✅

**生产篇**
- Guardrails 安全护栏（Prompt Injection 检测、输出幻觉校验、敏感信息过滤、意图越界拦截）
- Human-in-the-Loop 人机协作（置信度评估与自动转人工、Agent↔真人客服交接协议、上下文传递）
- Agent Observability 可观测性（调用链 Trace、Token/延迟指标采集、工具成功率看板、异常告警）

> 以上为初步规划，实际更新可能会根据大家的反馈进行调整。

---

## 项目架构 & 更新历史

> 这是本项目最核心的部分，会随着每一期的更新持续完善。

### 当前架构

```
ecom-service-agent/
├── main.py                        # CLI 入口（支持单 Agent / Multi-Agent 模式切换 + memory/skills 命令）
├── requirements.txt
├── .env.example
│
├── app/                           # 主 Bot 全部代码 + 数据
│   ├── config/
│   │   └── settings.py            # 配置管理（从 .env 读取，含 MCP / RAG / Multi-Agent / Memory / Skill / Evaluation 配置）
│   ├── prompts/
│   │   ├── customer_service.py    # 电商客服 system prompt（含工具使用指南 + 记忆能力）
│   │   ├── summarizer.py          # 历史摘要 prompt
│   │   ├── agents.py              # Multi-Agent 子 Agent prompt（售前/售后/投诉 + Router）
│   │   ├── memory.py              # 记忆提取 prompt（短期 STM / 长期 LTM 事实抽取）
│   │   └── evaluation.py          # LLM-as-judge prompt（回答质量 / 幻觉 / 过程合理性）
│   ├── schemas/
│   │   └── response.py            # 结构化输出 schema（Pydantic）
│   ├── agent/                     # Agent 核心实现 + 全部 Agent 技术栈（tools / rag / skills）
│   │   ├── chat.py                # 核心 ReAct 循环（集成 MemoryManager + SkillManager）
│   │   ├── summarizer.py          # LLM 自我压缩老对话（支持工具消息）
│   │   ├── storage.py             # 会话 JSON 持久化（含短期记忆）
│   │   ├── memory/                # 记忆系统（第7期）
│   │   │   ├── __init__.py        # 导出 MemoryManager / ShortTermMemory / LongTermMemory
│   │   │   ├── manager.py         # MemoryManager：统一管理短期 + 长期记忆
│   │   │   ├── short_term.py      # 短期记忆：会话内事实提取
│   │   │   ├── long_term.py       # 长期记忆：跨会话持久化（JSON per user）
│   │   │   └── extraction.py      # LLM 事实提取（共用模块）
│   │   ├── skills/                # Skill 模块（第8期）：代码 + 技能内容分层
│   │   │   ├── __init__.py        # 导出 SkillManager / SkillMeta
│   │   │   ├── loader.py          # SkillManager：扫描、发现、加载 SKILL.md（渐进式披露）
│   │   │   └── definitions/       # 技能内容（遵循 Agent Skills 开放标准，每个一个 SKILL.md）
│   │   │       ├── process-return/
│   │   │       │   └── SKILL.md   # 退货退款处理技能（确认订单→校验资格→退款→告知进度）
│   │   │       ├── track-order/
│   │   │       │   └── SKILL.md   # 订单物流跟踪技能（查单→查物流→综合建议）
│   │   │       └── product-recommend/
│   │   │           └── SKILL.md   # 商品推荐技能（了解需求→查偏好→搜索→推荐）
│   │   ├── strategies/            # (upcoming) Agent 执行策略
│   │   ├── tools/                 # 电商工具集（Function Calling）
│   │   │   ├── mock_data.py       # Mock 数据：订单、商品、物流
│   │   │   ├── registry.py        # 本地工具注册表 + OpenAI schema + 分发执行
│   │   │   ├── manager.py         # ToolManager：统一管理本地 + MCP 工具（支持 allowed_tools 过滤）
│   │   │   ├── order.py           # 查询订单详情
│   │   │   ├── product.py         # 搜索商品信息
│   │   │   ├── logistics.py       # 查询物流轨迹
│   │   │   ├── refund.py          # 申请退款
│   │   │   ├── knowledge.py       # search_knowledge：RAG 政策/FAQ 检索
│   │   │   ├── memory_tool.py     # recall_user_memory：查询用户记忆
│   │   │   └── skill_tool.py      # load_skill：按需加载技能指令
│   │   └── rag/                   # RAG 模块
│   │       ├── chunker.py         # Markdown → Chunk（按二级标题切分）
│   │       ├── embedder.py        # OpenAI Embeddings 封装
│   │       ├── retriever.py       # KnowledgeRetriever：query → 向量检索
│   │       ├── backends/          # 向量后端（可切换）
│   │       │   ├── base.py        # VectorBackend 抽象接口
│   │       │   ├── numpy_backend.py   # 手写余弦 + JSON（教学透明，零依赖）
│   │       │   └── chroma_backend.py  # Chroma 嵌入式向量数据库（生产代表）
│   │       └── knowledge/         # 知识库源文档（markdown，RAG 数据源）
│   │           ├── 退换货政策.md
│   │           ├── 配送说明.md
│   │           ├── 会员权益.md
│   │           └── 常见问题FAQ.md
│   ├── mcp_client/                # MCP Client（同步封装）
│   │   ├── client.py              # MCPClient：后台线程管理异步连接
│   │   └── converter.py           # MCP Tool schema → OpenAI function calling 格式
│   ├── evaluation/                # Agent 评估体系（第9期）
│   │   ├── __init__.py            # 导出 EvalCase / Sandbox / Evaluator / RunTrace 等
│   │   ├── dataset.py             # EvalCase 数据结构 + load_dataset
│   │   ├── trace.py               # RunTrace：沙箱采集的过程+结果载体
│   │   ├── sandbox.py             # Sandbox：隔离环境 + 共享 client 插桩 + 采集
│   │   ├── metrics.py             # 过程/结果双层指标（代码规则 + LLM judge）
│   │   ├── evaluator.py           # Evaluator：跑用例 → 双层评分 → 聚合报告
│   │   └── cases.json             # 黄金测试集（~10 条，引用 mock 数据）
│   ├── multi_agent/               # Multi-Agent 协作（第6期）
│   │   ├── router.py              # 意图路由器（LLM 分类 → 子 Agent）
│   │   ├── agents.py              # SubAgent 子 Agent 类 + 配置
│   │   └── orchestrator.py        # 编排器：路由 → 执行 → 结构化提取（集成 MemoryManager + SkillManager）
│   ├── scripts/
│   │   ├── build_kb_index.py      # 离线构建知识库索引（--backend numpy/chroma）
│   │   └── run_eval.py            # 离线运行评估（--mode single/multi · --judge/--no-judge · --output）
│   └── sessions/                  # 运行时生成，已 .gitignore
│       ├── session.json           # 当前会话快照
│       ├── kb_index.json          # NumpyBackend 索引
│       ├── chroma/                # ChromaBackend 持久化目录
│       └── memory/                # 长期记忆存储（按 user_id 分文件）
│           └── {user_id}.json
│
├── mcp_server/                    # MCP Server（独立微服务）
│   └── server.py                  # FastMCP + Streamable HTTP，暴露电商工具
│
└── tests/                         # 全部测试
    ├── test_agent.py              # 结构化输出 + 多轮 + reset
    ├── test_conversation_management.py  # 多轮对话管理
    ├── test_react_agent.py        # ReAct Agent + Function Calling
    ├── test_mcp.py                # MCP 集成
    ├── test_rag.py                # RAG 知识库检索
    ├── test_multi_agent.py        # Multi-Agent 协作
    ├── test_memory.py             # Memory 短期记忆 & 长期记忆
    ├── test_skills.py             # Skill 可复用能力模块
    └── test_evaluation.py         # Agent 评估体系（沙箱 + 双层测评）
```

### 更新日志

| 期数 | 主题 | Tag | 日期 |
|------|------|-----|------|
| 第 1 期 | 项目框架 + 纯 Prompt 客服 + 结构化输出 | v1-prompt-and-structured-output | 2025-04-14 |
| 第 2 期 | 多轮对话管理：Summary 压缩 + JSON 持久化 | v2-conversation-management | 2026-04-18 |
| 第 3 期 | ReAct Agent + 工具调用 (Function Calling) | v3-react-and-function-calling | 2026-04-27 |
| 第 4 期 | MCP 集成 (Streamable HTTP) | v4-mcp-integration | 2026-05-01 |
| 第 5 期 | RAG 检索增强生成（FAQ + 政策知识库） | v5-rag | 2026-05-13 |
| 第 6 期 | Multi-Agent 协作（客服路由 + 售前/售后/投诉分流） | v7-multi-agent | 2026-05-17 |
| 第 7 期 | Memory：短期记忆 & 长期记忆 | v8-memory | 2026-05-23 |
| 第 8 期 | Skill：可复用能力模块（基于 Agent Skills 开放标准） | v9-skills | 2026-05-31 |
| 第 9 期 | Agent 评估体系（沙箱重跑测试集 + 过程/结果双层指标 + LLM judge） | v10-evaluation | 2026-06-06 |

> 每期更新后，这里会同步更新架构图和更新日志。
