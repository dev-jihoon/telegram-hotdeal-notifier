from __future__ import annotations

from curl_cffi.requests import AsyncSession


async def cf_get(url: str, timeout: int = 15) -> tuple[int, str]:
    """Cloudflare 봇 챌린지가 걸린 사이트용 요청 헬퍼.

    일반 aiohttp 요청은 403으로 차단되지만, 브라우저의 TLS/HTTP2 핑거프린트를
    흉내내는 curl_cffi(impersonate="chrome")는 대부분 통과한다.
    """
    async with AsyncSession() as session:
        resp = await session.get(url, impersonate="chrome", timeout=timeout)
        return resp.status_code, resp.text
