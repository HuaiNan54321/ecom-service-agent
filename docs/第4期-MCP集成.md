上期把工具写死在代码里，查订单、查物流这些都是本地函数直接调。能跑，但真实系统中工具散落在不同微服务里，不可能全塞到 Agent 代码中

这期用 MCP 把工具变成独立服务



## 为什么需要 MCP

MCP（Model Context Protocol）是工具调用的标准协议，可以理解成"Agent 世界的 USB 接口"

上期的做法是手写工具 schema、手写分发逻辑，工具函数也在同一个项目里。但真实业务中，订单服务、物流服务、退款服务是不同团队维护的不同服务

MCP 把工具注册和调用标准化了。工具方按协议暴露接口，Agent 连上去自动发现有哪些工具、参数是什么，不用提前写死

跟上期 Function Calling 的区别：Function Calling 解决"模型怎么知道该调哪个工具"，MCP 解决"工具从哪来、怎么跨服务调"



## 怎么接的

MCP Server 独立进程启动，用 Streamable HTTP 监听端口，四个电商工具注册在上面

Agent 侧加了 ToolManager，启动时 HTTP 连 MCP Server，自动发现工具，把 MCP schema 转成 OpenAI 格式塞给模型。模型决定调工具后，ToolManager 转发给 MCP Server 执行

ReAct 循环本身只改了两行——工具列表和调用入口换成 ToolManager 的统一接口

为什么选 Streamable HTTP 不选 stdio？stdio 最简单但工具作为子进程跑，真实场景工具是独立部署的。HTTP 更贴近实际，而且天然支持多个 Agent 同时连一个 Server



## 下期预告

下期做 RAG，让 Agent 能检索商品库、FAQ、退换货政策，不再只靠工具返回的数据回答问题

关注我，一起做完写进简历
