"""演示技能目录、磁盘正文和模型上下文的区别；不调用模型或执行工具。"""

from pathlib import Path


SKILLS_ROOT = Path(__file__).with_name("skills")
CATALOG = {
    "return-guide": "用户询问退货条件或申请步骤时，核对商品情况、当前政策和操作确认。",
    "logistics-guide": "用户询问发货进度或物流位置时，查询并解释该用户有权访问的订单记录。",
}


def load_skill(name):
    """只读取注册表中的技能；这个小加载器不实现完整 YAML 规范。"""
    if name not in CATALOG:
        raise ValueError("未注册的技能名称")
    path = (SKILLS_ROOT / name / "SKILL.md").resolve()
    if not path.is_relative_to(SKILLS_ROOT.resolve()):
        raise ValueError("技能路径超出允许目录")
    text = path.read_text(encoding="utf-8")
    sections = text.split("---", 2)
    if len(sections) != 3 or sections[0].strip():
        raise ValueError("教学技能文件缺少头部元数据")
    return sections[2].strip()


def build_messages(question, activated_names):
    """应用显式把已选技能放进请求；读文件本身不会更新模型上下文。"""
    catalog = "\n".join(f"{name}: {description}" for name, description in CATALOG.items())
    messages = [{"role": "system", "content": "可用技能目录：\n" + catalog}]
    for name in dict.fromkeys(activated_names):
        messages.append({"role": "system", "content": f"已激活技能 {name}：\n" + load_skill(name)})
    messages.append({"role": "user", "content": question})
    return messages


def main():
    question = "我想了解退货流程。"
    unloaded = build_messages(question, [])
    loaded_text = load_skill("return-guide")
    assert loaded_text not in "\n".join(message["content"] for message in unloaded)
    selected = build_messages(question, ["return-guide", "return-guide"])
    all_skills = build_messages(question, list(CATALOG))
    selected_text = "\n".join(message["content"] for message in selected)
    assert loaded_text in selected_text
    assert selected_text.count("已激活技能 return-guide") == 1
    assert "已激活技能 logistics-guide" not in selected_text
    try:
        load_skill("../其他文件")
    except ValueError:
        print("未注册路径：已拒绝")
    else:
        raise AssertionError("不应读取未注册路径")
    size = lambda messages: sum(len(message["content"]) for message in messages)
    print("模式：本地加载机制演示；技能选择由代码预设")
    print("只发目录字符数：", size(unloaded))
    print("只激活退货字符数：", size(selected))
    print("激活全部字符数：", size(all_skills))
    print("磁盘已读但未注入：", loaded_text not in "\n".join(message["content"] for message in unloaded))
    print("退货正文已注入：", loaded_text in selected_text)
    print("实际工具执行次数：0")


if __name__ == "__main__":
    main()
