from __future__ import annotations

import logging
from datetime import datetime, timezone

from telegram import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Config
from .db import AdminContact, Database
from .settings_registry import (
    CATEGORY_LABELS,
    SETTINGS,
    format_value,
    get_spec,
    parse_user_input,
    serialize,
)
from .telegram_notifier import SITE_LABELS

logger = logging.getLogger(__name__)

TOGGLE_PREFIX = "toggle:"
REFRESH_STATUS = "refresh_status"
SETTINGS_MENU = "settings_menu"
SETTINGS_CAT_PREFIX = "settings_cat:"
SETTINGS_EDIT_PREFIX = "settings_edit:"
SETTINGS_CANCEL = "settings_cancel"
ADMINS_MENU = "admins_menu"
ADMIN_DEL_PREFIX = "admin_del:"
ADMIN_ADD = "admin_add"
ADMIN_ADD_CANCEL = "admin_add_cancel"


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

    def __init__(
        self,
        bot_token: str,
        admin_chat_ids: list[int],
        db: Database,
        site_keys: list[str],
        config: Config,
        admin_contacts: list[AdminContact],
    ):
        self._admin_chat_ids = admin_chat_ids
        self._db = db
        self._site_keys = site_keys
        self._config = config
        # TelegramNotifier와 같은 리스트 객체를 공유한다 - 여기서 append/삭제하면(리스트를
        # 통째로 새로 안 만들고 그 자리에서 수정하면) 재시작 없이 다음 메시지부터 바로 반영된다.
        self._admin_contacts = admin_contacts
        # 텍스트로 답장받아야 하는 설정(문자열/숫자값)을 편집 중일 때, 그 설정 키를 들고
        # 있는다 - 다음 일반 메시지가 오면 이 값에 대한 답변으로 처리한다. 봇 인스턴스
        # 전체에서 공유되는 단순한 상태라, 관리자가 여러 명이면 동시에 서로 다른 편집을
        # 진행할 때 꼬일 수 있다(흔치 않은 상황이라 감수한다).
        self._pending_edit: str | None = None
        self._pending_admin_add = False
        self._app = (
            Application.builder()
            .token(bot_token)
            .connection_pool_size(8)
            .pool_timeout(30.0)
            .build()
        )
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("sites", self._cmd_sites))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("settings", self._cmd_settings))
        self._app.add_handler(CommandHandler("admins", self._cmd_admins))
        self._app.add_handler(CallbackQueryHandler(self._on_toggle, pattern=f"^{TOGGLE_PREFIX}"))
        self._app.add_handler(CallbackQueryHandler(self._on_refresh_status, pattern=f"^{REFRESH_STATUS}$"))
        self._app.add_handler(CallbackQueryHandler(self._on_settings_menu, pattern=f"^{SETTINGS_MENU}$"))
        self._app.add_handler(CallbackQueryHandler(self._on_settings_category, pattern=f"^{SETTINGS_CAT_PREFIX}"))
        self._app.add_handler(CallbackQueryHandler(self._on_settings_edit, pattern=f"^{SETTINGS_EDIT_PREFIX}"))
        self._app.add_handler(CallbackQueryHandler(self._on_settings_cancel, pattern=f"^{SETTINGS_CANCEL}$"))
        self._app.add_handler(CallbackQueryHandler(self._on_admins_menu, pattern=f"^{ADMINS_MENU}$"))
        self._app.add_handler(CallbackQueryHandler(self._on_admin_del, pattern=f"^{ADMIN_DEL_PREFIX}"))
        self._app.add_handler(CallbackQueryHandler(self._on_admin_add, pattern=f"^{ADMIN_ADD}$"))
        self._app.add_handler(CallbackQueryHandler(self._on_admin_add_cancel, pattern=f"^{ADMIN_ADD_CANCEL}$"))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text_reply))

    def _is_admin(self, update: Update) -> bool:
        # 콜백쿼리는 버튼이 달린 "메시지가 있는 채팅"이 아니라 실제로 누른 사람(from_user)을
        # 기준으로 판단해야 한다 - 메시지 자체는 항상 admin_chat_ids 중 하나의 1:1
        # 대화에서만 생성되지만, 신원 확인은 클릭한 사람 기준으로 하는 게 더 안전하다.
        if update.callback_query is not None:
            user = update.callback_query.from_user
            return user is not None and user.id in self._admin_chat_ids
        chat = update.effective_chat
        return chat is not None and chat.id in self._admin_chat_ids

    # ---- /start ------------------------------------------------------

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            return
        text = (
            "👋 핫딜 알림 봇 관리자 메뉴예요.\n\n"
            "/sites — 사이트별 크롤링 켜고 끄기\n"
            "/status — 실시간 현황 (추적 글 수, 마지막 성공/실패)\n"
            "/settings — 문구/다이제스트/크롤링 설정 편집 (재배포 없이 바로 적용)\n"
            "/admins — 메시지에 붙는 관리자 1:1 문의 버튼 추가/삭제\n\n"
            "메시지창에 '/'만 입력해도 명령어 목록이 바로 뜹니다."
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
        text = "🔧 사이트 관리\n켜고 싶은 사이트를 눌러주세요. 괄호 안 숫자는 현재 추적 중인 글 개수예요."
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
        lines = ["📊 실시간 현황\n"]
        for key in self._site_keys:
            info = report[key]
            site_label = SITE_LABELS.get(key, key)
            icon = "✅" if info["enabled"] else "⛔"

            if not info["enabled"]:
                lines.append(f"{icon} {site_label} — 꺼짐")
                continue

            if info["last_error"]:
                status_line = f"⚠️ 실패 ({_relative_time(info['last_crawl_at'])}) · {info['last_error'][:60]}"
            elif not info["bootstrapped"]:
                status_line = "⏳ 초기 수집 중"
            else:
                status_line = f"🟢 정상 · {_relative_time(info['last_success_at'])} 성공"

            lines.append(f"{icon} {site_label} — 추적 {info['tracked']}개 · {status_line}")

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

    # ---- /settings ---------------------------------------------------------

    def _build_settings_menu(self) -> tuple[str, InlineKeyboardMarkup]:
        text = "⚙️ 설정 편집\n바꾸고 싶은 항목의 카테고리를 골라주세요."
        buttons = [
            [InlineKeyboardButton(label, callback_data=f"{SETTINGS_CAT_PREFIX}{slug}")]
            for slug, label in CATEGORY_LABELS.items()
        ]
        return text, InlineKeyboardMarkup(buttons)

    def _build_category_menu(self, category: str) -> tuple[str, InlineKeyboardMarkup]:
        label = CATEGORY_LABELS.get(category, category)
        text = f"⚙️ {label}\n항목을 누르면 켜짐/꺼짐은 바로 토글되고, 글자/숫자값은 다음 메시지로 입력받습니다."
        buttons = []
        for spec in SETTINGS:
            if spec.category != category:
                continue
            value = format_value(spec, spec.get(self._config))
            buttons.append([
                InlineKeyboardButton(f"{spec.label}: {value}", callback_data=f"{SETTINGS_EDIT_PREFIX}{spec.key}")
            ])
        buttons.append([InlineKeyboardButton("◀️ 뒤로", callback_data=SETTINGS_MENU)])
        return text, InlineKeyboardMarkup(buttons)

    async def _cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            return
        self._pending_edit = None
        text, markup = self._build_settings_menu()
        await update.message.reply_text(text, reply_markup=markup)

    async def _on_settings_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self._is_admin(update):
            await query.answer("권한이 없습니다.", show_alert=True)
            return
        self._pending_edit = None
        text, markup = self._build_settings_menu()
        await query.edit_message_text(text, reply_markup=markup)
        await query.answer()

    async def _on_settings_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self._is_admin(update):
            await query.answer("권한이 없습니다.", show_alert=True)
            return
        category = query.data[len(SETTINGS_CAT_PREFIX):]
        text, markup = self._build_category_menu(category)
        await query.edit_message_text(text, reply_markup=markup)
        await query.answer()

    async def _on_settings_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self._is_admin(update):
            await query.answer("권한이 없습니다.", show_alert=True)
            return

        key = query.data[len(SETTINGS_EDIT_PREFIX):]
        spec = get_spec(key)
        if spec is None:
            await query.answer("알 수 없는 설정입니다.", show_alert=True)
            return

        if spec.type is bool:
            new_value = not spec.get(self._config)
            spec.set(self._config, new_value)
            await self._db.set_setting(spec.key, serialize(spec, new_value))
            await query.answer(f"{spec.label}: {format_value(spec, new_value)}")
            text, markup = self._build_category_menu(spec.category)
            await query.edit_message_text(text, reply_markup=markup)
            return

        self._pending_edit = key
        current = format_value(spec, spec.get(self._config))
        text = (
            f"✏️ {spec.label}\n현재 값: {current}\n\n다음 메시지로 새 값을 입력해주세요."
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ 취소", callback_data=SETTINGS_CANCEL)]])
        await query.edit_message_text(text, reply_markup=markup)
        await query.answer()

    async def _on_settings_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self._is_admin(update):
            await query.answer("권한이 없습니다.", show_alert=True)
            return
        category = None
        if self._pending_edit:
            spec = get_spec(self._pending_edit)
            category = spec.category if spec else None
        self._pending_edit = None
        if category:
            text, markup = self._build_category_menu(category)
        else:
            text, markup = self._build_settings_menu()
        await query.edit_message_text(text, reply_markup=markup)
        await query.answer("취소했습니다.")

    # ---- /admins ---------------------------------------------------------

    def _build_admins_menu(self) -> tuple[str, InlineKeyboardMarkup]:
        text = (
            "👤 관리자 문의 버튼\n각 핫딜 메시지 아래에 붙는 \"1:1 문의\" 버튼 목록입니다. "
            "버튼을 누르면 해당 관리자와의 텔레그램 1:1 채팅이 열립니다."
        )
        buttons = []
        for contact in self._admin_contacts:
            label = f"❌ {contact.label} (@{contact.username})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"{ADMIN_DEL_PREFIX}{contact.id}")])
        buttons.append([InlineKeyboardButton("➕ 추가", callback_data=ADMIN_ADD)])
        return text, InlineKeyboardMarkup(buttons)

    async def _cmd_admins(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            return
        self._pending_admin_add = False
        text, markup = self._build_admins_menu()
        await update.message.reply_text(text, reply_markup=markup)

    async def _on_admins_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self._is_admin(update):
            await query.answer("권한이 없습니다.", show_alert=True)
            return
        self._pending_admin_add = False
        text, markup = self._build_admins_menu()
        await query.edit_message_text(text, reply_markup=markup)
        await query.answer()

    async def _on_admin_del(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self._is_admin(update):
            await query.answer("권한이 없습니다.", show_alert=True)
            return
        contact_id = int(query.data[len(ADMIN_DEL_PREFIX):])
        await self._db.remove_admin_contact(contact_id)
        # 같은 리스트 객체를 TelegramNotifier와 공유하므로 통째로 재할당하지 않고 자리에서 수정한다.
        self._admin_contacts[:] = [c for c in self._admin_contacts if c.id != contact_id]
        await query.answer("삭제했습니다.")
        text, markup = self._build_admins_menu()
        await query.edit_message_text(text, reply_markup=markup)

    async def _on_admin_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self._is_admin(update):
            await query.answer("권한이 없습니다.", show_alert=True)
            return
        self._pending_admin_add = True
        text = (
            "✏️ 관리자 추가\n다음 메시지로 \"버튼에 표시할 문구|텔레그램 username\" 형식으로 "
            "답장해주세요.\n예: 📩 문의하기|dev_jihoon"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ 취소", callback_data=ADMIN_ADD_CANCEL)]])
        await query.edit_message_text(text, reply_markup=markup)
        await query.answer()

    async def _on_admin_add_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self._is_admin(update):
            await query.answer("권한이 없습니다.", show_alert=True)
            return
        self._pending_admin_add = False
        text, markup = self._build_admins_menu()
        await query.edit_message_text(text, reply_markup=markup)
        await query.answer("취소했습니다.")

    async def _on_text_reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            return

        if self._pending_admin_add:
            raw = update.message.text.strip()
            if "|" not in raw:
                await update.message.reply_text(
                    "형식이 안 맞습니다. \"문구|username\" 형태로 다시 보내주세요 (예: 📩 문의하기|dev_jihoon)."
                )
                return
            label, username = (part.strip() for part in raw.split("|", 1))
            username = username.lstrip("@")
            if not label or not username:
                await update.message.reply_text("문구와 username 둘 다 비어있으면 안 됩니다. 다시 보내주세요.")
                return
            contact_id = await self._db.add_admin_contact(label, username)
            self._admin_contacts.append(AdminContact(id=contact_id, label=label, username=username))
            self._pending_admin_add = False
            await update.message.reply_text(f"✅ 추가했습니다: {label} (@{username})")
            text, markup = self._build_admins_menu()
            await update.message.reply_text(text, reply_markup=markup)
            return

        if not self._pending_edit:
            return

        key = self._pending_edit
        spec = get_spec(key)
        if spec is None:
            self._pending_edit = None
            return

        try:
            value = parse_user_input(spec, update.message.text)
        except ValueError:
            await update.message.reply_text("숫자로 입력해주세요. 다시 시도하거나 취소해주세요.")
            return

        spec.set(self._config, value)
        await self._db.set_setting(spec.key, serialize(spec, value))
        self._pending_edit = None

        await update.message.reply_text(f"✅ {spec.label} → {format_value(spec, value)}")
        text, markup = self._build_category_menu(spec.category)
        await update.message.reply_text(text, reply_markup=markup)

    async def start(self) -> None:
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

        # 관리자 채팅에서만 '/'를 입력했을 때 명령어 목록이 뜨도록 스코프를 좁혀서 등록한다
        # (전역으로 등록하면 다른 사용자에게도 명령어 목록이 노출된다).
        commands = [
            BotCommand("start", "관리자 메뉴 안내"),
            BotCommand("sites", "사이트별 크롤링 켜기/끄기"),
            BotCommand("status", "실시간 현황 보기"),
            BotCommand("settings", "문구/다이제스트/크롤링 설정 편집"),
            BotCommand("admins", "관리자 1:1 문의 버튼 추가/삭제"),
        ]
        for chat_id in self._admin_chat_ids:
            try:
                await self._app.bot.set_my_commands(
                    commands, scope=BotCommandScopeChat(chat_id=chat_id)
                )
            except Exception:
                # 그 chat_id가 아직 봇과 1:1 대화를 시작(/start)하지 않았으면 텔레그램이
                # "chat not found"를 준다 - 명령어 자동완성만 못 뜨는 것뿐이고 실제 권한
                # 체크(_is_admin)와는 무관하니 그냥 건너뛴다.
                logger.warning("failed to register command scope for admin %s", chat_id, exc_info=True)
        logger.info(
            "Admin bot polling started (/start, /sites, /status, /settings, /admins available to %s)",
            self._admin_chat_ids,
        )

    async def stop(self) -> None:
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
