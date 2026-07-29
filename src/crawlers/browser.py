from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

logger = logging.getLogger(__name__)

# Cloudflare JS 챌린지 타이틀(클라이언트 사이드에서 몇 초 안에 자동으로 풀림) - 브라우저
# locale을 ko-KR로 설정해두면 이 페이지 자체가 한국어로 내려온다("잠시만 기다리십시오…").
# 영어 문구만 체크했다가 한국어 챌린지를 "이미 풀림"으로 오판해서 기다리지도 않고 챌린지
# 페이지를 그대로 가져와버린 사고가 있었다 - 반드시 실제로 나온 언어를 다 포함해야 한다.
_CHALLENGE_TITLE_MARKERS = ("Just a moment", "잠시만 기다리십시오")

# 차단/챌린지 페이지 본문에서 공통적으로 보이는 문구들 (cf-mitigated 같은 차단 신호는
# 응답 헤더에만 있어 본문 검사로는 못 잡지만, 그 경우는 항상 비-200 상태코드도 같이 오므로
# status 체크로 걸러진다). "해당 아이피는 차단된 아이피입니다"는 coolenjoy가 IP를 차단할 때
# HTTP 200으로 주는 안내 문구라 상태코드만으론 못 잡아서 따로 추가했다. 진짜 삭제/404 마커와
# 겹치지 않도록 확인된 값만 넣는다.
_BLOCK_MARKERS = (*_CHALLENGE_TITLE_MARKERS, "Access Denied", "Attention Required", "차단된 아이피")

# Playwright의 Chromium/Firefox 번들은 자동화 전용으로 패치된 특수 빌드라(Firefox는 Juggler
# 프로토콜을 넣으려고, Chromium은 "Chromium for Testing") 실제 배포판 브라우저와 TLS 스택/빌드
# 자체가 미묘하게 다를 수 있다 - 관리자가 서버에서 webtop의 "진짜" Firefox로는 성공했는데
# Playwright Firefox(headless/headed 둘 다, 스텔스 패치 포함)로는 계속 막혀서 이 가능성이
# 유력해졌다. Firefox는 구조상 Playwright가 시스템에 깔린 진짜 바이너리를 못 쓰지만(Juggler가
# 그 바이너리에 내장돼 있어야 함), Chromium 계열은 channel="chrome"으로 실제 설치된 Google
# Chrome(수백만 명이 쓰는 바로 그 바이너리)을 직접 조종할 수 있어 이걸로 바꾼다 - TLS/브랜드
# 지문이 진짜와 100% 일치한다. User-Agent는 실제 설치된 Chrome이 스스로 정확하게 보고하므로
# 따로 흉내내지 않는다(가짜 UA를 덮어씌우면 오히려 내부 버전 정보와 안 맞아 더 의심스럽다).
#
# "진짜 창모드"(headless=False + Xvfb) 시도는 컨테이너에서 xvfb-run이 원인 불명으로 멈춰버려
# (xauth를 넣어도 재현) 포기했다 - 대신 headless 상태에서 자동화 지문을 최대한 지우는
# 스텔스 패치(_STEALTH_INIT_SCRIPT)로 접근한다.

# 자동화 브라우저임을 드러내는 흔한 신호들을 실제 브라우저처럼 보이게 지운다.
_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
try {
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (params) => (
        params.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(params)
    );
} catch (e) {}
"""

_playwright: Playwright | None = None
_browser: Browser | None = None
_context: BrowserContext | None = None
# 프로세스 전체에서 브라우저/컨텍스트를 하나만 띄우고 계속 재사용한다. 요청마다 새
# 컨텍스트(쿠키 없음)를 만들고 바로 닫으면 Cloudflare 입장에서 매번 "처음 보는 방문자"로
# 보여 더 의심스럽다 - 한 번이라도 통과하면 내려주는 cf_clearance 같은 쿠키를 계속
# 들고 있어야 이후 요청이 수월해진다(실제 사람이 웹탑에서 브라우저를 계속 켜두고 쓰는
# 것과 동일한 조건을 맞추기 위함).
_init_lock = asyncio.Lock()


async def _get_context() -> BrowserContext:
    global _playwright, _browser, _context
    async with _init_lock:
        if _context is None:
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(
                headless=True,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
            )
            _context = await _browser.new_context(locale="ko-KR", viewport={"width": 1920, "height": 1080})
            await _context.add_init_script(_STEALTH_INIT_SCRIPT)
            logger.info("playwright real Google Chrome browser+context launched (headless, persistent)")
    return _context


async def close_browser() -> None:
    global _playwright, _browser, _context
    if _context is not None:
        await _context.close()
        _context = None
    if _browser is not None:
        await _browser.close()
        _browser = None
    if _playwright is not None:
        await _playwright.stop()
        _playwright = None


async def browser_get(url: str, timeout: int = 20, challenge_wait: int = 40) -> tuple[int, str]:
    """실제 브라우저(Firefox)로 JS를 실행해 Cloudflare 챌린지를 통과한 뒤 HTML을 가져온다.

    curl_cffi(TLS/HTTP2 핑거프린트 흉내)로는 못 뚫는 "Just a moment..." 류의 JS 챌린지가
    걸린 사이트(zod)용. 챌린지는 클라이언트 사이드에서 자동으로 풀리는 경우가 많아 페이지
    타이틀이 챌린지 문구에서 벗어날 때까지 기다리고(내비게이션 타임아웃보다 넉넉하게),
    체크박스 클릭이 필요한 Turnstile 위젯이면 최선을 다해 클릭도 시도한다(닫힌 shadow DOM
    안에 있어 대부분 실패하지만, 되는 경우도 있어 시도 자체는 해본다).
    """
    context = await _get_context()
    page = await context.new_page()
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        status = response.status if response else 0

        title = await page.title()
        if any(marker in title for marker in _CHALLENGE_TITLE_MARKERS):
            try:
                await page.frame_locator("iframe[src*='challenges.cloudflare.com']").locator(
                    "input[type=checkbox]"
                ).click(timeout=3000)
                logger.info("clicked a Turnstile checkbox for %s", url)
            except Exception:
                pass

        for _ in range(int(challenge_wait)):
            title = await page.title()
            if not any(marker in title for marker in _CHALLENGE_TITLE_MARKERS):
                break
            await page.wait_for_timeout(1000)
        else:
            logger.info("challenge for %s did not clear within %ds", url, challenge_wait)

        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        html = await page.content()
    finally:
        await page.close()

    # 챌린지 통과 실패는 원본 상태코드와 무관하게 최종 렌더링 내용으로 판단한다
    # (Cloudflare가 자체적으로 403을 주는 경우도, 200으로 챌린지 페이지만 계속 보여주는
    # 경우도 있다). 그 외(진짜 404 포함)에는 실제 내비게이션 응답 상태코드를 그대로 쓴다.
    if any(marker in html for marker in _BLOCK_MARKERS):
        logger.warning(
            "playwright still blocked for %s (nav status=%s, title=%r, len=%d)",
            url, status, title, len(html),
        )
        return 403, html
    logger.info("playwright fetched %s (status=%s, title=%r, len=%d)", url, status, title, len(html))
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
