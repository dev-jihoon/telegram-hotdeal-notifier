from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from .db import Database
from .price import parse_won
from .telegram_notifier import SITE_LABELS

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


def _serialize(article, old_price: str | None) -> dict:
    discount_pct = None
    if old_price and article.price:
        old_won = parse_won(old_price)
        new_won = parse_won(article.price)
        if old_won and new_won and new_won < old_won:
            discount_pct = round((old_won - new_won) / old_won * 100)
    return {
        "site": article.site,
        "site_label": SITE_LABELS.get(article.site, article.site),
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


def create_app(db: Database, bot_token: str) -> web.Application:
    app = web.Application()

    async def index(request: web.Request) -> web.Response:
        return web.FileResponse(STATIC_DIR / "index.html")

    async def api_deals(request: web.Request) -> web.Response:
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        if not validate_init_data(init_data, bot_token):
            return web.json_response({"error": "invalid init data"}, status=403)

        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        articles = await db.get_top_articles_since(cutoff, DEALS_LIMIT)
        old_prices = await db.get_latest_old_prices([(a.site, a.article_id) for a in articles])
        deals = [_serialize(a, old_prices.get((a.site, a.article_id))) for a in articles]
        return web.json_response({"deals": deals})

    app.router.add_get("/", index)
    app.router.add_get("/api/deals", api_deals)
    app.router.add_static("/static/", STATIC_DIR)
    return app


async def start_webapp(db: Database, bot_token: str, port: int) -> web.AppRunner:
    app = create_app(db, bot_token)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Mini app web server listening on :%d", port)
    return runner
