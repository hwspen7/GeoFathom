"""Safe deterministic fallback when no language model is available."""

import re


def fallback_intent(message: str) -> dict[str, str]:
    text = message.strip()
    filters = re.search(
        r"(?:超过|至少|以内|范围内|大于|小于|between|within|larger than|smaller than|square meters|平方[米公里]|公顷)",
        text, re.IGNORECASE,
    )
    if filters and re.search(r"(?:找|寻|search|find|筛选|哪些|所有)", text, re.IGNORECASE):
        return {
            "action": "discover",
            "query": text,
            "explanation": "Spatial feature discovery requires an indexed dataset.",
        }
    text = re.sub(
        r"^(?:请|麻烦|可以)?(?:帮我|给我)?(?:查找|查询|寻找|搜索|定位|测量|计算|看看|找出|找|查|show me|find|locate|measure|search for)\s*",
        "", text, flags=re.IGNORECASE,
    ).strip(" ，,。.?!？")
    text = re.sub(
        r"(?:的)?(?:完整)?(?:占地)?(?:面积|边界|轮廓|周长|有多大|在哪里|位置)(?:是多少|有多少)?$",
        "", text, flags=re.IGNORECASE,
    ).strip(" ，,。.?!？")
    return {"action": "locate", "query": text or message.strip(), "explanation": "Direct place search."}
