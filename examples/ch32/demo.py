"""用两类合成需求说明同一套约束检查如何迁移，不构建完整业务应用。"""

import json


def check_study_plan(plan, catalog, *, available_minutes, completed):
    """检查时长、课程存在性、重复安排和先修条件，未通过时不保存计划。"""
    if not isinstance(available_minutes, int) or available_minutes < 0:
        raise ValueError("可用分钟数应为非负整数")
    errors = []
    if len(plan) != len(set(plan)):
        errors.append("重复安排课程")
    total = 0
    learned = set(completed)
    for course_id in plan:
        if course_id not in catalog:
            errors.append(f"课程不存在：{course_id}")
            continue
        course = catalog[course_id]
        total += course["minutes"]
        if course_id in completed:
            errors.append(f"重复安排已完成课程：{course_id}")
        if not set(course["requires"]) <= learned:
            errors.append(f"先修条件不足：{course_id}")
        learned.add(course_id)
    if total > available_minutes:
        errors.append("总时长超过可用时间")
    return {"success": not errors, "minutes": total, "errors": errors}


def check_event(candidate, *, participants, budget_cents, available_slots):
    """检查固定教学场地约束，不预订真实场地。"""
    errors = []
    if candidate["capacity"] < participants:
        errors.append("场地容量不足")
    if candidate["price_cents"] > budget_cents:
        errors.append("场地费用超出预算")
    if candidate["slot"] not in available_slots:
        errors.append("时段不可用")
    return {"success": not errors, "errors": errors}


def main():
    """比较文字看起来合理的方案与代码实际检查的结果。"""
    catalog = {
        "python": {"minutes": 30, "requires": []},
        "api": {"minutes": 40, "requires": ["python"]},
        "tools": {"minutes": 35, "requires": ["api"]},
    }
    bad_study = check_study_plan(["tools", "api"], catalog, available_minutes=60, completed={"python"})
    good_study = check_study_plan(["api"], catalog, available_minutes=60, completed={"python"})
    assert bad_study["errors"] == ["先修条件不足：tools", "总时长超过可用时间"]
    assert good_study["success"] and good_study["minutes"] == 40
    assert not check_study_plan(["api", "api"], catalog, available_minutes=100, completed={"python"})["success"]
    assert not check_study_plan(["unknown"], catalog, available_minutes=60, completed=set())["success"]
    candidate = {"capacity": 12, "price_cents": 12000, "slot": "周六14点"}
    bad_event = check_event(candidate, participants=20, budget_cents=10000, available_slots={"周六14点"})
    assert bad_event["errors"] == ["场地容量不足", "场地费用超出预算"]
    good_event = check_event({**candidate, "capacity": 25, "price_cents": 9000}, participants=20, budget_cents=10000, available_slots={"周六14点"})
    assert good_event["success"]
    assert not check_event(candidate, participants=10, budget_cents=20000, available_slots=set())["success"]
    print(json.dumps({"性质": "原创合成候选，未调用模型、未保存计划、未预订场地", "学习方案_错误": bad_study, "学习方案_可用": good_study, "活动方案_错误": bad_event, "活动方案_可用": good_event}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
