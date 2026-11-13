"""用普通 Python 与可选 LangGraph 执行同一查询流程，不调用模型。"""

import argparse
import json
from typing import TypedDict


class QueryState(TypedDict, total=False):
    """节点间传递的明确状态，缺失订单号时走追问分支。"""

    order_id: str
    route: str
    answer: str


def decide(state):
    """按已有字段选择流程；这是固定规则，不是模型规划。"""
    return {"route": "lookup" if state.get("order_id") else "ask"}


def lookup(state):
    """查询一条只读虚构记录，不承担真实业务权限。"""
    records = {"A1001": "已发货"}
    return {"answer": records.get(state["order_id"], "未找到订单")}


def ask(state):
    """缺少必要输入时返回明确追问。"""
    return {"answer": "请提供订单号"}


def run_python(initial):
    """字典保存状态，条件分支决定调用哪个普通函数。"""
    state = dict(initial)
    state.update(decide(state))
    state.update(lookup(state) if state["route"] == "lookup" else ask(state))
    return state


def build_graph():
    """可选框架只负责调度相同节点，不更换业务判断规则。"""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as error:
        raise SystemExit("请先安装本章 requirements-framework.txt，或省略 --langgraph") from error
    builder = StateGraph(QueryState)
    builder.add_node("decide", decide)
    builder.add_node("lookup", lookup)
    builder.add_node("ask", ask)
    builder.add_edge(START, "decide")
    builder.add_conditional_edges("decide", lambda state: state["route"], {"lookup": "lookup", "ask": "ask"})
    builder.add_edge("lookup", END)
    builder.add_edge("ask", END)
    return builder.compile()


def main():
    """验证有编号、无编号和未知编号三条固定路径。"""
    parser = argparse.ArgumentParser(description="查询流程到状态图的映射")
    parser.add_argument("--langgraph", action="store_true", help="同时验证已安装的 LangGraph")
    args = parser.parse_args()
    inputs = [{"order_id": "A1001"}, {}, {"order_id": "A9999"}]
    results = [run_python(item) for item in inputs]
    assert [item["answer"] for item in results] == ["已发货", "请提供订单号", "未找到订单"]
    report = {"性质": "确定性流程，无模型调用", "普通Python": results}
    if args.langgraph:
        from importlib.metadata import version
        graph = build_graph()
        graph_results = [graph.invoke(item) for item in inputs]
        assert graph_results == results
        report["LangGraph版本"] = version("langgraph")
        report["三条路径结果一致"] = True
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
