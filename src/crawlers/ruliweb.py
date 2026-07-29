from __future__ import annotations

import aiohttp
from bs4 import BeautifulSoup

from ..models import Article, ArticleStatus
from ..price import extract_mall, extract_price
from .base import DEFAULT_HEADERS, BaseCrawler
from .registry import register_crawler

BASE_URL = "https://bbs.ruliweb.com"
LIST_URL = BASE_URL + "/market/board/1020?page={page}"
END_KEYWORDS = ("품절", "종료", "매진", "마감")
NOT_FOUND_MARKER = "게시글이 없습니다"


@register_crawler("ruliweb")
class RuliwebCrawler(BaseCrawler):
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
        # 삭제/존재하지 않는 글은 200으로 "게시글이 없습니다" 안내 페이지를 보여준다.
        # 예전엔 실제 글 본문 컨테이너(#board_read)가 있는지로 판단했는데, 이건
        # "있어야 존재"라는 positive-signal 방식이라 네트워크 문제로 페이지가 일부만
        # 받아지는 등 어떤 이유로든 셀렉터가 안 걸리면 살아있는 글도 삭제로 오판하게
        # 된다. 확실한 마커 문구가 있을 때만 삭제로 보는 negative-signal 방식이 더 안전하다.
        try:
            async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
                async with session.get(
                    article_url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    # 일시적 오류(5xx, 429 등)를 삭제로 오판하지 않도록 404만 확정 삭제로 본다.
                    if resp.status == 404:
                        return False
                    if resp.status != 200:
                        return True
                    html = await resp.text(errors="replace")
        except Exception:
            return True
        return NOT_FOUND_MARKER not in html


def _parse_listing(html: str) -> list[Article]:
    soup = BeautifulSoup(html, "lxml")
    articles: list[Article] = []

    table = soup.select_one("table.board_list_table")
    if table is None:
        return articles

    rows = table.select("tr.table_body:not(.notice):not(.best):not(.inside)")
    for row in rows:
        id_td = row.select_one("td.id")
        if not id_td:
            continue
        article_id = id_td.get_text(strip=True)
        if not article_id.isdigit():
            continue

        link = row.select_one("a.subject_link")
        if not link or not link.get("href"):
            continue
        title_node = link.find(string=True, recursive=False)
        title = (title_node or link.get_text(strip=True)).strip()
        if not title:
            continue

        status = ArticleStatus.ACTIVE
        for kw in END_KEYWORDS:
            if kw in title:
                status = ArticleStatus.ENDED
                break

        likes = None
        rec_td = row.select_one("td.recomd")
        if rec_td:
            text = rec_td.get_text(strip=True)
            if text.lstrip("-").isdigit():
                likes = int(text)

        category_tag = row.select_one("td.divsn")
        category = category_tag.get_text(strip=True) if category_tag else None

        articles.append(
            Article(
                site="ruliweb",
                article_id=article_id,
                title=title,
                url=link["href"],
                category=category,
                mall=extract_mall(title),
                price=extract_price(title),
                likes=likes,
                thumbnail_url=None,
                status=status,
            )
        )

    return articles
