from __future__ import annotations


def build_template_reason(model_name: str, factors: list[str]) -> str:
    if not factors:
        return f"{model_name}满足当前核心筛选条件，可加入候选清单进一步比较。"
    if len(factors) == 1:
        return f"推荐 {model_name}，因为{factors[0]}。"
    return f"推荐 {model_name}，因为{'，并且'.join(factors)}。"
