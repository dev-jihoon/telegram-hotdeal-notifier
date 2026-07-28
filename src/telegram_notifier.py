from __future__ import annotations

import asyncio
import html
import logging
import time
from collections import defaultdict
from typing import Awaitable, Callable, TypeVar

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TelegramError

from .models import Article, ArticleStatus
from .price import parse_won

logger = logging.getLogger(__name__)

T = TypeVar("T")

_STATUS_LABEL = {
    ArticleStatus.ENDED: "🚫 종료",
    ArticleStatus.SOLDOUT: "🚫 품절",
}

SITE_LABELS = {
    "ppomppu": "뽐뿌",
    "clien": "클리앙",
    "ruliweb": "루리웹",
    "arcalive": "아카라이브",
    "fmkorea": "에펨코리아",
    "coolenjoy": "쿨앤조이",
    "damoang": "다모앙",
    "quasarzone": "퀘이사존",
    "zod": "zod",
}


class RateLimiter:
    """chat_id별로 최소 간격을 두고 발송하기 위한 간단한 게이트."""

    def __init__(self, min_interval: float = 1.1):
        self._min_interval = min_interval
        self._last_sent: dict[int, float] = {}
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, chat_id: int) -> None:
        async with self._locks[chat_id]:
            last = self._last_sent.get(chat_id, 0.0)
            elapsed = time.monotonic() - last
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_sent[chat_id] = time.monotonic()


def _format_price_line(price: str, previous_price: str | None) -> str:
    escaped_price = html.escape(price, quote=False)
    if not previous_price or previous_price == price:
        return escaped_price

    old_won = parse_won(previous_price)
    new_won = parse_won(price)
    if old_won is None or new_won is None or new_won >= old_won or old_won == 0:
        return escaped_price

    discount_pct = round((old_won - new_won) / old_won * 100)
    escaped_old = html.escape(previous_price, quote=False)
    return f"<s>{escaped_old}</s> → {escaped_price} (-{discount_pct}%)"


def format_message(article: Article, previous_price: str | None = None) -> str:
    site_label = SITE_LABELS.get(article.site, article.site)
    prefix = f"[{site_label}]"
    if article.mall and article.mall != article.category:
        prefix += f"[{html.escape(article.mall, quote=False)}]"
    if article.category:
        prefix += f"[{html.escape(article.category, quote=False)}]"
    lines = [f"<b>{prefix} {html.escape(article.title, quote=False)}</b>"]

    if article.price:
        lines.append(f"💰 {_format_price_line(article.price, previous_price)}")
    if article.delivery:
        lines.append(f"🚚 {html.escape(article.delivery, quote=False)}")
    if article.likes is not None:
        lines.append(f"👍 추천 {article.likes}")

    text = "\n".join(lines)

    status_label = _STATUS_LABEL.get(article.status)
    if status_label:
        text = f"{status_label}\n<s>{text}</s>"

    return text


def build_markup(article: Article) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("바로가기", url=article.url)]])


async def _with_flood_retry(func: Callable[[], Awaitable[T]], max_retries: int = 5) -> T:
    """RetryAfter(플러드 컨트롤)를 만나면 텔레그램이 알려준 시간만큼 대기 후 재시도한다."""
    for attempt in range(max_retries):
        try:
            return await func()
        except RetryAfter as e:
            wait = e.retry_after + 1
            logger.warning("Telegram flood control hit, sleeping %.1fs (attempt %d)", wait, attempt + 1)
            await asyncio.sleep(wait)
    return await func()


class TelegramNotifier:
    def __init__(self, bot: Bot):
        self._bot = bot
        self._limiter = RateLimiter()

    async def send(self, article: Article, chat_id: int) -> tuple[int, bool]:
        """새 글을 전송하고 (message_id, has_photo)를 반환한다."""
        text = format_message(article)
        markup = build_markup(article)
        await self._limiter.wait(chat_id)

        if article.thumbnail_url:
            try:
                message = await _with_flood_retry(
                    lambda: self._bot.send_photo(
                        chat_id=chat_id,
                        photo=article.thumbnail_url,
                        caption=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=markup,
                    )
                )
                return message.message_id, True
            except TelegramError:
                # 썸네일 URL이 깨졌거나 텔레그램이 가져오지 못하는 경우 텍스트로 폴백
                await self._limiter.wait(chat_id)

        message = await _with_flood_retry(
            lambda: self._bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        )
        return message.message_id, False

    async def edit(
        self,
        article: Article,
        chat_id: int,
        message_id: int,
        has_photo: bool,
        previous_price: str | None = None,
    ) -> None:
        text = format_message(article, previous_price=previous_price)
        markup = build_markup(article)
        await self._limiter.wait(chat_id)

        try:
            if has_photo:
                await _with_flood_retry(
                    lambda: self._bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=message_id,
                        caption=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=markup,
                    )
                )
            else:
                await _with_flood_retry(
                    lambda: self._bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=markup,
                        disable_web_page_preview=True,
                    )
                )
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return
            raise

    async def delete(self, chat_id: int, message_id: int) -> None:
        await self._limiter.wait(chat_id)
        try:
            await _with_flood_retry(
                lambda: self._bot.delete_message(chat_id=chat_id, message_id=message_id)
            )
        except BadRequest as e:
            if "message to delete not found" in str(e).lower():
                return
            raise

    async def send_alert(self, chat_id: int, text: str) -> None:
        await self._limiter.wait(chat_id)
        await _with_flood_retry(lambda: self._bot.send_message(chat_id=chat_id, text=text))

    async def send_media_group(self, chat_id: int, articles: list[Article]) -> None:
        """다이제스트용: 썸네일이 있는 글들을 앨범(미디어그룹)으로 전송한다.

        미디어그룹 아이템에는 인라인 버튼을 못 붙이므로, 순위/제목만 짧게 캡션으로
        보여주고 실제 링크는 뒤따르는 텍스트 메시지가 담당한다.
        """
        media = []
        for i, article in enumerate(articles, start=1):
            if not article.thumbnail_url:
                continue
            site_label = SITE_LABELS.get(article.site, article.site)
            caption = f"{i}위 [{site_label}] {html.escape(article.title[:60], quote=False)}"
            media.append(
                InputMediaPhoto(media=article.thumbnail_url, caption=caption, parse_mode=ParseMode.HTML)
            )
        if not media:
            return

        await self._limiter.wait(chat_id)
        try:
            await _with_flood_retry(
                lambda: self._bot.send_media_group(chat_id=chat_id, media=media[:10])
            )
        except TelegramError:
            logger.warning("Failed to send digest media group, skipping album preview", exc_info=True)

    async def send_digest_text(self, chat_id: int, text: str, webapp_url: str | None = None) -> None:
        """다이제스트 요약 텍스트를 전송한다.

        web_app 인라인 버튼은 텔레그램 정책상 1:1 채팅에서만 허용되고 채널/그룹에서는
        거부되므로, 채널 방송용으로는 일반 URL 버튼을 사용한다.
        """
        markup = None
        if webapp_url:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("📱 웹에서 더보기", url=webapp_url)]])

        await self._limiter.wait(chat_id)
        await _with_flood_retry(
            lambda: self._bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        )
