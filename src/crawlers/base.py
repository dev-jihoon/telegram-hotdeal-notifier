from __future__ import annotations

import abc

import aiohttp

from ..config import CrawlConfig, SiteConfig
from ..models import Article

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


class BaseCrawler(abc.ABC):
    site_key: str

    def __init__(self, site_config: SiteConfig, crawl_config: CrawlConfig):
        self.site_config = site_config
        self.crawl_config = crawl_config

    @abc.abstractmethod
    async def fetch(self) -> list[Article]:
        """게시판 최신 글 목록을 가져온다."""
        ...

    async def check_exists(self, article_url: str) -> bool:
        """글이 아직 존재하는지 확인한다 (목록에서 사라진 글의 삭제 여부 판단용).

        기본 구현은 명확한 404만 "삭제됨"으로 판단한다. 그 외 응답(5xx, 429 등
        일시적 오류 포함)이나 네트워크 오류는 오탐(잘못된 삭제 처리)을 피하기 위해
        존재한다고 가정한다 - 삭제 페이지가 200으로 응답하며 별도 마커 텍스트를
        보여주는 사이트는 이 메서드를 오버라이드한다.
        """
        try:
            async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
                async with session.get(
                    article_url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status != 404
        except Exception:
            return True
