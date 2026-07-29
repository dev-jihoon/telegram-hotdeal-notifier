from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Article, ArticleStatus
from ..price import extract_mall, extract_price
from .base import BaseCrawler
from .browser import browser_get
from .cf_bypass import cf_get
from .registry import register_crawler

BASE_URL = "https://damoang.net"
LIST_URL = BASE_URL + "/economy?page={page}"
ARTICLE_ID_RE = re.compile(r"/(\d+)$")
STATUS_MAP = {"종료": ArticleStatus.ENDED, "품절": ArticleStatus.SOLDOUT}


async def _get(fetch_method: str, url: str) -> tuple[int, str]:
    if fetch_method == "playwright":
        return await browser_get(url)
    return await cf_get(url)


@register_crawler("damoang")
class DamoangCrawler(BaseCrawler):
    async def fetch(self) -> list[Article]:
        articles: list[Article] = []
        for page in range(1, self.crawl_config.listing_pages + 1):
            status, html = await _get(self.site_config.fetch_method, LIST_URL.format(page=page))
            if status != 200:
                continue
            articles.extend(_parse_listing(html))
        return articles

    async def check_exists(self, article_url: str) -> bool:
        # Cloudflare 우회가 일시적으로 실패하는 경우(403 등)를 삭제로 오판하지 않도록
        # 404만 확정 삭제로 본다.
        try:
            status, _ = await _get(self.site_config.fetch_method, article_url)
        except Exception:
            return True
        return status != 404


def _parse_listing(html: str) -> list[Article]:
    soup = BeautifulSoup(html, "lxml")
    articles: list[Article] = []

    for row in soup.select("a.post-row"):
        href = row.get("href")
        if not href:
            continue
        match = ARTICLE_ID_RE.search(href)
        if not match:
            continue
        article_id = match.group(1)

        title_span = row.select_one("span.post-title")
        if not title_span:
            continue
        title = title_span.get("title") or title_span.get_text(strip=True)
        if not title:
            continue

        status = ArticleStatus.ACTIVE
        for span in row.select("span"):
            text = span.get_text(strip=True)
            if text in STATUS_MAP:
                status = STATUS_MAP[text]
                break

        likes = None
        likes_div = row.select_one("div.flex.min-h-5")
        if likes_div:
            text = likes_div.get_text(strip=True)
            if text.isdigit():
                likes = int(text)

        # 데스크톱 메타 영역의 첫 항목이 가격인 경우가 많지만, 상점명 등
        # 다른 텍스트가 오는 경우도 있어 "원"이 포함된 경우만 신뢰한다.
        price = None
        meta_spans = row.select("span.post-meta-text")
        if meta_spans:
            candidate = meta_spans[0].get_text(strip=True)
            if "원" in candidate:
                price = candidate
        if price is None:
            price = extract_price(title)

        articles.append(
            Article(
                site="damoang",
                article_id=article_id,
                title=title,
                url=BASE_URL + href,
                price=price,
                likes=likes,
                thumbnail_url=None,
                mall=extract_mall(title),
                status=status,
            )
        )

    return articles
