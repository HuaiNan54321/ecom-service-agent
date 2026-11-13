"""第 6 章：比较提示词与固定反例；离线样本不是模型实测结果。"""

import argparse
import json

from examples.ch05.demo import fixed_response, read_answer
from examples.common.llm import ModelAPIError, chat_completion


QUESTION = "订单 A1001 什么时候到？"
RECORD = "订单号：A1001；状态：已发货；预计送达时间：未提供。"
VARIANTS = [
    ("含糊指令", "你是专业客服，请热情回答。", "预计明天送达，请耐心等待。"),
    (
        "明确依据",
        "只使用记录回答。未提供送达时间时明确说明未知，不猜测日期。",
        "订单 A1001 已发货，但记录未提供预计送达时间。",
    ),
    (
        "加入边界示例",
        "只使用记录回答，不把示例当事实。示例：记录无送达时间时，"
        "回答‘暂时无法确认送达时间’。先说明已知，再说明缺失。",
        "订单 A1001 已发货，目前无法确认送达时间。",
    ),
]


def unsupported_date(text: str) -> bool:
    """仅检查本例中的几个越界词，不能替代完整事实评测。"""
    return any(word in text for word in ("明天", "后天", "今晚", "24小时"))


def main() -> None:
    """真实模式最多调用三次；人工样本与真实响应使用相同观察表。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="显式发送三次模型请求")
    args = parser.parse_args()
    print("性质：" + ("真实调用，结果随模型而变" if args.live else "人工预设对照，不代表模型表现"))
    for name, instruction, sample in VARIANTS:
        messages = [
            {"role": "system", "content": instruction},
            {"role": "user", "content": f"问题：{QUESTION}\n<record>{RECORD}</record>"},
        ]
        try:
            response = chat_completion(
                messages, live=args.live, max_completion_tokens=256,
                offline_response=None if args.live else fixed_response(sample),
            )
            answer = read_answer(response)
        except (ModelAPIError, ValueError) as error:
            parser.exit(1, f"{name} 未完成：{error}\n")
        print(json.dumps({
            "版本": name,
            "回答": answer,
            "命中本例无依据日期词": unsupported_date(answer),
            "用量": response.get("usage"),
        }, ensure_ascii=False))


if __name__ == "__main__":
    assert unsupported_date("预计明天送达")
    assert not unsupported_date("记录没有预计送达时间")
    main()
