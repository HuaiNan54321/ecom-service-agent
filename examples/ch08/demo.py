"""第 8 章：展示发给模型的历史和摘要；默认回答均为人工预设。"""

import argparse
import json

from examples.ch05.demo import fixed_response, read_answer
from examples.common.llm import ModelAPIError, chat_completion


SYSTEM = {"role": "system", "content": "根据提供的对话和记录回答；缺信息就说明。"}
HISTORY = [
    {"role": "user", "content": "请查订单 A1001。"},
    {"role": "assistant", "content": "教学查询结果：A1001 已发货，暂未提供送达时间。"},
]
CURRENT = {"role": "user", "content": "它什么时候到？"}
SUMMARY = "此前讨论订单 A1001；已查询到已发货；预计送达时间未知。"


def build_messages(mode: str) -> list[dict]:
    """三种请求保留的材料不同；摘要是人工整理，未调用摘要模型。"""
    if mode == "完整历史":
        return [dict(SYSTEM), *[dict(item) for item in HISTORY], dict(CURRENT)]
    if mode == "只留当前":
        return [dict(SYSTEM), dict(CURRENT)]
    if mode == "保留摘要":
        return [dict(SYSTEM), {"role": "user", "content": "历史摘要：" + SUMMARY}, dict(CURRENT)]
    raise ValueError("不支持的历史组织方式")


def main() -> None:
    """真实模式至多调用三次，固定回复只用于说明对话材料差异。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="显式运行三组真实请求")
    args = parser.parse_args()
    samples = {
        "完整历史": "A1001 已发货，但目前无法确认送达时间。",
        "只留当前": "请先提供要查询的订单号。",
        "保留摘要": "你说的是 A1001；已有记录没有预计送达时间。",
    }
    print("性质：" + ("真实模型调用" if args.live else "人工预设响应，不代表模型实测"))
    for mode, sample in samples.items():
        messages = build_messages(mode)
        print("\n方式：", mode)
        print(json.dumps(messages, ensure_ascii=False, indent=2))
        try:
            response = chat_completion(
                messages, live=args.live,
                offline_response=None if args.live else fixed_response(sample),
            )
            print("回答：", read_answer(response))
        except (ModelAPIError, ValueError) as error:
            parser.exit(1, f"本组未完成：{error}\n")
    business_state = {"A1001": {"refund_requested": False}}
    transcript = [{"role": "assistant", "content": "已申请退款"}]
    print("\n对话文本：", transcript[0]["content"])
    print("业务状态：", json.dumps(business_state, ensure_ascii=False))
    assert business_state["A1001"]["refund_requested"] is False


if __name__ == "__main__":
    assert len(build_messages("完整历史")) == 4
    assert len(build_messages("只留当前")) == 2
    assert "A1001" not in json.dumps(build_messages("只留当前"))
    assert "A1001" in json.dumps(build_messages("保留摘要"))
    main()
