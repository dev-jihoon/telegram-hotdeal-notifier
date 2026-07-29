from __future__ import annotations

import html
import logging

from .config import DisplayConfig
from .db import Database
from .telegram_notifier import SITE_LABELS, TelegramNotifier
from .time_utils import start_of_today_kst_iso

logger = logging.getLogger(__name__)


def _build_summary_text(
    articles: list, mall_counts: dict[str, int], display: DisplayConfig
) -> str:
    lines = [display.digest_header, ""]
    for i, article in enumerate(articles, start=1):
        title = html.escape(article.title, quote=False)
        label = f"[{SITE_LABELS.get(article.site, article.site)}] " if display.show_site_name else ""
        parts = [f"{i}. <a href=\"{article.url}\">{label}{title}</a>"]
        if article.likes is not None:
            parts.append(f"👍 {article.likes}")
        lines.append("\n".join(parts))
        lines.append("")

    if mall_counts:
        top_malls = list(mall_counts.items())[:5]
        ranking = ", ".join(f"{mall}({count})" for mall, count in top_malls)
        lines.append(f"{display.digest_mall_ranking_label}: {ranking}")

    return "\n".join(lines).strip()


async def send_digest(
    db: Database, notifier: TelegramNotifier, chat_id: int, top_n: int, display: DisplayConfig
) -> None:
    # 자정을 걸치는 롤링 24시간이 아니라, 달력상 오늘(KST) 올라온 글만 대상으로 한다.
    cutoff = start_of_today_kst_iso()
    articles = await db.get_top_articles_since(cutoff, top_n)
    if not articles:
        logger.info("digest: no articles today, skipping")
        return

    mall_counts = await db.get_mall_counts_since(cutoff)

    text = _build_summary_text(articles, mall_counts, display)
    await notifier.send_digest_text(chat_id, text)
    logger.info("digest sent with %d articles", len(articles))
