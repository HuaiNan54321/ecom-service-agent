"""第 5 章：观察请求、响应与流式片段；默认使用明确标记的离线样本。"""

import argparse
import json

from examples.common.llm import (
    ModelAPIError,
    chat_completion,
    stream_completion,
)


MESSAGES = [
    {"role": "system", "content": "根据给定记录回答，不补充未提供的信息。"},
    {"role": "user", "content": "教学记录：A1001 已发货。请用一句话说明状态。"},
]


def fixed_response(text: str) -> dict:
    """构造人工编写的响应样本，供后续章节演示程序流程。"""
    return {
        "id": "offline-example",
        "object": "chat.completion",
        "model": "offline-fixture",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": None,
    }


def read_answer(response: dict) -> str:
    """只接收完整的普通文本回答，截断、拒绝和空内容分别报错。"""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("响应缺少候选回答")
    choice = choices[0]
    if choice.get("finish_reason") != "stop":
        raise ValueError("回答未正常结束，暂不当作完整结果")
    message = choice.get("message", {})
    if message.get("refusal"):
        raise ValueError("模型拒绝了该请求")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("没有可显示的文本回答")
    return content


def main() -> None:
    """显式传入 --live 才向已配置的模型服务发送请求。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="显式调用已配置模型")
    parser.add_argument("--stream", action="store_true", help="按流式片段接收")
    args = parser.parse_args()
    print("运行方式：" + ("真实模型调用" if args.live else "离线预设样本，未调用模型"))
    print("messages：")
    print(json.dumps(MESSAGES, ensure_ascii=False, indent=2))
    try:
        if args.stream:
            pieces = []
            usage = None
            reason = None
            for chunk in stream_completion(MESSAGES, live=args.live):
                if chunk.get("usage") is not None:
                    usage = chunk["usage"]
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta", {})
                    if delta.get("refusal"):
                        raise ValueError("模型拒绝了该请求")
                    piece = delta.get("content")
                    if piece:
                        pieces.append(piece)
                        print(piece, end="", flush=True)
                    if choice.get("finish_reason") is not None:
                        reason = choice["finish_reason"]
            print("\n结束原因：", reason)
            print("服务端用量：", usage)
            if reason != "stop" or not "".join(pieces).strip():
                raise ValueError("流已经结束，但没有得到完整的文本回答")
        else:
            response = chat_completion(
                MESSAGES,
                live=args.live,
                offline_response=None if args.live else fixed_response("订单 A1001 已发货。"),
            )
            print("response：")
            print(json.dumps(response, ensure_ascii=False, indent=2))
            print("提取的回答：", read_answer(response))
    except (ModelAPIError, ValueError) as error:
        parser.exit(1, f"调用未完成：{error}\n")


if __name__ == "__main__":
    assert read_answer(fixed_response("已发货")) == "已发货"
    truncated = fixed_response("尚未写完")
    truncated["choices"][0]["finish_reason"] = "length"
    try:
        read_answer(truncated)
    except ValueError:
        pass
    else:
        raise AssertionError("截断回答不应通过完整性检查")
    main()
