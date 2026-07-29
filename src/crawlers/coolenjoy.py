from __future__ import annotations

import re

import aiohttp
from bs4 import BeautifulSoup

from ..models import Article, ArticleStatus
from ..price import extract_mall, extract_price
from .base import DEFAULT_HEADERS, BaseCrawler
from .registry import register_crawler

BASE_URL = "https://coolenjoy.net"
LIST_URL = BASE_URL + "/bbs/jirum?page={page}"
ARTICLE_ID_RE = re.compile(r"/jirum/(\d+)")
END_KEYWORDS = ("품절", "종료", "매진", "마감")


async def _get(url: str) -> tuple[int, str]:
    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            return resp.status, await resp.text(errors="replace")


@register_crawler("coolenjoy")
class CoolenjoyCrawler(BaseCrawler):
    async def fetch(self) -> list[Article]:
        articles: list[Article] = []
        for page in range(1, self.crawl_config.listing_pages + 1):
            status, html = await _get(LIST_URL.format(page=page))
            if status != 200:
                continue
            articles.extend(_parse_listing(html))
        return articles

    async def check_exists(self, article_url: str) -> bool:
        # 코올엔조이는 IP 차단 시 200으로 안내 문구를 보여주는데, 그 문구는 확인된 삭제
        # 마커가 아니므로 확실한 404일 때만 삭제로 본다 (그 외엔 존재한다고 가정).
        try:
            status, _ = await _get(article_url)
        except Exception:
            return True
        return status != 404


def _parse_listing(html: str) -> list[Article]:
    soup = BeautifulSoup(html, "lxml")
    articles: list[Article] = []

    for row in soup.select("li.d-md-table-row"):
        link = row.select_one("a.na-subject")
        if not link or not link.get("href"):
            continue
        href = link["href"]
        match = ARTICLE_ID_RE.search(href)
        if not match:
            continue
        article_id = match.group(1)

        title = link.get_text(strip=True)
        if not title:
            continue

        status = ArticleStatus.ACTIVE
        for kw in END_KEYWORDS:
            if kw in title:
                status = ArticleStatus.ENDED
                break

        likes = None
        vote_tag = row.select_one(".rank-icon_vote")
        if vote_tag:
            text = vote_tag.get_text(strip=True)
            if text.isdigit():
                likes = int(text)

        # 가격은 구조화된 태그(font[color])로 표시되는 경우가 많고, 없으면
        # 제목에서 정규식으로 추출한 값을 대신 사용한다.
        price = None
        price_tag = row.select_one("font[color]")
        if price_tag:
            text = price_tag.get_text(strip=True)
            if "원" in text:
                price = text
        if price is None:
            price = extract_price(title)

        category_tag = row.select_one("#abcd")
        category = category_tag.get_text(strip=True) if category_tag else None

        articles.append(
            Article(
                site="coolenjoy",
                article_id=article_id,
                title=title,
                url=f"{BASE_URL}/bbs/jirum/{article_id}",
                price=price,
                likes=likes,
                thumbnail_url=None,
                category=category,
                mall=extract_mall(title),
                status=status,
            )
        )

    return articles
