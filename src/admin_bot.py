from __future__ import annotations

import logging
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from .db import Database
from .telegram_notifier import SITE_LABELS

logger = logging.getLogger(__name__)

TOGGLE_PREFIX = "toggle:"
REFRESH_STATUS = "refresh_status"


def _relative_time(iso_str: str | None) -> str:
    if not iso_str:
        return "기록 없음"
    then = datetime.fromisoformat(iso_str)
    now = datetime.now(timezone.utc)
    delta = now - then
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "방금 전"
    if seconds < 3600:
        return f"{seconds // 60}분 전"
    if seconds < 86400:
        return f"{seconds // 3600}시간 전"
    return f"{seconds // 86400}일 전"


class AdminBot:
    """관리자가 1:1 채팅에서 사이트별 on/off와 크롤링 현황을 확인/제어할 수 있게 한다."""

    def __init__(self, bot_token: str, admin_chat_id: int, db: Database, site_keys: list[str]):
        self._admin_chat_id = admin_chat_id
        self._db = db
        self._site_keys = site_keys
        self._app = Application.builder().token(bot_token).build()
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("sites", self._cmd_sites))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CallbackQueryHandler(self._on_toggle, pattern=f"^{TOGGLE_PREFIX}"))
        self._app.add_handler(CallbackQueryHandler(self._on_refresh_status, pattern=f"^{REFRESH_STATUS}$"))

    def _is_admin(self, update: Update) -> bool:
        chat = update.effective_chat
        return chat is not None and chat.id == self._admin_chat_id

    # ---- /start ------------------------------------------------------

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            return
        text = (
            "핫딜 알림 봇 관리자 메뉴입니다.\n\n"
            "/sites - 사이트별 크롤링 켜기/끄기\n"
            "/status - 사이트별 현황 (추적 글 수, 마지막 성공/실패)"
        )
        await update.message.reply_text(text)

    # ---- /sites --------------------------------------------------------

    async def _build_sites_menu(self) -> tuple[str, InlineKeyboardMarkup]:
        report = await self._db.get_site_report(self._site_keys)
        buttons = []
        for key in self._site_keys:
            info = report[key]
            icon = "✅" if info["enabled"] else "⛔"
            label = f"{icon} {SITE_LABELS.get(key, key)} ({info['tracked']})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"{TOGGLE_PREFIX}{key}")])
        text = "사이트별 크롤링 on/off (괄호는 추적 중인 글 수). 누르면 전환됩니다:"
        return text, InlineKeyboardMarkup(buttons)

    async def _cmd_sites(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            return
        text, markup = await self._build_sites_menu()
        await update.message.reply_text(text, reply_markup=markup)

    async def _on_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self._is_admin(update):
            await query.answer("권한이 없습니다.", show_alert=True)
            return

        site = query.data[len(TOGGLE_PREFIX):]
        current = await self._db.get_site_enabled(site)
        await self._db.set_site_enabled(site, not current)

        site_label = SITE_LABELS.get(site, site)
        await query.answer(f"{site_label} {'켜짐' if not current else '꺼짐'}")

        text, markup = await self._build_sites_menu()
        await query.edit_message_text(text, reply_markup=markup)

    # ---- /status ---------------------------------------------------------

    async def _build_status_text(self) -> str:
        report = await self._db.get_site_report(self._site_keys)
        lines = ["📊 사이트별 현황\n"]
        for key in self._site_keys:
            info = report[key]
            site_label = SITE_LABELS.get(key, key)
            icon = "✅" if info["enabled"] else "⛔"

            if not info["enabled"]:
                lines.append(f"{icon} {site_label} — 꺼짐")
                continue

            if info["last_error"]:
                status_line = f"⚠️ 실패 ({_relative_time(info['last_crawl_at'])}): {info['last_error'][:60]}"
            elif not info["bootstrapped"]:
                status_line = "⏳ 초기 수집 중"
            else:
                status_line = f"정상, 마지막 성공 {_relative_time(info['last_success_at'])}"

            lines.append(f"{icon} {site_label} — 추적 {info['tracked']}개 | {status_line}")

        return "\n".join(lines)

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            return
        text = await self._build_status_text()
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 새로고침", callback_data=REFRESH_STATUS)]])
        await update.message.reply_text(text, reply_markup=markup)

    async def _on_refresh_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self._is_admin(update):
            await query.answer("권한이 없습니다.", show_alert=True)
            return
        text = await self._build_status_text()
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 새로고침", callback_data=REFRESH_STATUS)]])
        try:
            await query.edit_message_text(text, reply_markup=markup)
        except Exception as e:
            if "message is not modified" in str(e).lower():
                pass
            else:
                raise
        await query.answer()

    async def start(self) -> None:
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("Admin bot polling started (/start, /sites, /status available to admin_chat_id)")

    async def stop(self) -> None:
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
