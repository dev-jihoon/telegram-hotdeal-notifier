from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Article, ArticleStatus
from .base import BaseCrawler
from .cf_bypass import cf_get
from .registry import register_crawler

BASE_URL = "https://zod.kr"
LIST_URL = BASE_URL + "/deal?page={page}"
ARTICLE_ID_RE = re.compile(r"/deal/(\d+)")
END_KEYWORDS = ("품절", "종료", "매진", "마감")


@register_crawler("zod")
class ZodCrawler(BaseCrawler):
    async def fetch(self) -> list[Article]:
        articles: list[Article] = []
        for page in range(1, self.crawl_config.listing_pages + 1):
            status, html = await cf_get(LIST_URL.format(page=page))
            if status != 200:
                continue
            articles.extend(_parse_listing(html))
        return articles

    async def check_exists(self, article_url: str) -> bool:
        try:
            status, _ = await cf_get(article_url)
        except Exception:
            return True
        return status == 200


def _parse_listing(html: str) -> list[Article]:
    soup = BeautifulSoup(html, "lxml")
    articles: list[Article] = []

    list_tag = soup.select_one("#board-list .zod-board-list--deal")
    if list_tag is None:
        return articles

    for row in list_tag.select("li"):
        link = row.select_one("a")
        if not link or not link.get("href"):
            continue
        href = link["href"]
        # 스폰서 위젯(deal_partner) 블록은 실제 유저 게시글이 아니므로 건너뛴다.
        if "deal_partner" in href:
            continue
        match = ARTICLE_ID_RE.search(href)
        if not match:
            continue
        article_id = match.group(1)

        title_tag = link.select_one(".app-list-title-item")
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title:
            continue

        row_classes = row.get("class") or []
        status = ArticleStatus.ACTIVE
        if "zod-board-list--deal-ended" in row_classes:
            status = ArticleStatus.ENDED
        else:
            for kw in END_KEYWORDS:
                if kw in title:
                    status = ArticleStatus.ENDED
                    break

        price = None
        for dd in link.select(".app-list-meta.zod-board--deal-meta dd"):
            text = dd.get_text(" ", strip=True)
            if "가격:" in text:
                strong = dd.select_one("strong")
                if strong:
                    price = strong.get_text(strip=True)
                break

        likes = None
        likes_tag = link.select_one(".app-list__voted-count")
        if likes_tag:
            text = likes_tag.get_text(strip=True)
            if text.isdigit():
                likes = int(text)

        thumb = link.select_one(".app-thumbnail img")
        thumbnail_url = thumb.get("src") if thumb and thumb.get("src") else None

        articles.append(
            Article(
                site="zod",
                article_id=article_id,
                title=title,
                url=f"{BASE_URL}/deal/{article_id}",
                price=price,
                likes=likes,
                thumbnail_url=thumbnail_url,
                status=status,
            )
        )

    return articles
