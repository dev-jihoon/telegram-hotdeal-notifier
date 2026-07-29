from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import Bot, MenuButtonWebApp, WebAppInfo
from telegram.request import HTTPXRequest

from .admin_bot import AdminBot
from .config import Config, load_config
from .crawlers import load_all_crawlers
from .db import Database
from .digest import send_digest
from .singleton_lock import acquire_singleton_lock
from .sync import purge_expired, sync_site
from .telegram_notifier import SITE_LABELS, TelegramNotifier
from .webapp import start_webapp

KST = ZoneInfo("Asia/Seoul")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class FailureTracker:
    def __init__(self, threshold: int, realert_every: int):
        self._threshold = threshold
        self._realert_every = realert_every
        self._counts: dict[str, int] = {}

    def record_failure(self, site: str) -> bool:
        """실패를 기록하고, 이번에 알림을 보내야 하면 True를 반환한다."""
        count = self._counts.get(site, 0) + 1
        self._counts[site] = count
        if count == self._threshold:
            return True
        if count > self._threshold and (count - self._threshold) % self._realert_every == 0:
            return True
        return False

    def record_success(self, site: str) -> bool:
        """성공을 기록하고, 실패 상태에서 복구된 것이면 True를 반환한다."""
        had_failures = self._counts.get(site, 0) >= self._threshold
        self._counts[site] = 0
        return had_failures


async def run_site_loop(
    site_key: str,
    crawler,
    chat_id: int,
    interval: int,
    db: Database,
    notifier: TelegramNotifier,
    config: Config,
    failures: FailureTracker,
) -> None:
    site_label = SITE_LABELS.get(site_key, site_key)
    # 9개 사이트 루프가 전부 거의 같은 순간에 시작돼서 이후 사이클도 계속 같은 타이밍에
    # 몰린다 - 매 사이클 진짜 신규 글이 몇 개씩만 있어도 여러 사이트가 겹치면 순간적으로
    # 텔레그램에 한꺼번에 도착해서 "도배"처럼 보인다. 시작 시점만 무작위로 흩어두면 이후
    # 사이클도 계속 그 간격만큼 어긋난 채로 유지되어 자연스럽게 분산된다.
    await asyncio.sleep(random.uniform(0, interval))
    while True:
        if not await db.get_site_enabled(site_key):
            await asyncio.sleep(interval)
            continue
        now = datetime.now(timezone.utc).isoformat()
        try:
            await sync_site(db, notifier, crawler, chat_id, config.crawl)
            await db.record_crawl_success(site_key, now)
            if failures.record_success(site_key):
                await notifier.send_alert(
                    config.telegram.admin_chat_id, f"✅ [{site_label}] 크롤링 복구됨"
                )
        except Exception as e:
            logger.exception("[%s] crawl cycle failed", site_key)
            await db.record_crawl_failure(site_key, now, f"{type(e).__name__}: {e}")
            if failures.record_failure(site_key):
                await notifier.send_alert(
                    config.telegram.admin_chat_id,
                    f"⚠️ [{site_label}] 크롤링이 연속으로 실패하고 있습니다.",
                )
        await asyncio.sleep(interval)


async def run_retention_loop(db: Database, retention_days: int) -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            await purge_expired(db, retention_days)
        except Exception:
            logger.exception("retention cleanup failed")


def _seconds_until_next(hour: int, minute: int) -> float:
    now = datetime.now(KST)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_digest_loop(
    db: Database,
    notifier: TelegramNotifier,
    chat_id: int,
    hour: int,
    minute: int,
    top_n: int,
) -> None:
    while True:
        wait_seconds = _seconds_until_next(hour, minute)
        logger.info("digest scheduled in %.0f minutes", wait_seconds / 60)
        await asyncio.sleep(wait_seconds)
        try:
            await send_digest(db, notifier, chat_id, top_n)
        except Exception:
            logger.exception("digest send failed")
        await asyncio.sleep(60)  # 같은 분 안에서 즉시 재실행되는 것 방지


