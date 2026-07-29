from __future__ import annotations

import asyncio
import html
import logging
import time
from collections import defaultdict
from typing import Awaitable, Callable, TypeVar

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TelegramError, TimedOut

from .image_processing import fetch_letterboxed
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
    # 가격은 대부분 게시글 제목에 이미 포함돼 있어(제목 굵은 글씨로 표시) 중복 표시하지 않는다.
    site_label = SITE_LABELS.get(article.site, article.site)
    prefix = f"[{site_label}]"
    if article.mall and article.mall != article.category:
        prefix += f"[{html.escape(article.mall, quote=False)}]"
    if article.category:
        prefix += f"[{html.escape(article.category, quote=False)}]"
    lines = [f"<b>{prefix} {html.escape(article.title, quote=False)}</b>"]

    if article.delivery:
        lines.append(f"🚚 {html.escape(article.delivery, quote=False)}")

    text = "\n".join(lines)

    status_label = _STATUS_LABEL.get(article.status)
    if status_label:
        text = f"{status_label}\n<s>{text}</s>"

    return text


def build_markup(article: Article, webapp_link: str | None = None) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton("바로가기", url=article.url)]
    if webapp_link:
        # 채널/그룹 인라인 버튼은 텔레그램 정책상 web_app 타입을 못 쓰므로, BotFather에
        # 등록한 Mini App 짧은 이름으로 만든 t.me 딥링크(일반 url 버튼)를 사용한다.
        # 이 링크는 텔레그램 클라이언트가 특별 처리해서 진짜 미니앱으로 열어준다.
        buttons.append(InlineKeyboardButton("🔥 인기 핫딜", url=webapp_link))
    return InlineKeyboardMarkup([buttons])


async def _with_flood_retry(func: Callable[[], Awaitable[T]], max_retries: int = 5) -> T:
    """RetryAfter(플러드 컨트롤)나 일시적인 연결 풀 타임아웃을 만나면 잠깐 쉬었다가 재시도한다."""
    for attempt in range(max_retries):
        try:
            return await func()
        except RetryAfter as e:
            wait = e.retry_after + 1
            logger.warning("Telegram flood control hit, sleeping %.1fs (attempt %d)", wait, attempt + 1)
            await asyncio.sleep(wait)
        except TimedOut:
            wait = 2 * (attempt + 1)
            logger.warning("Telegram request timed out, retrying in %.1fs (attempt %d)", wait, attempt + 1)
            await asyncio.sleep(wait)
    return await func()


class TelegramNotifier:
    def __init__(self, bot: Bot, webapp_link: str | None = None):
        self._bot = bot
        self._limiter = RateLimiter()
        self._webapp_link = webapp_link

    async def send(self, article: Article, chat_id: int) -> tuple[int, bool]:
        """새 글을 전송하고 (message_id, has_photo)를 반환한다."""
        text = format_message(article)
        markup = build_markup(article, self._webapp_link)

        if article.thumbnail_url:
            # 세로/정사각형 썸네일이 많아 메시지 높이가 들쭉날쭉해지는 걸 막기 위해
            # 16:9 캔버스(블러 배경 + 중앙 배치)로 정규화한 뒤 파일로 업로드한다.
            # 처리에 실패하면 원본 URL을 그대로 쓰는 쪽으로 폴백한다.
            photo_bytes = await fetch_letterboxed(article.thumbnail_url)

            def _make_photo():
                # 재시도마다 새 InputFile을 만들어야 안전하다 (bytes 스트림 재사용 문제 방지)
                return InputFile(photo_bytes, filename="thumb.jpg") if photo_bytes else article.thumbnail_url

            await self._limiter.wait(chat_id)
            try:
                message = await _with_flood_retry(
                    lambda: self._bot.send_photo(
                        chat_id=chat_id,
                        photo=_make_photo(),
                        caption=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=markup,
                    )
                )
                return message.message_id, True
            except TelegramError:
                # 썸네일을 텔레그램이 못 받는 경우 텍스트로 폴백
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
        markup = build_markup(article, self._webapp_link)
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

    async def send_digest_text(self, chat_id: int, text: str) -> None:
        """다이제스트 요약 텍스트를 전송한다.

        web_app 인라인 버튼은 텔레그램 정책상 1:1 채팅에서만 허용되고 채널/그룹에서는
        거부되므로, 채널 방송용으로는 일반 URL 버튼(t.me 딥링크 또는 그냥 https 링크)을 쓴다.
        """
        markup = None
        if self._webapp_link:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("📱 웹에서 더보기", url=self._webapp_link)]])

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
