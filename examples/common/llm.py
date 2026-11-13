"""可观察的 Chat Completions 小客户端；默认返回教材预设数据，不联网。"""

from contextlib import contextmanager
from copy import deepcopy
from http.client import HTTPException
import json
import math
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ModelAPIError(RuntimeError):
    """保留可判定的错误类型，不把密钥、请求或服务器回显写入错误消息。"""

    def __init__(self, code: str, message: str, *, status=None, retryable=False):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = retryable


class _NoRedirect(HTTPRedirectHandler):
    """不自动跳转带有鉴权头的请求，避免把密钥转交给其他地址。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _payload(messages, tools, tool_choice, response_format, max_completion_tokens, temperature):
    if not isinstance(messages, list) or not messages:
        raise ModelAPIError("INPUT", "messages 必须是非空消息列表")
    roles = {"system", "developer", "user", "assistant", "tool"}
    if any(not isinstance(m, dict) or m.get("role") not in roles for m in messages):
        raise ModelAPIError("INPUT", "每条消息须包含有效的 role")
    if type(max_completion_tokens) is not int or not 1 <= max_completion_tokens <= 4096:
        raise ModelAPIError("INPUT", "教学客户端单次生成上限须在 1 至 4096 token 之间")
    if temperature is not None and (type(temperature) not in {int, float} or not 0 <= temperature <= 2):
        raise ModelAPIError("INPUT", "temperature 须为 0 至 2 的数值，或省略")
    payload = {"messages": deepcopy(messages), "max_completion_tokens": max_completion_tokens}
    for key, value in {"tools": tools, "tool_choice": tool_choice,
                       "response_format": response_format, "temperature": temperature}.items():
        if value is not None:
            payload[key] = deepcopy(value)
    try:
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise ModelAPIError("INPUT", "请求字段必须可编码为标准 JSON") from None
    return payload


@contextmanager
def _connection(payload: dict, timeout: float):
    """明确指定服务、模型和密钥；默认没有服务商或模型的隐式选择。"""
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0:
        raise ModelAPIError("INPUT", "timeout 必须是有限正数秒")
    base_url = os.environ.get("AGENTBOOK_BASE_URL", "").strip().rstrip("/")
    model = os.environ.get("AGENTBOOK_MODEL", "").strip()
    key = os.environ.get("AGENTBOOK_API_KEY", "").strip()
    if not base_url or not model or not key:
        raise ModelAPIError("CONFIG", "真实调用需要 AGENTBOOK_BASE_URL、AGENTBOOK_MODEL、AGENTBOOK_API_KEY")
    try:
        url = urlsplit(base_url)
        valid_transport = url.scheme == "https" or (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"})
        if not valid_transport or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError()
        if any(c in base_url + key + model for c in "\r\n"):
            raise ValueError()
        payload = {**payload, "model": model}
        request = Request(base_url + "/chat/completions", method="POST",
                          data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                          headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    except ValueError:
        raise ModelAPIError("CONFIG", "服务地址须为不含凭据、查询串的 HTTPS 根地址；本地测试允许 HTTP 回环地址") from None
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            yield response
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise ModelAPIError(f"HTTP_{status}", f"服务返回 HTTP {status}；请检查鉴权、额度或接口支持情况",
                            status=status, retryable=status in {408, 429} or status >= 500) from None
    except TimeoutError:
        raise ModelAPIError("TIMEOUT", "模型服务未在超时限制内响应；本客户端没有自动重试", retryable=True) from None
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise ModelAPIError("TIMEOUT", "连接模型服务超时；本客户端没有自动重试", retryable=True) from None
        raise ModelAPIError("NETWORK", "无法连接模型服务；请检查网络和服务地址", retryable=True) from None
    except (OSError, HTTPException):
        raise ModelAPIError("NETWORK", "读取模型服务响应时连接中断", retryable=True) from None


def _decode(data):
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        raise ModelAPIError("PROTOCOL", "服务响应不是有效的 JSON") from None
    if not isinstance(value, dict) or "error" in value:
        raise ModelAPIError("PROTOCOL", "响应不是有效的成功对象；检查接口兼容性")
    return value


def _validate_chunk(chunk):
    """拒绝畸形成功片段，同时允许只有用量的空 choices 列表。"""
    choices = chunk.get("choices")
    if not isinstance(choices, list):
        raise ModelAPIError("PROTOCOL", "流式响应的 choices 必须是列表")
    for choice in choices:
        if not isinstance(choice, dict) or not isinstance(choice.get("delta"), dict):
            raise ModelAPIError("PROTOCOL", "流式响应缺少有效的 delta 对象")
        for field in ("content", "refusal"):
            value = choice["delta"].get(field)
            if value is not None and not isinstance(value, str):
                raise ModelAPIError("PROTOCOL", "流式文本或拒绝说明须为字符串或空值")


def chat_completion(messages, *, live=False, tools=None, tool_choice=None,
                    response_format=None, max_completion_tokens=256,
                    temperature=None, timeout=30.0, offline_response=None) -> dict:
    """返回原始响应形状；offline_response 是作者提供的预设样本，不是模型推断。"""
    payload = _payload(messages, tools, tool_choice, response_format, max_completion_tokens, temperature)
    if type(live) is not bool:
        raise ModelAPIError("INPUT", "live 必须是布尔值")
    start = time.perf_counter()
    if live:
        if offline_response is not None:
            raise ModelAPIError("INPUT", "真实调用不能同时提供离线响应")
        with _connection(payload, timeout) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ModelAPIError("PROTOCOL", "响应超出教学客户端的大小限制")
        result = _decode(raw)
    else:
        result = deepcopy(offline_response) if offline_response is not None else {
            "id": "offline-example", "object": "chat.completion", "model": "offline-scripted",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "这是教材预设响应，用来观察请求与返回结构；没有调用真实模型。"}, "finish_reason": "stop"}],
        }
        if not isinstance(result, dict):
            raise ModelAPIError("INPUT", "离线响应必须是完整的响应字典")
        result["usage"] = None
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict) or not isinstance(choices[0].get("message"), dict):
        raise ModelAPIError("PROTOCOL", "响应缺少 choices[0].message")
    result["_meta"] = {"mode": "live" if live else "offline", "elapsed_ms": round((time.perf_counter() - start) * 1000, 3)}
    return result


def stream_completion(messages, *, live=False, tools=None, tool_choice=None,
                      response_format=None, max_completion_tokens=256,
                      temperature=None, timeout=30.0, offline_chunks=None):
    """逐个返回 SSE 中的 JSON 对象，包含结束标记前可能出现的用量块。"""
    payload = _payload(messages, tools, tool_choice, response_format, max_completion_tokens, temperature)
    if type(live) is not bool:
        raise ModelAPIError("INPUT", "live 必须是布尔值")
    if not live:
        chunks = deepcopy(offline_chunks) if offline_chunks is not None else [
            {"choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
            for piece in ["这是教材预设", "的流式片段，", "不是实际模型输出。"]
        ] + [{"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}]
        if not isinstance(chunks, list) or any(not isinstance(c, dict) for c in chunks):
            raise ModelAPIError("INPUT", "离线流式样本必须是 JSON 对象列表")
        for chunk in chunks:
            _validate_chunk(chunk)
            chunk["_meta"] = {"mode": "offline"}
            chunk["usage"] = None
            yield chunk
        return
    if offline_chunks is not None:
        raise ModelAPIError("INPUT", "真实调用不能同时提供离线片段")
    payload.update(stream=True, stream_options={"include_usage": True})
    with _connection(payload, timeout) as response:
        data_lines = []
        total_bytes = 0
        for raw_line in response:
            total_bytes += len(raw_line)
            if total_bytes > 8 * 1024 * 1024:
                raise ModelAPIError("PROTOCOL", "流式响应超出教学客户端的大小限制")
            try:
                line = raw_line.decode("utf-8").rstrip("\r\n")
            except UnicodeError:
                raise ModelAPIError("PROTOCOL", "流式响应不是 UTF-8 文本") from None
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
            elif not line and data_lines:
                data = "\n".join(data_lines)
                data_lines.clear()
                if data == "[DONE]":
                    return
                chunk = _decode(data)
                _validate_chunk(chunk)
                chunk["_meta"] = {"mode": "live"}
                yield chunk
        raise ModelAPIError("INCOMPLETE_STREAM", "连接已关闭但未收到 [DONE]，不能把部分输出当作完整结果", retryable=True)