async def async_main(config_path: str) -> None:
    config = load_config(config_path)
    acquire_singleton_lock(config.database.path)

    db = Database(config.database.path)
    await db.connect()
    await db.seed_site_state({key: site.enabled for key, site in config.sites.items()})

    # 사이트 크롤 루프 9개가 봇 인스턴스 하나를 동시에 공유하는데, python-telegram-bot의
    # 기본 연결 풀 크기는 1이라 여러 사이트가 동시에 전송을 시도하면 나머지가 1초 만에
    # PoolTimeout으로 실패한다 (실패한 전송은 DB에 기록이 안 남아 다음 사이클에 "새 글"로
    # 재시도되며 도배처럼 보이는 원인이 됐다) - 동시 사용량에 맞게 풀을 넉넉히 키운다.
    bot = Bot(
        token=config.telegram.bot_token,
        request=HTTPXRequest(connection_pool_size=16, pool_timeout=30.0),
    )

    # 채널/그룹 메시지에 붙일 미니앱 버튼 링크를 미리 계산해둔다.
    # BotFather에 Mini App 짧은 이름(short_name)을 등록했으면 t.me 딥링크를 쓰고
    # (진짜 미니앱으로 열림), 아니면 그냥 public_url을 일반 링크로 사용한다.
    channel_webapp_link: str | None = None
    if config.webapp.enabled and config.webapp.short_name:
        me = await bot.get_me()
        channel_webapp_link = f"https://t.me/{me.username}/{config.webapp.short_name}"
    elif config.webapp.enabled and config.webapp.public_url:
        channel_webapp_link = config.webapp.public_url

    notifier = TelegramNotifier(bot, webapp_link=channel_webapp_link)

    crawlers = load_all_crawlers(config)
    failures = FailureTracker(
        config.crawl.failure_alert_threshold, config.crawl.failure_realert_every
    )

    admin_bot = AdminBot(
        config.telegram.bot_token,
        config.telegram.admin_chat_id,
        db,
        [crawler.site_key for crawler in crawlers],
    )
    await admin_bot.start()

    webapp_runner = None
    if config.webapp.enabled:
        webapp_runner = await start_webapp(db, config.telegram.bot_token, config.webapp.port)
        if config.webapp.public_url:
            # 메뉴 버튼(채팅창 왼쪽 아래)은 1:1 대화 전용 web_app 타입이라 항상 public_url을
            # 직접 써야 한다 (t.me 딥링크가 아니라).
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="🔥 인기 핫딜",
                    web_app=WebAppInfo(url=config.webapp.public_url),
                )
            )
            logger.info("Set persistent menu button to mini app: %s", config.webapp.public_url)
        else:
            logger.warning(
                "webapp.enabled=true but webapp.public_url is not set - menu button skipped"
            )

    tasks = [asyncio.create_task(run_retention_loop(db, config.crawl.retention_days))]

    if config.digest.enabled:
        digest_chat_id = config.digest.chat_id or config.telegram.default_chat_id
        tasks.append(
            asyncio.create_task(
                run_digest_loop(
                    db, notifier, digest_chat_id,
                    config.digest.hour, config.digest.minute, config.digest.top_n,
                )
            )
        )
        logger.info(
            "digest scheduled daily at %02d:%02d KST (top %d)",
            config.digest.hour, config.digest.minute, config.digest.top_n,
        )

    for crawler in crawlers:
        site_config = crawler.site_config
        chat_id = site_config.chat_id or config.telegram.default_chat_id
        tasks.append(
            asyncio.create_task(
                run_site_loop(
                    crawler.site_key,
                    crawler,
                    chat_id,
                    site_config.interval_seconds,
                    db,
                    notifier,
                    config,
                    failures,
                )
            )
        )
        logger.info("started crawl loop for %s (every %ss)", crawler.site_key, site_config.interval_seconds)

    try:
        await asyncio.gather(*tasks)
    finally:
        if webapp_runner is not None:
            await webapp_runner.cleanup()
        await admin_bot.stop()
        await db.close()


def main() -> None:
    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    asyncio.run(async_main(config_path))


if __name__ == "__main__":
    main()
