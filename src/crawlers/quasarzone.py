from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ..models import Article, ArticleStatus
from .base import BaseCrawler
from .cf_bypass import cf_get
from .registry import register_crawler

BASE_URL = "https://quasarzone.com"
LIST_URL = BASE_URL + "/bbs/qb_saleinfo?page={page}"
ARTICLE_RE = re.compile(r"/bbs/([\w\d_]+)/views/(\d+)")


@register_crawler("quasarzone")
class QuasarzoneCrawler(BaseCrawler):
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

    table = soup.select_one(".market-info-type-list > table > tbody")
    if table is None:
        return articles

    for row in table.select("tr"):
        link = row.select_one(".subject-link")
        if not link or not link.get("href"):
            continue
        match = ARTICLE_RE.search(link["href"])
        if not match:
            continue
        board_id, article_id = match.group(1), match.group(2)

        title_tag = row.select_one(".ellipsis-with-reply-cnt")
        if not title_tag or not title_tag.get_text(strip=True):
            continue
        title = title_tag.get_text(strip=True)

        label = row.select_one("p.tit .label")
        status = (
            ArticleStatus.ENDED
            if label and label.get_text(strip=True) == "종료"
            else ArticleStatus.ACTIVE
        )

        likes = None
        num_tag = row.select_one("td .num")
        if num_tag:
            text = num_tag.get_text(strip=True)
            if text.lstrip("-").isdigit():
                likes = int(text)

        price = _extract_price(row)

        category_tag = row.select_one(".market-info-sub .category")
        category = category_tag.get_text(strip=True) if category_tag else None

        thumb = row.select_one(".thumb-wrap img")
        thumbnail_url = thumb.get("src") if thumb and thumb.get("src") else None

        articles.append(
            Article(
                site="quasarzone",
                article_id=article_id,
                title=title,
                url=f"{BASE_URL}/bbs/{board_id}/views/{article_id}",
                price=price,
                likes=likes,
                thumbnail_url=thumbnail_url,
                category=category,
                status=status,
            )
        )

    return articles


def _extract_price(row: Tag) -> str | None:
    info = row.select_one(".market-info-sub p:first-child")
    if not info:
        return None
    for span in info.find_all("span", recursive=False):
        first_text = span.find(string=True, recursive=False)
        if first_text and first_text.strip() == "가격":
            price_span = span.find("span")
            if price_span:
                return price_span.get_text(strip=True)
    return None
