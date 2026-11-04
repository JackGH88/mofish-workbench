"""Built-in writing material library plus validation for account-owned assets.

The workbench needs one shared definition of the selectable 开头钩子 / 结构模板 / 结尾引导 so the
API, the Agent prompt and the tests cannot drift apart. Custom assets reuse the same
shape with ``builtin=False`` so the client can render one list per kind.
"""
from __future__ import annotations

from typing import Any


HOOK_KIND = "hook"
STRUCTURE_KIND = "structure"
ENDING_KIND = "ending"
WRITING_ASSET_KINDS = (HOOK_KIND, STRUCTURE_KIND, ENDING_KIND)
WRITING_ASSET_FORMATS = ("video", "article")

ASSET_NAME_LIMIT = 60
ASSET_CONTENT_LIMIT = 2000
ASSET_NOTE_LIMIT = 400
ASSET_EXAMPLE_LIMIT = 400
ASSET_STEP_LIMIT = 24
ASSET_LIMIT_PER_KIND = 200

# ``content`` is what the Agent prompt consumes; ``description`` / ``example`` are the
# short card copy the operator reads while choosing.
BUILTIN_HOOKS: tuple[dict[str, str], ...] = (
    {
        "id": "hook-quantified",
        "name": "量化冲击",
        "tag": "具体数字",
        "description": "用具体数字呈现变化。",
        "example": "例：我用3个步骤整理一周的工作资料。",
        "content": "开头用一个具体、反差大的数字制造冲击。示例：我用3个步骤整理一周的工作资料。",
    },
    {
        "id": "hook-pain",
        "name": "先说你的难",
        "tag": "痛点扎心",
        "description": "先说出用户正在遇到的难题。",
        "example": "例：资料找半天，整理又花一晚上？",
        "content": "第一句直接说出目标受众正在经历的难题，让对方觉得“说的就是我”。示例：资料找半天，整理又花一晚上？",
    },
    {
        "id": "hook-contrarian",
        "name": "打破预期",
        "tag": "反差常识",
        "description": "从一个不同的观点切入。",
        "example": "例：整理资料，未必需要先建文件夹。",
        "content": "先抛出一个与大家默认认知相反的结论，制造停顿。示例：整理资料，未必需要先建文件夹。",
    },
    {
        "id": "hook-result-first",
        "name": "先给答案",
        "tag": "结果前置",
        "description": "先讲结果，再解释方法。",
        "example": "例：先说结论，这3步能让资料更好找。",
        "content": "把最有价值的结果放在最前面，再回头讲怎么做到。示例：先说结论，这3步能让资料更好找。",
    },
    {
        "id": "hook-identity",
        "name": "精准喊人",
        "tag": "身份代入",
        "description": "让目标人群快速对号入座。",
        "example": "例：如果你每周都要写周报，试试这套方法。",
        "content": "开头直接点名目标人群，让对的人一秒确认这条内容和他有关。示例：如果你每周都要写周报，试试这套方法。",
    },
    {
        "id": "hook-question",
        "name": "留个钩子",
        "tag": "悬念提问",
        "description": "用一个问题引出后续内容。",
        "example": "例：同样的资料，为什么有人一找就有？",
        "content": "抛出一个对方很想知道答案的问题，引出后续内容。示例：同样的资料，为什么有人一找就有？",
    },
)

_VIDEO_STRUCTURES: tuple[dict[str, Any], ...] = (
    {
        "id": "structure-video-problem",
        "name": "痛点解决型",
        "tag": "教程 / 避坑",
        "description": "适合讲方法、经验与解决方案。",
        "steps": ("痛点开场", "我踩的坑", "3个方法", "结果对比", "结尾引导"),
    },
    {
        "id": "structure-video-story",
        "name": "故事反转型",
        "tag": "故事 / 观点",
        "description": "适合用故事引发共鸣，再反转带出观点。",
        "steps": ("反常识开场", "铺垫", "反转", "揭示原因", "观点升华"),
    },
    {
        "id": "structure-video-list",
        "name": "清单盘点型",
        "tag": "清单 / 干货",
        "description": "适合整理干货、工具或资源清单。",
        "steps": ("明确收益", "逐条展开", "总结回顾", "结尾引导"),
    },
)

_ARTICLE_STRUCTURES: tuple[dict[str, Any], ...] = (
    {
        "id": "structure-article-problem",
        "name": "痛点解决型",
        "tag": "教程 / 避坑",
        "description": "适合图文分步讲解方法与步骤。",
        "steps": ("痛点开场", "方法步骤", "结果对比", "结尾引导"),
    },
    {
        "id": "structure-article-story",
        "name": "故事反转型",
        "tag": "故事 / 观点",
        "description": "适合用一段经历带出观点。",
        "steps": ("反常识开场", "经历铺垫", "反转", "观点总结"),
    },
    {
        "id": "structure-article-list",
        "name": "清单盘点型",
        "tag": "清单 / 干货",
        "description": "适合把干货整理成可收藏的清单。",
        "steps": ("明确收益", "逐条展开", "总结回顾", "结尾引导"),
    },
)


def _structure_entry(item: dict[str, Any], asset_format: str) -> dict[str, Any]:
    steps = list(item["steps"])
    return {
        "id": item["id"],
        "kind": STRUCTURE_KIND,
        "name": item["name"],
        "tag": item["tag"],
        "description": item["description"],
        "example": "",
        "content": " → ".join(steps),
        "steps": steps,
        "format": asset_format,
        "builtin": True,
    }


