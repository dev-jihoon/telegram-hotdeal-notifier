from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ..models import Article, ArticleStatus
from ..price import extract_mall
from .base import BaseCrawler
from .browser import get_with_fallback
from .cf_bypass import cf_get
from .registry import register_crawler

BASE_URL = "https://quasarzone.com"
LIST_URL = BASE_URL + "/bbs/qb_saleinfo?page={page}"
ARTICLE_RE = re.compile(r"/bbs/([\w\d_]+)/views/(\d+)")
NOT_FOUND_MARKER = "글이 존재하지 않습니다"


async def _get(fetch_method: str, url: str) -> tuple[int, str]:
    # requests(curl_cffi) 모드에서 차단이 감지되면 자동으로 playwright로 폴백한다.
    return await get_with_fallback(fetch_method, url, cf_get)


@register_crawler("quasarzone")
class QuasarzoneCrawler(BaseCrawler):
    async def fetch(self) -> list[Article]:
        articles: list[Article] = []
        for page in range(1, self.crawl_config.listing_pages + 1):
            status, html = await _get(self.site_config.fetch_method, LIST_URL.format(page=page))
            if status != 200:
                continue
            articles.extend(_parse_listing(html))
        return articles

    async def check_exists(self, article_url: str) -> bool:
        # 삭제된 글도 HTTP 200을 반환하며 JS alert에 "글이 존재하지 않습니다" 문구를
        # 담아 보여준다. Cloudflare 우회가 일시적으로 실패하는 경우(403 등)를 삭제로
        # 오판하지 않도록 이 마커 문구나 404가 있을 때만 확정 삭제로 본다.
        try:
            status, body = await _get(self.site_config.fetch_method, article_url)
        except Exception:
            return True
        if status == 404:
            return False
        return NOT_FOUND_MARKER not in body


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

        price, delivery = _extract_price_and_delivery(row)

        category_tag = row.select_one(".market-info-sub .category")
        category = category_tag.get_text(strip=True) if category_tag else None

        thumb = row.select_one(".thumb-wrap img")
        thumbnail_url = None
        if thumb and thumb.get("src"):
            # 파일명의 'thumb_' 접두사를 떼면 같은 CDN에서 원본 화질 이미지를 받을 수 있다.
            src = thumb["src"]
            filename = src.rsplit("/", 1)[-1]
            if filename.startswith("thumb_"):
                src = src[: -len(filename)] + filename[len("thumb_") :]
            thumbnail_url = src

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
                mall=extract_mall(title),
                delivery=delivery,
                status=status,
            )
        )

    return articles


def _extract_price_and_delivery(row: Tag) -> tuple[str | None, str | None]:
    info = row.select_one(".market-info-sub p:first-child")
    if not info:
        return None, None

    price = None
    delivery = None
    for span in info.find_all("span", recursive=False):
        first_text = span.find(string=True, recursive=False)
        label = first_text.strip() if first_text else ""
        if label == "가격":
            price_span = span.find("span")
            if price_span:
                price = price_span.get_text(strip=True)
        elif label.startswith("배송비"):
            delivery = span.get_text(strip=True)[len("배송비") :].strip() or None
    return price, delivery
