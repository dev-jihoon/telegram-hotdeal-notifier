from __future__ import annotations

import asyncio
import html
import logging
import time
from collections import defaultdict
from typing import Awaitable, Callable, TypeVar

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TelegramError

from .models import Article, ArticleStatus

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


def format_message(article: Article) -> str:
    site_label = SITE_LABELS.get(article.site, article.site)
    prefix = f"[{site_label}]"
    if article.category:
        prefix += f"[{html.escape(article.category, quote=False)}]"
    lines = [f"<b>{prefix} {html.escape(article.title, quote=False)}</b>"]
    if article.price:
        lines.append(f"💰 {html.escape(article.price, quote=False)}")
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

    async def edit(self, article: Article, chat_id: int, message_id: int, has_photo: bool) -> None:
        text = format_message(article)
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
