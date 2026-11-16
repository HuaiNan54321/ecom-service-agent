# 配套代码运行说明

这些脚本配合《大模型与Agent原理图解：基础、实践与进阶》，按知识点演示机制。默认使用原创合成数据或明确标记的预设响应，不需要启动完整电商工程。

## 先确定 Python 与目录

使用 Python 3.11 或更高版本。先创建并激活独立示例环境；本文的 `python` 指向该环境。Windows 可用 `py -3.11 -m venv .venv-examples` 创建，再运行 `.venv-examples\Scripts\Activate.ps1`；激活后使用 `python`，避免显式版本启动器绕过当前环境。macOS / Linux 可使用：

```bash
python3.11 -m venv .venv-examples
source .venv-examples/bin/activate
python --version
```

从 `ecom-service-agent` 仓库根目录运行命令；该目录下应同时能看到 `main.py`、`app/` 和 `examples/`：

```bash
python -m examples.ch09.demo
python -m unittest examples.common.test_common -v
```

`-m` 让 Python 按模块路径找到同一份公共代码，点号对应目录层级。不要切到 `ch09` 目录里运行 `python demo.py`，否则可能找不到 `examples` 包。离线公共核心只依赖 Python 标准库，不需要安装 SDK。

## 两种运行模式

| 模式 | 输入与输出性质 | 可以验证什么 |
| --- | --- | --- |
| 默认离线 | 合成订单、手写预设响应、小矩阵、固定数据 | 数据流、状态变化、程序校验、错误处理 |
| 显式 `--live` | 发往读者自己配置服务的真实请求 | 该服务、模型与配置在本次输入上的实际表现 |

离线响应中的 `_meta.mode` 为 `offline`，`usage` 为 `None`。它不是一次真实模型运行，也不产生可用于估算真实模型费用的 token 记录。真实调用中的 `_meta.mode` 为 `live`，`usage` 保留服务实际返回的数据；服务没有给出用量时，不自行补造。

只有章节明确提供 `--live` 时才能使用该选项。运行真实调用前，配置三个环境变量：

```bash
export AGENTBOOK_BASE_URL='https://服务商提供的API根地址/v1'
export AGENTBOOK_MODEL='服务商实际提供的模型标识'
export AGENTBOOK_API_KEY='读者自己的密钥'
```

这些值是需要自行替换的占位说明，不能原样连接服务。不要把真实密钥写入教材脚本、提交记录或截图。Windows PowerShell 使用 `$env:AGENTBOOK_MODEL='...'` 等形式设置变量。

客户端对配置的根地址追加 `/chat/completions`；不要把这个后缀重复写入根地址。它沿用原工程使用的 Chat Completions 兼容调用方式，但不代表各家服务支持完全相同的字段。比如工具、结构化输出、`max_completion_tokens` 和流式用量，需要按实际服务支持情况核对。不要把 Responses API 的事件结构直接当作这里的响应结构。

## 与主应用的对应关系

`examples/` 是同一开源仓库内的独立原理实验，帮助观察模型请求、状态变更和评测机制；`app/` 是已有电商 Agent 实现。默认实验无需安装仓库根 `requirements.txt`，也不会自动读取 `.env`。`main.py` 则使用 `app/config/settings.py` 自动加载 `.env` 中的 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`MODEL_NAME` 等配置，运行对话、构建真实向量索引或主系统评测可能调用模型并产生费用；主系统并不以 `--live` 作为联网开关。

| 知识点 | 主系统源码 | 独立实验的边界 |
| --- | --- | --- |
| 工具与退款 | `app/agent/tools/order.py`、`refund.py`、`registry.py` | 主系统使用 `ORD-*` 数据；`apply_refund` 返回模拟说明，没有实验中的主体隔离、幂等记录或退款状态写入。 |
| RAG | `app/agent/rag/chunker.py`、`backends/numpy_backend.py`、`retriever.py` | 第 13–14 章默认词袋和固定政策，用来拆解检索过程；真实 Embedding 是显式可选入口。 |
| Memory | `app/agent/memory/` | 主系统长期记忆使用 JSON；第 15 章 SQLite、版本校验和 TTL 是独立机制实验。 |
| Skills | `app/agent/skills/loader.py` 与 `definitions/` | 第 16 章使用自己的两份短 Skill，方便观察按需加载与长度变化。 |
| 评测 | `app/evaluation/`、`app/scripts/run_eval.py` | 主系统 `Sandbox` 是运行真实 Agent 并收集轨迹的插桩器；`examples.common.Sandbox` 是确定性合成状态环境，两者不能互换。`run_eval --no-judge` 仍可能调用 Agent 模型。 |
| MCP | `mcp_server/server.py`、`app/mcp_client/` | 主系统 MCP v1 使用 HTTP；第 9 章 MCP v2.3 实验使用独立环境和本机 stdio 子进程。 |
| 多 Agent 与优化 | `app/multi_agent/`、`app/agent/strategies/` | 主系统按路由选子 Agent；实验并行汇总、自进化审核和 `active.txt` 不会自动接入 `main.py`。 |

