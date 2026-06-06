这期是高级篇的倒数第二期啦：Agent Skills。一起做完这一期，其实就已经得到一个很成熟的、包含所有主流技术栈的 Agent 系统了



1️⃣ 先聊聊概念：Skill 到底是什么

在我的眼里，Skill 很像 Agent 操作的 SOP：想象你有一个学习能力很强的员工，只要你能描述清楚任务（promp）和他能够使用的工具（tool），他就能自主决定如何使用这些工具来完成任务。但他也有一些缺点：

1、在特定的场景下通常有特定的 SOP 能够更好、更快地完成任务，而不需要 Agent 自己摸索

2、在特定的场景下你对 Agent 有特殊要求，但是你不能直接在 prompt 中枚举所有的特殊要求，否则上下文会爆炸💥

3、你需要可插拔式的提供一些新的能力（主要是执行脚本）给 Agent



Skill 就是解决上述问题的。Anthropic 搞了个 Agent Skills 开放标准，核心思路就是渐进式披露上下文：启动时只加载每个 Skill 的name和description（建议写得短一点，简明而要）。模型判断当前场景符合description，才会通过 load_skill把skill 的具体内容加载到上下文中



项目代码已开源，GitHub 🔍 HuaiNan54321/ecom-service-agent



📢 下期预告

下期做 Agent 评估体系（高级篇的最后一节），量化衡量 Agent 的效果



关注我，一起做完写进简历

           