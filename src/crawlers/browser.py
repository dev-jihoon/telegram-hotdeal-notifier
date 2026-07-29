from __future__ import annotations

import asyncio
import logging

from playwright.async_api import Browser, Playwright, async_playwright

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_playwright: Playwright | None = None
_browser: Browser | None = None
# 프로세스 전체에서 브라우저 인스턴스 하나만 띄우고 재사용한다 (요청마다 새로 띄우면
# Cloudflare 챌린지를 매번 새로 풀어야 해서 느리고, 크로미움 기동 자체도 무겁다).
_init_lock = asyncio.Lock()


async def get_browser() -> Browser:
    global _playwright, _browser
    async with _init_lock:
        if _browser is None:
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True)
            logger.info("playwright chromium browser launched")
    return _browser


async def close_browser() -> None:
    global _playwright, _browser
    if _browser is not None:
        await _browser.close()
        _browser = None
    if _playwright is not None:
        await _playwright.stop()
        _playwright = None


async def browser_get(url: str, timeout: int = 20) -> tuple[int, str]:
    """실제 브라우저(Chromium)로 JS를 실행해 Cloudflare 챌린지를 통과한 뒤 HTML을 가져온다.

    curl_cffi(TLS/HTTP2 핑거프린트 흉내)로는 못 뚫는 "Just a moment..." 류의 JS 챌린지가
    걸린 사이트(zod)용. 챌린지는 몇 초 안에 클라이언트 사이드에서 자동으로 풀리므로,
    페이지 타이틀이 챌린지 문구에서 벗어날 때까지 잠깐 기다린다.
    """
    browser = await get_browser()
    context = await browser.new_context(user_agent=_UA, locale="ko-KR")
    try:
        page = await context.new_page()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        status = response.status if response else 0
        for _ in range(int(timeout)):
            title = await page.title()
            if "Just a moment" not in title:
                break
            await page.wait_for_timeout(1000)
        html = await page.content()
    finally:
        await context.close()

    # 챌린지 통과 실패는 원본 상태코드와 무관하게 최종 렌더링 내용으로 판단한다
    # (Cloudflare가 자체적으로 403을 주는 경우도, 200으로 챌린지 페이지만 계속 보여주는
    # 경우도 있다). 그 외(진짜 404 포함)에는 실제 내비게이션 응답 상태코드를 그대로 쓴다.
    if "Just a moment" in html or "Access Denied" in html:
        return 403, html
    return status, html
