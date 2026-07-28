from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone

from .db import Database
from .telegram_notifier import SITE_LABELS, TelegramNotifier

logger = logging.getLogger(__name__)


def _build_summary_text(articles: list, mall_counts: dict[str, int]) -> str:
    lines = ["🔥 오늘의 인기 핫딜 TOP", ""]
    for i, article in enumerate(articles, start=1):
        site_label = SITE_LABELS.get(article.site, article.site)
        title = html.escape(article.title, quote=False)
        parts = [f"{i}. <a href=\"{article.url}\">[{site_label}] {title}</a>"]
        meta = []
        if article.price:
            meta.append(f"💰 {html.escape(article.price, quote=False)}")
        if article.likes is not None:
            meta.append(f"👍 {article.likes}")
        if meta:
            parts.append(" | ".join(meta))
        lines.append("\n".join(parts))
        lines.append("")

    if mall_counts:
        top_malls = list(mall_counts.items())[:5]
        ranking = ", ".join(f"{mall}({count})" for mall, count in top_malls)
        lines.append(f"🏪 오늘의 인기 쇼핑몰: {ranking}")

    return "\n".join(lines).strip()


async def send_digest(
    db: Database,
    notifier: TelegramNotifier,
    chat_id: int,
    top_n: int,
    webapp_url: str | None = None,
) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    articles = await db.get_top_articles_since(cutoff, top_n)
    if not articles:
        logger.info("digest: no articles in the last 24h, skipping")
        return

    mall_counts = await db.get_mall_counts_since(cutoff)

    text = _build_summary_text(articles, mall_counts)
    await notifier.send_digest_text(chat_id, text, webapp_url=webapp_url)
    logger.info("digest sent with %d articles", len(articles))
