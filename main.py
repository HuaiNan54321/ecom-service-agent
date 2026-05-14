from agent.chat import EcomAgent
from schemas.response import IntentType

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
    print("=" * 50)
    print("  并夕夕 · 智能客服「小夕」(ReAct + MCP + RAG)")
    print("  支持工具调用：查订单/商品/物流/退款 + 政策检索")
    print("  输入 quit 或 exit 退出，输入 reset 重置对话")
    print("=" * 50)
    print()

    agent = EcomAgent()

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
