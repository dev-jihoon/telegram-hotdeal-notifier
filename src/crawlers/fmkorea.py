from __future__ import annotations

import aiohttp
from bs4 import BeautifulSoup

from ..models import Article, ArticleStatus
from ..price import extract_price
from .base import DEFAULT_HEADERS, BaseCrawler
from .registry import register_crawler

BASE_URL = "https://www.fmkorea.com"
LIST_URL = BASE_URL + "/hotdeal?page={page}"
END_KEYWORDS = ("품절", "종료", "매진", "마감")


@register_crawler("fmkorea")
class FmkoreaCrawler(BaseCrawler):
    async def fetch(self) -> list[Article]:
        articles: list[Article] = []
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
            for page in range(1, self.crawl_config.listing_pages + 1):
                url = LIST_URL.format(page=page)
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    html = await resp.text(errors="replace")
                articles.extend(_parse_listing(html))
        return articles

    async def check_exists(self, article_url: str) -> bool:
        # 에펨코리아는 자체 "보안 시스템"이 의심스러운 요청에 200이 아닌 커스텀 상태코드
        # (예: 430)를 돌려주는 경우가 있어, 확실한 404가 아니면 삭제로 판단하지 않는다.
        try:
            async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
                async with session.get(
                    article_url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status != 404
        except Exception:
            return True


def _parse_listing(html: str) -> list[Article]:
    soup = BeautifulSoup(html, "lxml")
    articles: list[Article] = []

    for row in soup.select("#content .fm_best_widget ul li"):
        title_h3 = row.select_one("h3.title")
        if not title_h3:
            continue
        title_link = title_h3.select_one("a")
        if not title_link or not title_link.get("href"):
            continue
        href = title_link["href"].lstrip("/")
        if not href.isdigit():
            continue
        article_id = href

        title_span = title_link.select_one(".ellipsis-target")
        if title_span:
            title = title_span.get_text(strip=True)
        else:
            text_node = title_link.find(string=True, recursive=False)
            title = (text_node or "").strip()
        if not title:
            continue

        status = ArticleStatus.ACTIVE
        for kw in END_KEYWORDS:
            if kw in title:
                status = ArticleStatus.ENDED
                break

        likes = None
        vote_tag = row.select_one(".pc_voted_count .count")
        if vote_tag:
            text = vote_tag.get_text(strip=True)
            if text.lstrip("-").isdigit():
                likes = int(text)

        price = None
        for span in row.select(".hotdeal_info span"):
            if "가격" in span.get_text():
                price_a = span.select_one("a")
                if price_a:
                    price = price_a.get_text(strip=True)
                break
        if price is None:
            price = extract_price(title)

        thumb_tag = row.select_one("img.thumb")
        thumbnail_url = None
        if thumb_tag:
            src = thumb_tag.get("data-original") or thumb_tag.get("src")
            if src and "transparent.gif" not in src:
                thumbnail_url = f"https:{src}" if src.startswith("//") else src

        category_tag = row.select_one(".category a")
        category = category_tag.get_text(strip=True) if category_tag else None

        articles.append(
            Article(
                site="fmkorea",
                article_id=article_id,
                title=title,
                url=f"{BASE_URL}/{article_id}",
                price=price,
                likes=likes,
                thumbnail_url=thumbnail_url,
                category=category,
                status=status,
            )
        )

    return articles
