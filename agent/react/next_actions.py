"""跑完后生成「下一步可执行动作」建议，供前端一键作为提示词发送。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent.schemas.task import ReActTaskPlan


def _clip(text: str, n: int = 280) -> str:
    t = (text or "").strip()
    if len(t) <= n:
        return t
    return t[: n - 1].rstrip() + "…"


def build_next_actions(
    plan: ReActTaskPlan,
    *,
    success: bool,
    model_path: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    根据本次运行结果生成 2~4 条下一步建议。
    每条含 id / label / prompt；prompt 可直接作为用户消息发送。
    """
    path = (model_path or getattr(plan, "model_path", None) or "").strip()
    path_hint = f"模型路径：{path}" if path else "请基于当前会话中已生成的部分模型继续。"
    err = (plan.error or "").strip()
    user_goal = _clip(plan.user_input or "", 180)
    actions: List[Dict[str, str]] = []

    if success and path:
        actions.extend(
            [
                {
                    "id": "export_results",
                    "label": "导出结果图/数据",
                    "prompt": (
                        f"请基于已生成的模型继续：{path_hint}\n"
                        "导出关键物理量的结果图与数据到 output/ 目录（如温度场、等效应力），"
                        "并简要说明每个结果的物理含义与文件路径。"
                    ),
                },
                {
                    "id": "parametric_scan",
                    "label": "参数扫描对比",
                    "prompt": (
                        f"请在当前模型上增加参数化扫描：{path_hint}\n"
                        "选择 1 个关键参数（材料、载荷或几何尺寸）扫描 3~5 个取值，"
                        "重新求解后导出对比 CSV 到 output/，并总结趋势。"
                    ),
                },
                {
                    "id": "refine_mesh",
                    "label": "加密网格重算",
                    "prompt": (
                        f"请保持物理设置不变，将网格提高一级并重新求解：{path_hint}\n"
                        "对比关键量变化，判断网格是否已足够。"
                    ),
                },
                {
                    "id": "edit_bc",
                    "label": "改边界后重算",
                    "prompt": (
                        f"请基于当前模型副本调整边界条件后重新求解：{path_hint}\n"
                        "若我未指定新边界，请先给出 2~3 个合理改动方案并选推荐项执行，"
                        "最后导出结果图。"
                    ),
                },
            ]
        )
    else:
        err_l = err.lower()
        if any(k in err_l for k in ("nu", "泊松", "young", "杨氏", "材料属性", "thermalconductivity", "导热")):
            actions.append(
                {
                    "id": "fix_material",
                    "label": "补齐材料属性再求解",
                    "prompt": (
                        f"上次失败与材料属性有关：{_clip(err, 220)}\n"
                        f"{path_hint}\n"
                        "请补齐固体力学所需的 E/nu 与传热所需的导热系数 k（及必要比热），"
                        "不要重建无关步骤，然后继续网格/研究并求解到可算。"
                    ),
                }
            )
        if any(k in err for k in ("未知特征", "Convective", "FixedConstraint", "Displacement", "特征 ID")):
            actions.append(
                {
                    "id": "fix_bc_features",
                    "label": "改用正确边界特征",
                    "prompt": (
                        f"上次边界/特征设置失败：{_clip(err, 220)}\n"
                        f"{path_hint}\n"
                        "请改用当前 COMSOL 版本可用的官方特征 ID 重新设置热/结构边界，"
                        "并继续求解到可算；不要停在半成品。"
                    ),
                }
            )
        if "REORCHESTRATE" in err or "重新编排" in err:
            actions.append(
                {
                    "id": "replan_closed_loop",
                    "label": "重新规划并闭环求解",
                    "prompt": (
                        f"请重新规划并一次性闭环完成可求解模型。\n"
                        f"原需求：{user_goal or '（见上文）'}\n"
                        f"上次问题：{_clip(err, 220)}\n"
                        f"{path_hint}\n"
                        "允许简化几何或边界，但必须产出可求解的 .mph。"
                    ),
                }
            )

        actions.append(
            {
                "id": "continue_fix",
                "label": "继续修复直到可算",
                "prompt": (
                    f"请继续修复当前建模任务直到可求解。\n"
                    f"原需求：{user_goal or '（见上文）'}\n"
                    f"上次失败：{_clip(err, 260) or '任务未完成'}\n"
                    f"{path_hint}\n"
                    "优先修补材料/边界/网格/研究配置，不要从零重建，完成后导出关键结果。"
                ),
            }
        )
        if path:
            actions.append(
                {
                    "id": "inspect_partial",
                    "label": "检查半成品并补全",
                    "prompt": (
                        f"请打开并检查已有部分模型：{path}\n"
                        "列出已完成与缺失的节点（几何/材料/物理场/网格/研究），"
                        "然后只补缺失部分并求解到可算。"
                    ),
                }
            )
        else:
            actions.append(
                {
                    "id": "restart_minimal",
                    "label": "用最小可算模型重做",
                    "prompt": (
                        f"请用最小可算假设重做：{user_goal or '当前建模需求'}。\n"
                        "几何可简化，材料用典型默认值，边界给齐，最终必须稳态可求解并导出一张结果图。"
                    ),
                }
            )

    # 去重并限制数量
    seen = set()
    unique: List[Dict[str, str]] = []
    for item in actions:
        key = item.get("id") or item.get("label")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(
            {
                "id": str(item.get("id") or ""),
                "label": str(item.get("label") or "下一步").strip(),
                "prompt": str(item.get("prompt") or "").strip(),
            }
        )
        if len(unique) >= 4:
            break
    return [a for a in unique if a["prompt"]]


def next_actions_event_payload(
    plan: ReActTaskPlan,
    *,
    success: bool,
    model_path: Optional[str] = None,
) -> Dict[str, Any]:
    actions = build_next_actions(plan, success=success, model_path=model_path)
    return {
        "title": "下一步可执行建议",
        "hint": "点击即可作为提示词发送",
        "success": success,
        "model_path": model_path,
        "actions": actions,
    }
