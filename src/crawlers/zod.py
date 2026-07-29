from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Article, ArticleStatus
from .base import BaseCrawler
from .browser import get_with_fallback
from .cf_bypass import cf_get
from .registry import register_crawler

BASE_URL = "https://zod.kr"
LIST_URL = BASE_URL + "/deal?page={page}"
ARTICLE_ID_RE = re.compile(r"/deal/(\d+)")
END_KEYWORDS = ("품절", "종료", "매진", "마감")


async def _get(fetch_method: str, url: str) -> tuple[int, str]:
    # zod는 curl_cffi(TLS 흉내)로는 못 뚫는 Cloudflare JS 챌린지가 자주 걸려서, "requests"
    # 모드라도 차단이 감지되면 자동으로 playwright(실제 헤드리스 브라우저)로 폴백한다.
    # 기본 설정은 아예 처음부터 playwright로 시작해 그 첫 시도조차 아끼지만, config.yaml에
    # 이 필드가 없어 "requests"로 남아있어도 자동 폴백 덕분에 결국 playwright로 성공한다.
    return await get_with_fallback(fetch_method, url, cf_get)


@register_crawler("zod")
class ZodCrawler(BaseCrawler):
    async def fetch(self) -> list[Article]:
        articles: list[Article] = []
        for page in range(1, self.crawl_config.listing_pages + 1):
            status, html = await _get(self.site_config.fetch_method, LIST_URL.format(page=page))
            if status != 200:
                continue
            articles.extend(_parse_listing(html))
        return articles

    async def check_exists(self, article_url: str) -> bool:
        # 챌린지 페이지 자체는 절대 404를 주지 않으므로, 챌린지 통과 실패(403)를 삭제로
        # 오판하지 않도록 404만 확정 삭제로 본다.
        try:
            status, _ = await _get(self.site_config.fetch_method, article_url)
        except Exception:
            return True
        return status != 404


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
        mall = None
        delivery = None
        meta_list = link.select_one(".app-list-meta.zod-board--deal-meta")
        if meta_list:
            dts = meta_list.select("dt")
            dds = meta_list.select("dd")
            for dt, dd in zip(dts, dds):
                label = dt.get_text(strip=True)
                strong = dd.select_one("strong")
                value = strong.get_text(strip=True) if strong else dd.get_text(strip=True)
                if "홈페이지" in label or "장소" in label:
                    mall = value
                elif "가격" in label:
                    price = value
                elif "배송비" in label:
                    delivery = value

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
                mall=mall,
                delivery=delivery,
                status=status,
            )
        )

    return articles
