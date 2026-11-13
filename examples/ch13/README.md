# 第13章：RAG 数据流

从 ecom-service-agent 仓库根目录运行，先确认 `python --version` 为 3.11 或以上；Windows 先用 `py -3.11 -m venv .venv-examples` 创建环境，激活后使用 `python`。

```bash
python -m examples.ch13.demo
python -m examples.ch13.embeddings
python -m unittest examples.ch13.test_demo
```

默认不联网。`demo` 使用手工词表的0/1向量和模板摘录，`embeddings` 默认只显示配置要求。固定输出中的排序不是语义模型测评。

可选真实生成：按公共运行说明配置 `AGENTBOOK_BASE_URL`、`AGENTBOOK_MODEL` 和 `AGENTBOOK_API_KEY`，然后运行 `python -m examples.ch13.demo --live`。此时检索仍是词袋，生成由真实聊天模型完成。

可选真实向量：配置兼容接口的 HTTPS 根地址 `AGENTBOOK_BASE_URL`、对应密钥 `AGENTBOOK_API_KEY` 和可调用的向量模型 `AGENTBOOK_EMBEDDING_MODEL`，然后运行 `python -m examples.ch13.embeddings --live`。脚本追加 `/embeddings`，发送问题和四段原创政策，输出实际排序、维度和用量。地域地址和模型名称以账号控制台为准，不使用聊天模型名称替代向量模型。

真实入口可能产生费用。本教材已验证离线流程、响应解析和模拟请求分支，未实际调用付费模型；没有固定真实排序或质量承诺。
