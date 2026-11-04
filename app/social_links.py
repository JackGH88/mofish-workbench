"""Resolve public social profile links; paid data queries use the platform."""
from __future__ import annotations
import re
from typing import Any, Optional

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

SHARE_URL_RE = re.compile(r"https?://[^\s\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+", re.IGNORECASE)
SEC_UID_RE = re.compile(r"MS4wLjAB[A-Za-z0-9_-]{12,}")
USER_PATH_RE = re.compile(r"douyin\.com/user/([^/?#\s]+)", re.IGNORECASE)
VIDEO_PATH_RE = re.compile(r"douyin\.com/(?:video|note)/\d+", re.IGNORECASE)


class DataServiceError(Exception):
    """上游数据接口调用失败，``code`` 供接口层映射成 HTTP 状态和提示文案。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status = status


def extract_share_url(text: str) -> str:
    """从分享文本里取出第一个链接；抖音分享文案通常把链接夹在中文之间。"""
    match = SHARE_URL_RE.search(str(text or ""))
    if not match:
        return ""
    return match.group(0).rstrip(".,;:!?，。、；：！？")


def sec_user_id_from_text(text: str) -> str:
    """从主页链接、分享落地页或直接粘贴的 sec_user_id 里解析稳定身份。

    返回空串表示这段文本里没有可用的博主身份；调用方据此提示用户
    「作品链接不能当博主主页」，而不是拿昵称或作品 ID 猜一个身份。
    """
    value = str(text or "").strip()
    if not value:
        return ""
    direct = SEC_UID_RE.search(value)
    if direct:
        return direct.group(0)
    user_path = USER_PATH_RE.search(value)
    if user_path:
        candidate = user_path.group(1)
        if SEC_UID_RE.fullmatch(candidate):
            return candidate
        return candidate
    return ""


def looks_like_video_link(text: str) -> bool:
    return bool(VIDEO_PATH_RE.search(str(text or "")))


async def resolve_creator_sec_user_id(share_text: str, *, client: Optional[Any] = None) -> str:
    """把博主主页链接解析成 sec_user_id；整段解析只在本地与跳转过程中完成，不调用付费接口。

    工作台不再持有数据接口密钥，因此这里只解析公开主页链接。
    """
    raw = str(share_text or "").strip()
    if not raw:
        raise DataServiceError("monitor_blogger_link_required", "请粘贴博主主页链接。")
    direct = sec_user_id_from_text(raw)
    if direct:
        return direct
    url = extract_share_url(raw)
    if not url:
        raise DataServiceError("monitor_blogger_link_invalid", "没有识别到链接，请粘贴博主主页链接。")
    if looks_like_video_link(url):
        raise DataServiceError(
            "monitor_blogger_link_unsupported",
            "这是作品链接而不是博主主页；请在抖音里进入博主主页后复制主页链接。",
        )
    final_url = await _follow_redirect(url, client=client)
    resolved = sec_user_id_from_text(final_url) or sec_user_id_from_text(url)
    if not resolved:
        raise DataServiceError(
            "monitor_blogger_link_unresolved",
            "没能从这个链接解析出博主身份，请确认是抖音博主主页链接。",
        )
    return resolved


async def _follow_redirect(url: str, *, client: Optional[Any] = None) -> str:
    """跟随短链跳转拿到最终主页地址；失败时原样返回，由调用方决定如何提示。"""
    headers = {"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml"}
    if client is not None:
        return await client.follow(url, headers=headers)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http:
            response = await http.get(url, headers=headers)
            return str(response.url)
    except Exception:  # noqa: BLE001 - 拿不到最终地址时按原链接解析
        return url
