"""HTTP 封装:统一 UA / 超时 / 重定向,以及轻量网页正文抽取(无第三方解析库)。"""
from __future__ import annotations

import html as _html
import re

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def get_text(
    url: str,
    *,
    timeout: float = 8.0,
    headers: dict | None = None,
    params: dict | None = None,
    retries: int = 1,
) -> str:
    """GET 返回文本。失败抛 httpx 异常,由调用方降级。"""
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as c:
                r = c.get(url, headers=h, params=params)
                r.raise_for_status()
                return r.text
        except (httpx.HTTPError, OSError) as e:  # noqa: PERF203
            last_exc = e
    raise last_exc  # type: ignore[misc]


def get_bytes(
    url: str,
    *,
    timeout: float = 20.0,
    headers: dict | None = None,
) -> bytes:
    """GET 返回二进制(PDF 下载用)。"""
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    with httpx.Client(timeout=timeout, follow_redirects=True) as c:
        r = c.get(url, headers=h)
        r.raise_for_status()
        return r.content


def extract_article(html_text: str, max_chars: int = 6000) -> dict:
    """轻量正文抽取:去脚本/样式 → 段落切分 → 拼接,返回 {title, text}。"""
    text = html_text
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if m:
        title = _html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    # 去掉脚本/样式/导航类标签
    text = re.sub(r"(?is)<(script|style|noscript|iframe|svg|nav|footer|header)[^>]*>.*?</\1>", " ", text)
    # 块级标签 → 换行,便于分段
    text = re.sub(r"(?is)<br\s*/?>|</(p|h[1-6]|li|tr|div)>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = _html.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    # 保留足够长的行(过滤导航/页脚碎片),再整体截断
    lines = [ln for ln in lines if len(ln) >= 15]
    return {"title": title, "text": "\n".join(lines)[:max_chars]}
