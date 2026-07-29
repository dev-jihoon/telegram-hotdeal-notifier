from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from bs4 import BeautifulSoup

from ..models import Article, ArticleStatus
from .base import DEFAULT_HEADERS, BaseCrawler
from .registry import register_crawler

BASE_URL = "https://arca.live"
LIST_URL = BASE_URL + "/b/hotdeal?p={page}"
ARTICLE_RE = re.compile(r"/b/([\w\d]+)/(\d+)")


async def _get(url: str) -> tuple[int, str]:
    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            return resp.status, await resp.text(errors="replace")


@register_crawler("arcalive")
class ArcaLiveCrawler(BaseCrawler):
    async def fetch(self) -> list[Article]:
        articles: list[Article] = []
        for page in range(1, self.crawl_config.listing_pages + 1):
            status, html = await _get(LIST_URL.format(page=page))
            if status != 200:
                continue
            articles.extend(_parse_listing(html))
        return articles

    async def check_exists(self, article_url: str) -> bool:
        # 일시적 오류(403 등)를 삭제로 오판하지 않도록 404만 확정 삭제로 본다.
        try:
            status, _ = await _get(article_url)
        except Exception:
            return True
        return status != 404


def _parse_listing(html: str) -> list[Article]:
    soup = BeautifulSoup(html, "lxml")
    articles: list[Article] = []

    table = soup.select_one(".list-table")
    if table is None:
        return articles

    for row in table.select(".vrow.hybrid"):
        title_tag = row.select_one("a.title.hybrid-title")
        if not title_tag or not title_tag.get("href"):
            continue
        match = ARTICLE_RE.search(title_tag["href"])
        if not match:
            continue
        board_id, article_id = match.group(1), match.group(2)

        title = "".join(title_tag.find_all(string=True, recursive=False)).strip()
        if not title:
            continue

        status = ArticleStatus.ENDED if row.select_one(".deal-close") else ArticleStatus.ACTIVE

        likes = None
        rate_tag = row.select_one(".col-rate")
        if rate_tag:
            text = rate_tag.get_text(strip=True)
            if text.lstrip("-").isdigit():
                likes = int(text)

        price_tag = row.select_one(".deal-price")
        price = price_tag.get_text(strip=True) if price_tag else None

        delivery_tag = row.select_one(".deal-delivery")
        delivery = delivery_tag.get_text(strip=True) if delivery_tag else None

        mall_tag = row.select_one(".deal-store")
        mall = mall_tag.get_text(strip=True) if mall_tag else None

        thumb_tag = row.select_one(".vrow-preview img")
        thumbnail_url = None
        if thumb_tag and thumb_tag.get("src"):
            src = thumb_tag["src"]
            thumbnail_url = f"https:{src}" if src.startswith("//") else src
            thumbnail_url = _drop_list_size(thumbnail_url)

        category_tag = row.select_one(".badge")
        category = category_tag.get_text(strip=True) if category_tag else None

        articles.append(
            Article(
                site="arcalive",
                article_id=article_id,
                title=title,
                url=f"{BASE_URL}/b/{board_id}/{article_id}",
                price=price,
                likes=likes,
                thumbnail_url=thumbnail_url,
                category=category,
                mall=mall,
                delivery=delivery,
                status=status,
            )
        )

    return articles


def _drop_list_size(url: str) -> str:
    """썸네일 CDN URL의 'type=list'(저화질 목록용) 파라미터를 제거해 원본 화질을 받는다."""
    parts = urlsplit(url)
    query = "&".join(p for p in parts.query.split("&") if not p.startswith("type="))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