`AGENTBOOK_*` 只属于示例的显式真实调用，不会自动继承主应用的 `.env`。下面的 `Sandbox` 始终指 `examples.common.Sandbox`，所有订单与用户均为独立实验数据。

## 公共业务环境

```python
from examples.common import Sandbox, seed_state

box = Sandbox()
result = box.query_order("U1001", "A1001")
```

| 方法 | 返回与用途 |
| --- | --- |
| `query_order(user_id, order_id)` | `{success: True, order: {...}}` |
| `query_logistics(user_id, order_id)` | `{success: True, logistics: {...}}`；参数是订单号 |
| `request_refund(user_id, order_id, reason, *, request_id, confirmed=False, amount_cents=None)` | 写入申请、修改订单状态并记录幂等结果；成功含 `refund`、`replayed` |
| `query_refund(user_id, order_id)` | 根据订单查询真正保存的申请；不存在时返回 `REFUND_NOT_FOUND` |
| `snapshot()` / `Sandbox.from_snapshot(state)` | 深复制并恢复业务状态及幂等记录 |
| `reset()` | 恢复默认种子，并清除失败注入 |
| `inject_failure(operation, when="before")` | 下一次指定操作抛出一次 `TimeoutError`；`after_commit` 仅适用于退款 |

失败统一为 `{"success": False, "error": {"code": "...", "message": "中文说明"}}`。不要从中文文案猜测错误类型。

默认种子如下，金额单位为整数分：

| 用户 | 订单 | 初始状态 | 金额 | `eligible` |
| --- | --- | --- | --- | --- |
| U1001 | A1001 | shipped | 12900 | True |
| U1001 | A1002 | pending | 5900 | True |
| U1002 | A1003 | delivered | 9900 | True |
| U1001 | A1004 | delivered | 2990 | False |

`eligible` 是本教材预设的业务资格字段，不是对现实售后法律或商家规则的判断。新申请要求资格为真、状态为 `pending/shipped/delivered`、金额为正整数分且不超过实付金额、可信调用方已取得明确确认。`bool` 不作为合法金额。

用户标识由外层登录上下文或固定教学身份传入；不能让模型任意填写身份。`confirmed` 也必须来自外层确认流程，不能因为模型写了 `true` 就视为用户已确认。

写成功后，订单变为 `refund_pending`，`refunds[refund_id]` 保存 `refund_id/user_id/order_id/reason/amount_cents/request_id/status`，申请状态为 `requested`。这只表示模拟系统保存了申请，不表示审核通过或真实到账。

同一用户、同一 `request_id`、同一业务参数重复提交，返回已有申请并标记 `replayed=True`；若改了订单、原因或金额，返回 `IDEMPOTENCY_CONFLICT`。同一订单换一个请求编号重新提交，返回 `REFUND_ALREADY_EXISTS`。未知订单和越权订单使用相同的 `ORDER_NOT_ACCESSIBLE`，不泄露其他用户订单是否存在。

快照字段为 `version/users/orders/logistics/policies/refunds/requests/next_refund_id`。评测可以先用 `seed_state()` 获得副本，修改合法夹具字段，再用 `from_snapshot()` 构造独立环境。快照是可信程序数据，不接收模型生成的任意状态。失败注入不会保存进快照。这个小环境没有生产数据库的并发事务或真实身份认证。

## 公共模型客户端

```python
from examples.common.llm import chat_completion, ModelAPIError

# offline_sample 是本章自己准备的完整响应字典；真实调用时不传预设响应。
result = chat_completion(
    messages,
    live=args.live,
    offline_response=None if args.live else offline_sample,
    max_completion_tokens=256,
    timeout=30.0,
)
text = result["choices"][0]["message"]["content"]
```

以上展示调用位置，`messages/args/offline_sample` 在各章完整脚本中定义。工具调用时 `content` 可能为 `None`，应检查 `tool_calls`。`live=True` 与 `offline_response` 同时出现会被拒绝，避免把预设响应混进真实调用。

`chat_completion` 可选参数还有 `tools`、`tool_choice`、`response_format`、`temperature`。温度默认不传；输出上限默认 256，教材客户端接受 1–4096。输出上限不是总费用上限，输入和多次调用仍会计费；跨步骤预算由章节脚本控制。超时约束针对网络阻塞，不构成整个多步任务的总时限。客户端不自动重试。

