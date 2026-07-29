from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from playwright.async_api import Browser, Playwright, async_playwright

logger = logging.getLogger(__name__)

# 차단/챌린지 페이지 본문에서 공통적으로 보이는 문구들 (cf-mitigated 같은 차단 신호는
# 응답 헤더에만 있어 본문 검사로는 못 잡지만, 그 경우는 항상 비-200 상태코드도 같이 오므로
# status 체크로 걸러진다). "해당 아이피는 차단된 아이피입니다"는 coolenjoy가 IP를 차단할 때
# HTTP 200으로 주는 안내 문구라 상태코드만으론 못 잡아서 따로 추가했다. 진짜 삭제/404 마커와
# 겹치지 않도록 확인된 값만 넣는다.
_BLOCK_MARKERS = ("Just a moment", "Access Denied", "Attention Required", "차단된 아이피")

# Playwright Chromium(CDP로 제어)은 headless 특유의 신호(navigator.webdriver, CDP 연결
# 자체의 타이밍/행동 패턴, headless 전용 WebGL 렌더러 문자열 등)가 있어 Cloudflare가
# "실제 JS를 실행하는 브라우저"인데도 자동화로 탐지해 계속 차단하는 경우가 있었다 - 관리자가
# 같은 서버에서 webtop Firefox로 직접 열었을 때는 성공하는 걸로 확인됨. Firefox는 Playwright가
# CDP가 아니라 별도 프로토콜(Juggler)로 제어해서 그 특정 탐지에 걸리지 않는다.
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0"

_playwright: Playwright | None = None
_browser: Browser | None = None
# 프로세스 전체에서 브라우저 인스턴스 하나만 띄우고 재사용한다 (요청마다 새로 띄우면
# Cloudflare 챌린지를 매번 새로 풀어야 해서 느리고, 브라우저 기동 자체도 무겁다).
_init_lock = asyncio.Lock()


async def get_browser() -> Browser:
    global _playwright, _browser
    async with _init_lock:
        if _browser is None:
            _playwright = await async_playwright().start()
            # headless=False: 실제 서버에서 로그로 확인해보니 headless Firefox도 여전히
            # 차단됐다 (관리자가 webtop에서 "진짜 창을 띄운" Firefox로 열었을 때만 성공함).
            # 컨테이너엔 화면이 없으니 Dockerfile의 xvfb-run(가상 디스플레이)으로 감싸서
            # 돌린다 - headless 특유의 신호 없이 진짜 창모드 브라우저처럼 보이게 하기 위함.
            _browser = await _playwright.firefox.launch(headless=False)
            logger.info("playwright firefox browser launched (headed, via xvfb)")
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
    # navigator.webdriver=true는 가장 흔한 자동화 탐지 신호라 실제 브라우저처럼 지운다.
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
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
    if any(marker in html for marker in _BLOCK_MARKERS):
        logger.warning(
            "playwright still blocked for %s (nav status=%s, title=%r, len=%d)",
            url, status, title, len(html),
        )
        return 403, html
    return status, html


def looks_blocked(status: int, html: str) -> bool:
    """응답이 실제 콘텐츠가 아니라 차단/챌린지 페이지인지 판단한다 (404는 차단이 아니다)."""
    if status == 404:
        return False
    if status != 200:
        return True
    return any(marker in html for marker in _BLOCK_MARKERS)


async def get_with_fallback(
    fetch_method: str, url: str, requests_get: Callable[[str], Awaitable[tuple[int, str]]]
) -> tuple[int, str]:
    """사이트별 요청 방식을 하나로 통일한다.

    "playwright"면 바로 헤드리스 브라우저로 접근한다. "requests"(기본값)면 더 가볍고 빠른
    방식(curl_cffi/aiohttp)을 먼저 시도하고, 결과가 차단된 것으로 보이면 관리자가 수동으로
    설정을 바꾸지 않아도 그 요청 한 번만 자동으로 playwright로 재시도한다 - 평소엔 가볍게
    돌다가, 막힌 시점부터는 계속 성공해야 하는 요구사항 때문에 자동 폴백을 기본으로 한다.
    """
    if fetch_method == "playwright":
        return await browser_get(url)
    try:
        status, html = await requests_get(url)
    except Exception:
        status, html = 0, ""
    if looks_blocked(status, html):
        logger.info("requests mode blocked for %s (status=%s), falling back to playwright", url, status)
        return await browser_get(url)
    return status, html
