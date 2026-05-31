from app.agent.chat import EcomAgent
from app.config.settings import settings
from app.schemas.response import IntentType

# 意图类型的中文映射
INTENT_LABELS = {
    IntentType.ORDER_QUERY: "订单查询",
    IntentType.RETURN_REQUEST: "退换货",
    IntentType.PRODUCT_CONSULT: "商品咨询",
    IntentType.COMPLAINT: "投诉",
    IntentType.AFTER_SALE: "售后服务",
    IntentType.PROMOTION: "优惠活动",
    IntentType.ACCOUNT: "账户问题",
    IntentType.GREETING: "打招呼",
    IntentType.OTHER: "其他",
}


def main():
    if settings.multi_agent_enabled:
        from app.multi_agent.orchestrator import MultiAgentOrchestrator
        agent = MultiAgentOrchestrator()
        mode = "Multi-Agent 协作模式"
    else:
        agent = EcomAgent()
        mode = "ReAct + MCP + RAG"

    print("=" * 50)
    print(f"  并夕夕 · 智能客服「小夕」({mode})")
    print("  支持工具调用 + 政策检索 + 用户记忆 + 技能编排")
    print("  输入 quit/exit 退出, reset 重置, memory 查看记忆, skills 查看技能")
    print("=" * 50)
    print()

    if agent.history_size > 0:
        print(f"💬 已恢复上次对话（{agent.history_size} 条历史）\n")

    while True:
        try:
            user_input = input("👤 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            agent.save()
            agent.close()
            print("\n再见，欢迎下次光临！")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit"):
            agent.save()
            agent.close()
            print("再见，欢迎下次光临！")
            break

        if user_input.lower() == "reset":
            agent.reset()
            print("对话已重置。\n")
            continue

        if user_input.lower() == "skills":
            if hasattr(agent, "skill_manager") and agent.skill_manager.enabled:
                catalog = agent.skill_manager.get_catalog()
                print(f"\n--- 已加载 {len(catalog)} 个技能 ---")
                for s in catalog:
                    print(f"  - {s['name']}：{s['description']}")
                print()
            else:
                print("技能系统未启用\n")
            continue

        if user_input.lower() == "memory":
            if hasattr(agent, "memory_manager") and agent.memory_manager.memory_enabled:
                stm = agent.memory_manager.stm
                ltm = agent.memory_manager.ltm
                print("\n--- 短期记忆（本次对话）---")
                if stm.facts:
                    for f in stm.facts:
                        print(f"  - {f}")
                else:
                    print("  （暂无）")
                print(f"\n--- 长期记忆（跨会话，用户: {ltm.user_id}）---")
                if ltm.facts:
                    for f in ltm.facts:
                        print(f"  - [{f.category}] {f.content}")
                else:
                    print("  （暂无）")
                if ltm.interaction_summaries:
                    print("\n--- 最近交互 ---")
                    for s in ltm.interaction_summaries[-3:]:
                        print(f"  - {s['summary']}")
                print()
            else:
                print("记忆功能未启用\n")
            continue

        try:
            response = agent.chat(user_input)

            # 打印客服回复
            print(f"\n🤖 小夕: {response.reply}")

            # 打印结构化元信息
            intent_label = INTENT_LABELS.get(response.intent, response.intent)
            print(
                f"   [意图: {intent_label} | "
                f"置信度: {response.confidence:.0%} | "
                f"转人工: {'是' if response.requires_human else '否'}]"
            )

            if response.follow_up_question:
                print(f"   [追问: {response.follow_up_question}]")

            print()

        except Exception as e:
            print(f"\n⚠️  出错了: {e}\n")


if __name__ == "__main__":
    main()
