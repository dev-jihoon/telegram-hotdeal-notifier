from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from telegram import Bot

from .admin_bot import AdminBot
from .config import Config, load_config
from .crawlers import load_all_crawlers
from .db import Database
from .sync import purge_expired, sync_site
from .telegram_notifier import SITE_LABELS, TelegramNotifier

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


async def async_main(config_path: str) -> None:
    config = load_config(config_path)

    db = Database(config.database.path)
    await db.connect()
    await db.seed_site_state({key: site.enabled for key, site in config.sites.items()})

    bot = Bot(token=config.telegram.bot_token)
    notifier = TelegramNotifier(bot)

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

    tasks = [asyncio.create_task(run_retention_loop(db, config.crawl.retention_days))]
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
        await admin_bot.stop()
        await db.close()


def main() -> None:
    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    asyncio.run(async_main(config_path))


if __name__ == "__main__":
    main()