`stream_completion` 接受相同请求参数，把离线样本参数换成 `offline_chunks`，逐个返回原始 JSON 片段。读取文本前检查 `choices` 是否为空：用量片段可能只有 `usage`。收到 `[DONE]` 才正常结束；连接提前关闭会报 `INCOMPLETE_STREAM`。流被中断时也可能拿不到完整用量，不能把已看到的前半段误称为完整回答。

`ModelAPIError` 提供 `code/status/retryable`。常见 `code` 为 `CONFIG`、`INPUT`、`HTTP_401`、`HTTP_429`、`TIMEOUT`、`NETWORK`、`PROTOCOL`、`INCOMPLETE_STREAM`。`retryable=True` 只表示可能值得重试，不能保证请求未到达服务，也不代替预算与幂等判断。错误消息不回显密钥或服务端响应原文。远程服务必须使用 HTTPS；HTTP 只允许本机回环地址做测试。

## 依赖与验证范围

公共业务环境和模型客户端没有第三方运行依赖。各章的 tokenizer、MCP 等可选依赖按对应章节说明安装，不把全书依赖一次性强加给每位读者。

公共核心已在 Python 3.12.14 下用本地确定性用例和回环 HTTP 服务验证。没有向真实模型服务发出收费请求，没有验证任意供应商/模型的全部兼容性；真实模型内容质量、费用和线上表现不能由这些测试推断。

## 全书入口索引

从 ecom-service-agent 仓库根目录运行表中命令。模块名沿用仓库已有目录，例如第 32 章运行 `examples.ch24.demo`。第 9 章的 MCP 实验需先安装该节的可选依赖。

| 教材章节 | 内容 | 仓库运行入口 |
| --- | --- | --- |
| 01 | 大模型是什么 | `python -m examples.ch01.demo` |
| 02 | 从文字到 Token：模型怎样生成一句话 | `python -m examples.ch02.demo` |
| 03 | 向量、Attention 与 Transformer 的直觉 | `python -m examples.ch03.demo` |
| 04 | 模型如何学会能力：训练、后训练与推理 | `python -m examples.ch04.demo` |
| 05 | 第一次模型调用：看懂请求与响应 | `python -m examples.ch05.demo` |
| 06 | Prompt 怎样写，为什么有效又为什么失效 | `python -m examples.ch06.demo` |
| 07 | 结构化输出：从一段话到程序可使用的数据 | `python -m examples.ch07.demo` |
| 08 | 多轮对话：历史、上下文与程序状态 | `python -m examples.ch08.demo` |
| 09 | Function Calling 与 MCP：模型怎样请求工具，应用怎样连接服务 | 本地工具：`python -m examples.ch09.demo`。MCP（9.12）：`python -m examples.ch21.demo`。 |
| 10 | Workflow、ReAct 与规划：谁决定下一步 | `python -m examples.ch10.demo` |
| 11 | 工具失败怎么办：可靠执行的基本规则 | `python -m examples.ch11.demo` |
| 12 | Context Engineering：每次给模型看什么 | `python -m examples.ch12.demo` |
| 13 | RAG 从头理解：先找依据，再回答 | `python -m examples.ch13.demo` |
| 14 | 检索为什么会错：从相似度到检索改进 | `python -m examples.ch14.demo` |
| 15 | Memory：哪些信息值得跨会话保留 | `python -m examples.ch15.demo` |
| 16 | Agent Skills：把操作方法按需交给模型 | `python -m examples.ch16.demo` |
| 17 | Agent 到底做对了吗：定义任务和评测集 | `python -m examples.ch17.demo` |
| 18 | 怎样评分：答案、工具轨迹与最终状态 | `python -m examples.ch18.demo` |
| 19 | 模型裁判可信吗：校准、用户模拟与重复试验 | `python -m examples.ch19.demo` |
| 20 | 从评分到改进：回归、对照、成本与可观测性 | `python -m examples.ch20.demo` |
| 21 | 从一次退货咨询看懂 Agent Harness | 工具调用：`python -m examples.ch09.demo`。有界循环：`python -m examples.ch10.demo`。 |
| 22 | 长任务如何恢复：让下一次运行接得上 | `python -m examples.ch22.demo` |
| 23 | 沙箱、审批与安全护栏 | `python -m examples.ch23.demo` |
| 24 | 可观测：沿一次退款的 Trace 找到故障 | 在仓库根目录运行 `python`，执行 24.4 的代码，用 `examples.ch17.dataset.load_tasks` 和 `examples.ch20.runner.run_task` 比较 dev_10 的两种策略。跨进程恢复：`python -m examples.ch22.demo`。 |
| 25 | 反思、重试与自进化：到底改变了什么 | `python -m examples.ch25.demo` |
| 26 | 从失败轨迹到经验和 Skills | `python -m examples.ch26.demo` |
| 27 | 自动优化 Prompt：理解 GEPA 的核心思想 | `python -m examples.ch27.demo` |
| 28 | 怎样检验自进化是否有效：验收、泛化与回滚 | `python -m examples.ch28.demo` |
| 29 | 什么时候需要训练：SFT、LoRA、DPO 与 Agentic RL | `python -m examples.ch29.demo` |
| 30 | 多模态、浏览器与计算机操作 Agent | `python -m examples.ch30.demo` |
| 31 | 原生 API、SDK 与框架：怎样做技术选择 | `python -m examples.ch31.demo` |
| 32 | 多 Agent 协作：路由、委派与 A2A | `python -m examples.ch24.demo` |
| 33 | 把知识用到新场景：技术地图与源码阅读 | `python -m examples.ch32.demo` |
| 附录 A | Python 与文件操作 | `python -m examples.appendix_a.demo` |
| 附录 B | 点积、矩阵与概率 | `python -m examples.appendix_b.demo` |
| 附录 C | 环境诊断，不打印密钥 | `python -m examples.appendix_c.diagnose` |
| 附录 D | 术语与版本速查 | 阅读材料，无独立脚本 |

