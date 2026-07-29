from __future__ import annotations

import aiohttp
from bs4 import BeautifulSoup

from ..models import Article, ArticleStatus
from ..price import extract_mall, extract_price
from .base import DEFAULT_HEADERS, BaseCrawler
from .registry import register_crawler

BASE_URL = "https://www.clien.net"
LIST_URL = BASE_URL + "/service/board/jirum"


async def _get(url: str) -> tuple[int, str]:
    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            return resp.status, await resp.text(errors="replace")


@register_crawler("clien")
class ClienCrawler(BaseCrawler):
    async def fetch(self) -> list[Article]:
        articles: list[Article] = []
        for page in range(self.crawl_config.listing_pages):
            url = LIST_URL if page == 0 else f"{LIST_URL}?po={page}"
            status, html = await _get(url)
            if status != 200:
                continue
            articles.extend(_parse_listing(html))
        return articles

    async def check_exists(self, article_url: str) -> bool:
        # 클리앙은 삭제/존재하지 않는 글에 확실한 404를 준다 (직접 확인함).
        try:
            status, _ = await _get(article_url)
        except Exception:
            return True
        return status != 404


def _parse_listing(html: str) -> list[Article]:
    soup = BeautifulSoup(html, "lxml")
    articles: list[Article] = []

    for row in soup.select(".list_content > .contents_jirum > .list_item.jirum"):
        article_id = row.get("data-board-sn")
        if not article_id:
            continue

        title_tag = row.select_one(".list_subject")
        if not title_tag:
            continue
        title = title_tag.get("title") or title_tag.get_text(strip=True)

        status = (
            ArticleStatus.SOLDOUT
            if "sold_out" in (row.get("class") or [])
            else ArticleStatus.ACTIVE
        )

        likes = None
        votes_tag = row.select_one(".list_votes")
        if votes_tag:
            digits = "".join(c for c in votes_tag.get_text(strip=True) if c.isdigit())
            if digits:
                likes = int(digits)

        thumb = row.select_one("img")
        thumbnail_url = None
        if thumb and thumb.get("src") and "noimage" not in thumb["src"]:
            thumbnail_url = thumb["src"]

        category_tag = row.select_one(".icon_keyword")
        category = category_tag.get_text(strip=True) if category_tag else None

        articles.append(
            Article(
                site="clien",
                article_id=article_id,
                title=title,
                url=f"{BASE_URL}/service/board/jirum/{article_id}",
                price=extract_price(title),
                likes=likes,
                thumbnail_url=thumbnail_url,
                category=category,
                mall=extract_mall(title),
                status=status,
            )
        )

    return articles
