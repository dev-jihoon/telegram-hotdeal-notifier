from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .config import CrawlConfig
from .crawlers.base import BaseCrawler
from .db import Database, TrackedArticle
from .models import Article
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
    known_max_id = await db.get_max_numeric_article_id(site)

    seen_ids: set[str] = set()
    for article in articles:
        seen_ids.add(article.article_id)
        existing = tracked.get(article.article_id)
        try:
            await _process_article(
                db, notifier, site, chat_id, crawl_config, article, existing, now, known_max_id
            )
        except Exception:
            # 글 하나 처리(전송/수정 등)가 실패해도 이번 사이클의 나머지 글은 계속 처리한다.
            # 여기서 예외가 전체 사이클을 중단시키면, 아직 처리 못한 나머지 글들이 DB에
            # 기록되지 않은 채 다음 사이클에 전부 "신규"로 다시 잡혀 도배로 이어질 수 있다.
            logger.exception(
                "[%s] failed to process article %s, skipping for this cycle", site, article.article_id
            )

    for article_id, existing in tracked.items():
        if article_id in seen_ids:
            continue
        try:
            still_exists = await crawler.check_exists(existing.url)
            if not still_exists:
                if existing.message_id is not None:
                    await notifier.delete(existing.chat_id, existing.message_id)
                await db.mark_deleted(site, article_id, now)
                logger.info("[%s] deleted article %s", site, article_id)
        except Exception:
            logger.exception(
                "[%s] failed to check/delete article %s, skipping for this cycle", site, article_id
            )


async def _process_article(
    db: Database,
    notifier: TelegramNotifier,
    site: str,
    chat_id: int,
    crawl_config: CrawlConfig,
    article: Article,
    existing: TrackedArticle | None,
    now: str,
    known_max_id: int | None,
) -> None:
    if existing is None:
        # 게시글 번호는 사이트가 순차 발급하므로, 지금까지 관측한 최고 번호보다 작은
        # 번호가 처음 발견되면 오늘 새로 쓰인 글이 아니라 인기글 재노출 등으로 뒤늦게
        # 크롤 범위에 걸린 오래된 글이다 - 신규 전송 없이 조용히 기록만 한다.
        # (부트스트랩 당시 목록에 없었던 오래된 글이 "새 글"로 오인 전송되던 문제의 원인)
        if (
            known_max_id is not None
            and article.article_id.isdigit()
            and int(article.article_id) <= known_max_id
        ):
            await db.insert_baseline_articles([article], now)
            logger.info(
                "[%s] old article %s resurfaced in listing (max seen so far: %d), tracked silently",
                site, article.article_id, known_max_id,
            )
            return
        message_id, has_photo = await notifier.send(article, chat_id)
        await db.insert_article(article, chat_id, message_id, has_photo, now)
        logger.info("[%s] new article %s", site, article.article_id)
        return

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
        # 기준선으로만 저장돼 있던(텔레그램 미전송) 글. 부트스트랩이 잡아둔 시점에 이미
        # 존재하던 글이므로, 나중에 제목/가격/상태가 바뀌어도 "신규"로 전송하지 않는다.
        # (예전엔 여기서 실제 전송(promote)했는데, listing_pages로 최대 수 시간~하루치
        # 기존 글까지 기준선에 잡히다 보니, 그 글들이 나중에 조금만 바뀌어도 "새 글"인 것처럼
        # 채널에 올라가는 문제가 있었다 - "옛날 글이 새 글로 온다"는 신고의 진짜 원인이었다.
        # 기준선 글에 대한 갱신은 DB에만 조용히 반영한다.)
        if content_changed:
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
        return

    if content_changed or (likes_changed and _throttle_elapsed(
        existing.last_edited_at, crawl_config.likes_edit_throttle_minutes, now
    )):
        if price_changed:
            await db.record_price_event(site, article.article_id, existing.price, article.price, now)
        await notifier.edit(article, existing.chat_id, existing.message_id, existing.has_photo)
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


async def purge_expired(db: Database, retention_days: int) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    removed = await db.purge_old(cutoff)
    if removed:
        logger.info("purged %d expired article rows", removed)