第 5 章可加 `--stream` 观察离线片段。第 13 章另有 `python -m examples.ch13.embeddings`，默认只说明配置，不联网；真实向量入口使用 `--live`，额外需要 `AGENTBOOK_EMBEDDING_MODEL`。

## 按章安装可选依赖

不要将下面三项合并成全书必装依赖。先创建、激活对应的虚拟环境，再在该环境中执行安装与运行命令。主系统固定 MCP `<2`，第 9 章的 MCP 实验固定 `2.3.0`，必须使用不同虚拟环境，不要在主系统环境升级 MCP。Windows 激活后使用 `python`，避免 `py -3.11` 绕过当前环境。

| 章节 | 本轮固定版本 | 安装与实际用途 |
| --- | --- | --- |
| 02 | `tokenizers==0.22.2` | `python -m pip install -r examples/ch02/requirements.txt`；只用于真实分词器，采样 demo 无须它。 |
| 09（MCP） | `mcp==2.3.0` | `python -m pip install -r examples/ch21/requirements.txt`；连接本机 MCP 子进程，不调用模型。 |
| 31 | `langgraph==1.2.21` | `python -m pip install -r examples/ch31/requirements-framework.txt`；仅加 `--langgraph` 时需要。 |

```bash
python -m examples.ch02.tokenizer_demo --download
python -m examples.ch21.demo
python -m examples.ch31.demo --langgraph
```

分词器的 `--download` 会联网下载公开词表，不调用语言模型。代码固定 GPT-2 仓库 revision `607a30d783dfa663caf39e06633721c8d4cfcd7e`；已有对应 `tokenizer.json` 时改用 `--file /你的路径/tokenizer.json`。不要把词表中的 Token ID 当作其他模型也适用的编号。

MCP 在本轮本地连接中协商到协议版本 `2026-07-28`。SDK 版本与协议版本是两个不同的记录；这里报告本轮组合，不宣称任意旧客户端都兼容。LangGraph 可选分支执行同一组确定性节点，没有调用模型。

## 保存报告、采纳与回滚

下列目录需自行选择；第 28 章生成报告时要求空目录，避免覆盖既有记录。示例目录仅用于本地教学实验。

```bash
python -m examples.ch20.demo --output runs/ch20-report.json
python -m examples.ch27.demo --budget 2 --out runs/ch27
python -m examples.ch28.demo --out runs/ch28
```

第 28 章生成报告后尚未采纳。检查该目录中的冻结候选与 `release.json`，决定采纳时运行下面的命令；它读取同一目录中已经评测的候选，不重新搜索。需要恢复时再运行回滚命令。

```bash
python -m examples.ch28.demo --activate runs/ch28
python -m examples.ch28.demo --rollback runs/ch28
```

第 22 章默认入口已经包含“子进程模拟中断→恢复”的完整演示；中间子进程的约定退出码不是整段演示失败。第 9 章的 MCP 实验故意调用未知工具时会出现预期错误日志，最终入口退出码与断言结果才是验证结论。

生成的 `runs/` 目录只保存本地实验报告与策略文件，已加入 Git 忽略规则。第 28 章 `active.txt` 不被主应用读取；采纳与回滚只改变实验文件。

## 运行示例测试

从仓库根目录运行；这些测试使用合成状态、函数替身或本机 HTTP 桩，不请求付费模型：

```bash
python -m unittest discover -s examples -t . -p 'test*.py' -v
```

这条命令只测试 `examples/`，不等于执行主系统 `tests/` 的真实模型集成测试。可选 tokenizer、MCP 与 LangGraph 仍需使用各自环境，按上面的入口单独验证。
