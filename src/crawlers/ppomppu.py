from __future__ import annotations

from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from ..models import Article, ArticleStatus
from ..price import extract_mall, extract_price
from .base import DEFAULT_HEADERS, BaseCrawler
from .registry import register_crawler

BASE_URL = "https://www.ppomppu.co.kr/zboard/"
LIST_URL = BASE_URL + "zboard.php?id=ppomppu&page={page}"
NOT_FOUND_MARKER = "존재하지 않습니다"


@register_crawler("ppomppu")
class PpomppuCrawler(BaseCrawler):
    async def fetch(self) -> list[Article]:
        articles: list[Article] = []
        pages = self.crawl_config.listing_pages
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
            for page in range(1, pages + 1):
                html = await _get_text(session, LIST_URL.format(page=page))
                articles.extend(_parse_listing(html))
        return articles

    async def check_exists(self, article_url: str) -> bool:
        try:
            async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
                html = await _get_text(session, article_url)
        except Exception:
            return True
        return NOT_FOUND_MARKER not in html


async def _get_text(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        raw = await resp.read()
    return raw.decode("cp949", errors="replace")


def _parse_listing(html: str) -> list[Article]:
    soup = BeautifulSoup(html, "lxml")
    articles: list[Article] = []

    for row in soup.select("tr.baseList.bbs_new1"):
        numb_td = row.select_one("td.baseList-numb")
        title_a = row.select_one("a.baseList-title")
        if not numb_td or not title_a:
            continue

        article_id = numb_td.get_text(strip=True)
        if not article_id.isdigit():
            continue

        title = title_a.get_text(strip=True)
        url = urljoin(BASE_URL, title_a["href"])

        classes = title_a.get("class", [])
        status = ArticleStatus.ENDED if any("end" in c for c in classes) else ArticleStatus.ACTIVE

        thumbnail_url = None
        thumb_a = row.select_one("a.baseList-thumb")
        if thumb_a:
            # tooltip 속성에 원본 이미지(P_img://...)가 들어있어, 목록용 저화질
            # small_*.jpg 썸네일보다 훨씬 화질이 좋다. 없으면 저화질로 대체한다.
            tooltip = thumb_a.get("tooltip", "")
            if tooltip.startswith("P_img://"):
                thumbnail_url = "https://" + tooltip[len("P_img://") :]
            else:
                thumb_img = thumb_a.select_one("img")
                if thumb_img and thumb_img.get("src") and "noimage" not in thumb_img["src"]:
                    thumbnail_url = urljoin("https://cdn3.ppomppu.co.kr", thumb_img["src"])

        rec_td = row.select_one("td.baseList-rec")
        likes = None
        if rec_td:
            rec_text = rec_td.get_text(strip=True)
            first_part = rec_text.split("-")[0].strip()
            if first_part.isdigit():
                likes = int(first_part)

        category_tag = row.select_one(".baseList-small")
        category = category_tag.get_text(strip=True).strip(" []") if category_tag else None

        articles.append(
            Article(
                site="ppomppu",
                article_id=article_id,
                title=title,
                url=url,
                price=extract_price(title),
                likes=likes,
                thumbnail_url=thumbnail_url,
                category=category or None,
                mall=extract_mall(title),
                status=status,
            )
        )

    return articles
