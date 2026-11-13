"""本地模拟界面的观察与动作；不调用视觉模型，不控制真实浏览器或商家账号。"""

import json
from copy import deepcopy


def initial_state():
    """创建一笔虚构草稿；界面版本用于拒绝基于旧观察的动作。"""
    return {"version": 1, "order_id": "A1001", "status": "draft", "requests": []}


def observe(state):
    """直接从模拟环境读取观察；这一步不是 OCR 或图像识别。"""
    return deepcopy({key: state[key] for key in ("version", "order_id", "status")})


def execute(state, action, *, confirmed=False):
    """校验观察版本、对象、动作与确认后，才修改本地教学状态。"""
    if action.get("version") != state["version"]:
        return {"success": False, "error": "观察已过期，请重新读取"}
    if action.get("order_id") != state["order_id"]:
        return {"success": False, "error": "对象不匹配"}
    if action.get("name") != "submit_request":
        return {"success": False, "error": "不在可执行动作列表中"}
    if confirmed is not True:
        return {"success": False, "error": "需要明确确认"}
    if state["status"] != "draft":
        return {"success": False, "error": "草稿已提交，不能重复执行"}
    state["requests"].append({"id": "R001", "order_id": state["order_id"]})
    state["status"] = "submitted"
    state["version"] += 1
    return {"success": True, "request_id": "R001"}


def scale_point(x, y, image_size, viewport_size):
    """仅适用于无裁剪、无偏移、等比例对应的截图与视口。"""
    iw, ih = image_size
    vw, vh = viewport_size
    if min(iw, ih, vw, vh) <= 0 or not (0 <= x < iw and 0 <= y < ih):
        raise ValueError("尺寸或坐标超出范围")
    return round(x * vw / iw), round(y * vh / ih)


def main():
    """展示拒绝未确认动作、成功提交及拒绝陈旧动作三种结果。"""
    state = initial_state()
    before = observe(state)
    action = {"name": "submit_request", "order_id": "A1001", "version": before["version"]}
    refused = execute(state, action)
    assert not refused["success"] and not state["requests"]
    success = execute(state, action, confirmed=True)
    assert success["success"] and state["status"] == "submitted"
    stale = execute(state, action, confirmed=True)
    assert not stale["success"] and len(state["requests"]) == 1
    assert before["status"] == "draft"
    assert scale_point(300, 200, (600, 400), (1200, 800)) == (600, 400)
    fresh = {**action, "version": state["version"]}
    assert not execute(state, fresh, confirmed=True)["success"]
    assert not execute(initial_state(), {**action, "order_id": "A9999"}, confirmed=True)["success"]
    print(json.dumps({
        "性质": "程序预设动作，本地状态模拟，未做视觉识别",
        "执行前": before, "未确认": refused, "执行回包": success,
        "执行后": observe(state), "重复旧动作": stale,
        "申请条数": len(state["requests"]), "坐标映射": [600, 400],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
