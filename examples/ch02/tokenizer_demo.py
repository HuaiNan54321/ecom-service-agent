"""观察 GPT-2 的真实分词结果；只加载词表，不加载或调用语言模型。"""

import argparse
from pathlib import Path


REVISION = "607a30d783dfa663caf39e06633721c8d4cfcd7e"


def main():
    """从指定本地文件读取，或经显式选项下载固定版本词表。"""
    parser = argparse.ArgumentParser(description="真实分词器演示，不调用模型 API")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=Path, help="已有 GPT-2 tokenizer.json 的路径")
    group.add_argument("--download", action="store_true", help="从公开模型仓库下载并缓存词表")
    args = parser.parse_args()
    try:
        from tokenizers import Tokenizer
    except ImportError as error:
        raise SystemExit("请先运行 python -m pip install -r examples/ch02/requirements.txt") from error
    try:
        if args.file:
            tokenizer = Tokenizer.from_file(str(args.file))
        else:
            tokenizer = Tokenizer.from_pretrained("openai-community/gpt2", revision=REVISION)
    except Exception as error:
        raise SystemExit("词表加载失败。检查文件路径或网络；可下载 tokenizer.json 后改用 --file。") from error
    for text in ("hello world", "订单A1001已发货。"):
        encoded = tokenizer.encode(text)
        restored = tokenizer.decode(encoded.ids)
        assert restored == text
        print("原文:", text)
        print("Token ID:", encoded.ids)
        print("词表片段:", encoded.tokens)
        print("Token 数:", len(encoded.ids))
        print("完整还原:", restored)
    print("GPT-2 使用字节级 BPE；词表片段中的特殊显示字符不等于原文乱码。")


if __name__ == "__main__":
    main()