def builtin_hooks() -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "kind": HOOK_KIND,
            "name": item["name"],
            "tag": item["tag"],
            "description": item["description"],
            "example": item["example"],
            "content": item["content"],
            "steps": [],
            "format": "",
            "builtin": True,
        }
        for item in BUILTIN_HOOKS
    ]


def builtin_structures() -> list[dict[str, Any]]:
    return [
        *(_structure_entry(item, "video") for item in _VIDEO_STRUCTURES),
        *(_structure_entry(item, "article") for item in _ARTICLE_STRUCTURES),
    ]


ENDING_PRESETS = (
    ("comment", "评论互动", "围绕本期内容提出一个具体、容易回答的问题。", "你整理资料时，最头疼的是找不到，还是存得太乱？"),
    ("save", "收藏复用", "说明未来可以在什么场景再次使用本期方法，自然邀请收藏。", "下次整理周报资料时，可以照着这三个步骤试一遍，先收藏备用。"),
    ("follow", "关注追更", "明确后续内容的价值，再自然邀请关注。", "后面会继续分享 AI 办公的实际用法，想一起实践可以关注。"),
    ("preview", "下期预告", "承接本期内容，预告下一步；没有真实安排时不编造承诺，改为建议下一步行动。", "资料整理好了，下一期再讲怎么把它变成一份周报。"),
    ("action", "行动建议", "给观众一个现在就能完成的小动作。", "今天先挑一个最乱的文件夹，按这套方法整理一次。"),
    ("summary", "总结升华", "回扣主题，用一句清晰观点结束，不强加互动要求。", "整理的目的，是让资料在需要的时候派上用场。"),
)


def builtin_endings() -> list[dict[str, Any]]:
    return [dict(id="ending-" + key, kind=ENDING_KIND, name=name, content=content,
                 description=content, note="", example="例：" + example,
                 tag="", steps=[], format="", builtin=True)
            for key, name, content, example in ENDING_PRESETS]


def builtin_assets(kind: str) -> list[dict[str, Any]]:
    if kind == ENDING_KIND:
        return builtin_endings()
    if kind == HOOK_KIND:
        return builtin_hooks()
    if kind == STRUCTURE_KIND:
        return builtin_structures()
    raise ValueError("素材类型无效。")


def is_builtin_asset_id(asset_id: Any) -> bool:
    """True when an id belongs to the shipped library; edits require account context."""
    normalized = str(asset_id or "").strip()
    if not normalized:
        return False
    return any(item["id"] == normalized for item in (*builtin_hooks(), *builtin_structures(), *builtin_endings()))


def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clean_block(value: Any, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:limit]


def split_structure_steps(content: str) -> list[str]:
    """Turn one structure line into ordered steps for the card preview."""
    normalized = str(content or "").replace("->", "→").replace("→", "\n")
    normalized = normalized.replace("；", "\n").replace(";", "\n").replace("，", "\n").replace(",", "\n")
    steps: list[str] = []
    for chunk in normalized.split("\n"):
        text = " ".join(chunk.split()).strip(" 、,，。.")
        if text and text not in steps:
            steps.append(text[:60])
        if len(steps) >= ASSET_STEP_LIMIT:
            break
    return steps


def normalize_asset_fields(kind: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Validate one create/update payload for a custom asset."""
    if kind not in WRITING_ASSET_KINDS:
        raise ValueError("素材类型无效。")
    name = _clean_text(fields.get("name"), ASSET_NAME_LIMIT)
    if not name:
        raise ValueError("请填写素材名称。")
    content = _clean_block(fields.get("content"), ASSET_CONTENT_LIMIT).strip()
    if not content:
        raise ValueError("请填写素材内容。")
    asset: dict[str, Any] = {
        "kind": kind,
        "name": name,
        "content": content,
        "note": _clean_block(fields.get("note"), ASSET_NOTE_LIMIT),
        "example": _clean_text(fields.get("example"), ASSET_EXAMPLE_LIMIT),
    }
    if kind == STRUCTURE_KIND:
        asset_format = str(fields.get("format") or "").strip()
        if asset_format not in WRITING_ASSET_FORMATS:
            raise ValueError("请选择结构模板适用的内容形式。")
        asset["format"] = asset_format
        asset["steps"] = split_structure_steps(content)
    else:
        asset["format"] = ""
        asset["steps"] = []
    return asset


def asset_view(asset: dict[str, Any], *, builtin: bool) -> dict[str, Any]:
    """Expose one stored asset in the shape the client renders."""
    content = str(asset.get("content") or "")
    steps = asset.get("steps")
    if not isinstance(steps, list):
        steps = split_structure_steps(content)
    return {
        "id": str(asset.get("id") or ""),
        "kind": str(asset.get("kind") or ""),
        "name": str(asset.get("name") or ""),
        "tag": str(asset.get("tag") or ""),
        "description": str(asset.get("description") or asset.get("note") or ""),
        "note": str(asset.get("note") or ""),
        "example": str(asset.get("example") or ""),
        "content": content,
        "steps": [str(step) for step in steps if str(step).strip()],
        "format": str(asset.get("format") or ""),
        "builtin": builtin,
        "sourceBreakdownId": str(asset.get("sourceBreakdownId") or ""),
        "sourceTitle": str(asset.get("sourceTitle") or ""),
        "createdAt": str(asset.get("createdAt") or ""),
        "updatedAt": str(asset.get("updatedAt") or ""),
    }
