from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .config import CrawlConfig
from .crawlers.base import BaseCrawler
from .db import Database
from .telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _throttle_elapsed(last_edited_at: str | None, minutes: int, now_iso: str) -> bool:
    if not last_edited_at:
        return True
    last = datetime.fromisoformat(last_edited_at)
    now = datetime.fromisoformat(now_iso)
    return (now - last) >= timedelta(minutes=minutes)


async def sync_site(
    db: Database,
    notifier: TelegramNotifier,
    crawler: BaseCrawler,
    chat_id: int,
    crawl_config: CrawlConfig,
) -> None:
    site = crawler.site_key
    articles = await crawler.fetch()
    now = _now_iso()

    if not await db.get_site_bootstrapped(site):
        # 이 사이트를 처음 크롤링하는 경우: 현재 목록 전체를 "신규"로 취급해 한꺼번에
        # 전송하면 도배가 되므로, 텔레그램 전송 없이 기준선으로만 저장한다.
        # 이후 사이클부터 실제로 새로 올라오거나 바뀐 글만 알림이 간다.
        #
        # 결과가 비정상적으로 적으면(차단/파싱 실패 가능성) 기준선으로 확정하지 않고
        # 다음 사이클에 재시도한다 - 그렇지 않으면 나중에 차단이 풀렸을 때 그 시점의
        # 전체 목록이 "신규"로 오인되어 도배가 재발할 수 있다.
        if len(articles) < 3:
            logger.warning(
                "[%s] bootstrap crawl returned only %d articles, retrying next cycle instead of confirming baseline",
                site,
                len(articles),
            )
            return
        await db.insert_baseline_articles(articles, now)
        await db.set_site_bootstrapped(site)
        logger.info(
            "[%s] bootstrapped with %d existing articles (no telegram messages sent)",
            site,
            len(articles),
        )
        return

    tracked = await db.get_active_articles(site)

    seen_ids: set[str] = set()
    for article in articles:
        seen_ids.add(article.article_id)
        existing = tracked.get(article.article_id)

        if existing is None:
            message_id, has_photo = await notifier.send(article, chat_id)
            await db.insert_article(article, chat_id, message_id, has_photo, now)
            logger.info("[%s] new article %s", site, article.article_id)
            continue

        # category/mall/delivery는 부가 정보라 그 자체 변화로는 알림을 재전송하지 않는다.
        # (이 필드들이 나중에 추가되면서 기존 글들이 전부 NULL -> 실제값으로 한꺼번에
        # "변경됨"으로 잡혀 대량 재전송/재수정되는 사고가 있었다 - 재발 방지)
        content_changed = (
            existing.title != article.title
            or existing.price != article.price
            or existing.status != article.status
        )
        likes_changed = existing.likes != article.likes
        price_changed = existing.price != article.price and article.price is not None

        if existing.message_id is None:
            # 기준선으로만 저장돼 있던(텔레그램 미전송) 글 -> 실제 내용이 바뀐 경우에만
            # 그제서야 처음으로 전송한다. 추천수만 오른 건 promote하지 않는다.
            if content_changed:
                if price_changed:
                    await db.record_price_event(site, article.article_id, existing.price, article.price, now)
                message_id, has_photo = await notifier.send(article, chat_id)
                await db.promote_baseline(
                    site,
                    article.article_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    has_photo=has_photo,
                    title=article.title,
                    price=article.price,
                    likes=article.likes,
                    status=article.status,
                    thumbnail_url=article.thumbnail_url,
                    category=article.category,
                    mall=article.mall,
                    delivery=article.delivery,
                    now=now,
                )
                logger.info("[%s] baseline article changed, now sending %s", site, article.article_id)
            else:
                await db.touch_last_seen(site, article.article_id, now)
            continue

        if content_changed or (likes_changed and _throttle_elapsed(
            existing.last_edited_at, crawl_config.likes_edit_throttle_minutes, now
        )):
            if price_changed:
                await db.record_price_event(site, article.article_id, existing.price, article.price, now)
            await notifier.edit(
                article, existing.chat_id, existing.message_id, existing.has_photo,
                previous_price=existing.price if price_changed else None,
            )
            await db.update_article(
                site,
                article.article_id,
                title=article.title,
                price=article.price,
                likes=article.likes,
                status=article.status,
                thumbnail_url=article.thumbnail_url,
                category=article.category,
                mall=article.mall,
                delivery=article.delivery,
                now=now,
                edited=True,
            )
            logger.info("[%s] edited article %s", site, article.article_id)
        elif likes_changed:
            # 추천수만 바뀌었고 아직 throttle 기간 내 -> DB만 갱신, 텔레그램 메시지는 건드리지 않음
            await db.update_article(
                site,
                article.article_id,
                title=article.title,
                price=article.price,
                likes=article.likes,
                status=article.status,
                thumbnail_url=article.thumbnail_url,
                category=article.category,
                mall=article.mall,
                delivery=article.delivery,
                now=now,
                edited=False,
            )
        else:
            await db.touch_last_seen(site, article.article_id, now)

    for article_id, existing in tracked.items():
        if article_id in seen_ids:
            continue
        still_exists = await crawler.check_exists(existing.url)
        if not still_exists:
            if existing.message_id is not None:
                await notifier.delete(existing.chat_id, existing.message_id)
            await db.mark_deleted(site, article_id, now)
            logger.info("[%s] deleted article %s", site, article_id)


async def purge_expired(db: Database, retention_days: int) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    removed = await db.purge_old(cutoff)
    if removed:
        logger.info("purged %d expired article rows", removed)
