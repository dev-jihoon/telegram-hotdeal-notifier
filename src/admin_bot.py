from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from .db import Database
from .telegram_notifier import SITE_LABELS

logger = logging.getLogger(__name__)

CALLBACK_PREFIX = "toggle:"


class AdminBot:
    """관리자가 1:1 채팅에서 인라인 버튼으로 사이트별 크롤링을 켜고 끌 수 있게 한다."""

    def __init__(self, bot_token: str, admin_chat_id: int, db: Database, site_keys: list[str]):
        self._admin_chat_id = admin_chat_id
        self._db = db
        self._site_keys = site_keys
        self._app = Application.builder().token(bot_token).build()
        self._app.add_handler(CommandHandler("sites", self._cmd_sites))
        self._app.add_handler(CallbackQueryHandler(self._on_toggle, pattern=f"^{CALLBACK_PREFIX}"))

    def _is_admin(self, update: Update) -> bool:
        chat = update.effective_chat
        return chat is not None and chat.id == self._admin_chat_id

    async def _build_menu(self) -> tuple[str, InlineKeyboardMarkup]:
        states = await self._db.get_all_site_states()
        buttons = []
        for key in self._site_keys:
            enabled = states.get(key, True)
            label = f"{'✅' if enabled else '⛔'} {SITE_LABELS.get(key, key)}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"{CALLBACK_PREFIX}{key}")])
        return "사이트별 크롤링 on/off (누르면 전환됩니다):", InlineKeyboardMarkup(buttons)

    async def _cmd_sites(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            return
        text, markup = await self._build_menu()
        await update.message.reply_text(text, reply_markup=markup)

    async def _on_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self._is_admin(update):
            await query.answer("권한이 없습니다.", show_alert=True)
            return

        site = query.data[len(CALLBACK_PREFIX):]
        current = await self._db.get_site_enabled(site)
        await self._db.set_site_enabled(site, not current)

        site_label = SITE_LABELS.get(site, site)
        await query.answer(f"{site_label} {'켜짐' if not current else '꺼짐'}")

        text, markup = await self._build_menu()
        await query.edit_message_text(text, reply_markup=markup)

    async def start(self) -> None:
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("Admin bot polling started (/sites command available to admin_chat_id)")

    async def stop(self) -> None:
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
