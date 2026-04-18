from typing import Optional

from openai import OpenAI

from prompts.summarizer import SUMMARY_PROMPT


def summarize(
    client: OpenAI,
    model: str,
    old_messages: list[dict],
    prev_summary: Optional[str],
) -> str:
    """把老对话（可选地带上上一次 summary）压缩成新的 summary 文本。

    注意：使用 chat.completions.create 而不是 beta.chat.completions.parse，
    避免被 CustomerServiceResponse 的结构化 schema 约束。
    """
    parts: list[str] = []
    if prev_summary:
        parts.append(f"【此前摘要】\n{prev_summary}")

    transcript_lines = []
    for msg in old_messages:
        role = msg.get("role")
        content = msg.get("content") or ""
        if role == "user":
            transcript_lines.append(f"用户：{content}")
        elif role == "assistant":
            transcript_lines.append(f"客服：{content}")
    parts.append("【待压缩对话】\n" + "\n".join(transcript_lines))

    user_content = "\n\n".join(parts)

    response = client.chat.completions.create(
        model=model,
        temperature=0.3,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    return response.choices[0].message.content.strip()
