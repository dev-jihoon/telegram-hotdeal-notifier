from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from .config import Config, DisplayConfig
from .db import Database
from .models import Article, ArticleStatus
from .price import parse_won
from .sync import sync_webhook_listing
from .telegram_notifier import SITE_LABELS, TelegramNotifier
from .time_utils import start_of_today_kst_iso

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
INIT_DATA_MAX_AGE_SECONDS = 24 * 3600
DEALS_LIMIT = 50


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = INIT_DATA_MAX_AGE_SECONDS) -> bool:
    """텔레그램 미니앱의 initData가 실제로 이 봇에서 발급됐는지 검증한다.

    공식 알고리즘: https://core.telegram.org/bots/webapps#validating-data-received-via-the-web-app
    """
    if not init_data:
        return False
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return False

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return False

    auth_date = pairs.get("auth_date")
    if auth_date:
        try:
            if time.time() - int(auth_date) > max_age_seconds:
                return False
        except ValueError:
            return False

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_hash, received_hash)


def _serialize(article, old_price: str | None, show_site_name: bool) -> dict:
    discount_pct = None
    if old_price and article.price:
        old_won = parse_won(old_price)
        new_won = parse_won(article.price)
        if old_won and new_won and new_won < old_won:
            discount_pct = round((old_won - new_won) / old_won * 100)
    return {
        "site": article.site,
        "site_label": SITE_LABELS.get(article.site, article.site) if show_site_name else None,
        "title": article.title,
        "url": article.url,
        "price": article.price,
        "likes": article.likes,
        "thumbnail_url": article.thumbnail_url,
        "category": article.category,
        "mall": article.mall,
        "delivery": article.delivery,
        "discount_pct": discount_pct,
    }


def _article_from_payload(site: str, data: dict) -> Article:
    status_raw = (data.get("status") or "active").lower()
    status = {
        "active": ArticleStatus.ACTIVE,
        "ended": ArticleStatus.ENDED,
        "soldout": ArticleStatus.SOLDOUT,
    }.get(status_raw, ArticleStatus.ACTIVE)
    return Article(
        site=site,
        article_id=str(data["article_id"]),
        title=data["title"],
        url=data["url"],
        price=data.get("price"),
        likes=data.get("likes"),
        thumbnail_url=data.get("thumbnail_url"),
        category=data.get("category"),
        mall=data.get("mall"),
        delivery=data.get("delivery"),
        status=status,
    )


def create_app(
    db: Database, bot_token: str, display: DisplayConfig, config: Config, notifier: TelegramNotifier
) -> web.Application:
    app = web.Application(client_max_size=4 * 1024 * 1024)

    async def index(request: web.Request) -> web.Response:
        return web.FileResponse(STATIC_DIR / "index.html")

    async def api_deals(request: web.Request) -> web.Response:
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        if not validate_init_data(init_data, bot_token):
            return web.json_response({"error": "invalid init data"}, status=403)

        # 자정을 걸치는 롤링 24시간이 아니라, 달력상 오늘(KST) 올라온 글만 대상으로 한다.
        cutoff = start_of_today_kst_iso()
        articles = await db.get_top_articles_since(cutoff, DEALS_LIMIT)
        old_prices = await db.get_latest_old_prices([(a.site, a.article_id) for a in articles])
        deals = [
            _serialize(a, old_prices.get((a.site, a.article_id)), display.show_site_name)
            for a in articles
        ]
        return web.json_response({
            "deals": deals,
            "meta": {
                "title": display.webapp_title,
                "empty_message": display.webapp_empty_message,
            },
        })

    def _check_webhook_auth(request: web.Request) -> web.Response | None:
        if not config.webhook.enabled or not config.webhook.secret:
            return web.json_response({"error": "webhook disabled"}, status=404)
        provided = request.headers.get("X-Webhook-Secret", "")
        if not hmac.compare_digest(provided, config.webhook.secret):
            return web.json_response({"error": "unauthorized"}, status=403)
        return None

    async def _touch_site_alive(site: str) -> None:
        # /status 패널이 웹훅 소스의 건강 상태도 같이 보여주도록, 폴링 크롤러와 같은
        # site_state.last_success_at을 갱신한다(하트비트/글 수신 둘 다 "살아있다"는 신호).
        await db.record_crawl_success(site, datetime.now(timezone.utc).isoformat())

    async def webhook_batch(request: web.Request) -> web.Response:
        """확장이 주기적으로(예: 1분마다) 다시 스크랩한 목록 전체를 받아 폴링 크롤러와
        동일한 신규/수정/삭제 판정을 거친다 - 최초 1회만 조용히 기준선을 잡고, 그 뒤로는
        매번 이 판정을 다시 거친다 (한 번 부트스트랩됐다고 끝나는 게 아니다)."""
        auth_error = _check_webhook_auth(request)
        if auth_error:
            return auth_error
        site = request.match_info["site"]
        if not await db.get_site_enabled(site):
            return web.json_response({"status": "site disabled, ignored"})
        try:
            data = await request.json()
            articles = [_article_from_payload(site, item) for item in data["articles"]]
        except Exception:
            return web.json_response({"error": "invalid payload"}, status=400)

        chat_id = config.sites[site].chat_id if site in config.sites and config.sites[site].chat_id else config.telegram.default_chat_id
        try:
            await sync_webhook_listing(db, notifier, site, chat_id, config.crawl, articles)
        except Exception:
            logger.exception("[%s] failed to sync webhook listing", site)
            return web.json_response({"error": "sync failed"}, status=500)
        await _touch_site_alive(site)
        return web.json_response({"status": "ok"})

    async def webhook_heartbeat(request: web.Request) -> web.Response:
        auth_error = _check_webhook_auth(request)
        if auth_error:
            return auth_error
        site = request.match_info["site"]
        await _touch_site_alive(site)
        return web.json_response({"status": "ok"})

    app.router.add_get("/", index)
    app.router.add_get("/api/deals", api_deals)
    app.router.add_post("/webhook/{site}/batch", webhook_batch)
    app.router.add_post("/webhook/{site}/heartbeat", webhook_heartbeat)
    app.router.add_static("/static/", STATIC_DIR)
    return app


async def start_webapp(
    db: Database, bot_token: str, port: int, display: DisplayConfig, config: Config, notifier: TelegramNotifier
) -> web.AppRunner:
    app = create_app(db, bot_token, display, config, notifier)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Mini app web server listening on :%d", port)
    return runner
