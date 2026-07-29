from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from .models import Article, ArticleStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    site TEXT NOT NULL,
    article_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    price TEXT,
    likes INTEGER,
    status TEXT NOT NULL,
    thumbnail_url TEXT,
    category TEXT,
    mall TEXT,
    delivery TEXT,
    chat_id INTEGER,
    message_id INTEGER,
    has_photo INTEGER NOT NULL DEFAULT 0,
    last_edited_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_checked_at TEXT,
    deleted_at TEXT,
    PRIMARY KEY (site, article_id)
);
CREATE INDEX IF NOT EXISTS idx_articles_site_active
    ON articles (site) WHERE deleted_at IS NULL;
CREATE TABLE IF NOT EXISTS site_state (
    site TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL,
    bootstrapped INTEGER NOT NULL DEFAULT 0,
    last_crawl_at TEXT,
    last_success_at TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS price_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    article_id TEXT NOT NULL,
    old_price TEXT,
    new_price TEXT,
    changed_at TEXT NOT NULL
);
"""

# 이미 존재하는 DB 파일에도 안전하게 컬럼을 추가하기 위한 마이그레이션 목록.
# (컬럼, ADD COLUMN DDL) - 이미 있으면 aiosqlite.OperationalError를 무시한다.
_MIGRATIONS: list[tuple[str, str]] = [
    ("site_state.bootstrapped", "ALTER TABLE site_state ADD COLUMN bootstrapped INTEGER NOT NULL DEFAULT 0"),
    ("site_state.last_crawl_at", "ALTER TABLE site_state ADD COLUMN last_crawl_at TEXT"),
    ("site_state.last_success_at", "ALTER TABLE site_state ADD COLUMN last_success_at TEXT"),
    ("site_state.last_error", "ALTER TABLE site_state ADD COLUMN last_error TEXT"),
    ("articles.category", "ALTER TABLE articles ADD COLUMN category TEXT"),
    ("articles.mall", "ALTER TABLE articles ADD COLUMN mall TEXT"),
    ("articles.delivery", "ALTER TABLE articles ADD COLUMN delivery TEXT"),
    ("articles.last_checked_at", "ALTER TABLE articles ADD COLUMN last_checked_at TEXT"),
]


@dataclass
class TrackedArticle:
    site: str
    article_id: str
    title: str
    url: str
    price: str | None
    likes: int | None
    status: ArticleStatus
    thumbnail_url: str | None
    category: str | None
    mall: str | None
    delivery: str | None
    chat_id: int | None
    message_id: int | None
    has_photo: bool
    last_edited_at: str | None
    first_seen_at: str
    last_seen_at: str
    last_checked_at: str | None
    deleted_at: str | None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "TrackedArticle":
        return cls(
            site=row["site"],
            article_id=row["article_id"],
            title=row["title"],
            url=row["url"],
            price=row["price"],
            likes=row["likes"],
            status=ArticleStatus(row["status"]),
            thumbnail_url=row["thumbnail_url"],
            category=row["category"],
            mall=row["mall"],
            delivery=row["delivery"],
            chat_id=row["chat_id"],
            message_id=row["message_id"],
            has_photo=bool(row["has_photo"]),
            last_edited_at=row["last_edited_at"],
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
            last_checked_at=row["last_checked_at"],
            deleted_at=row["deleted_at"],
        )


class Database:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        await self._migrate()

    async def _migrate(self) -> None:
        for _label, ddl in _MIGRATIONS:
            try:
                await self.conn.execute(ddl)
            except aiosqlite.OperationalError:
                pass  # 컬럼이 이미 존재함
        await self.conn.commit()

        # 예전 스키마(articles.chat_id/message_id가 NOT NULL)로 만들어진 DB 파일 대응.
        # SQLite는 컬럼의 NOT NULL 제약을 직접 뗄 수 없어 테이블을 다시 만든다.
        cursor = await self.conn.execute("PRAGMA table_info(articles)")
        columns = await cursor.fetchall()
        chat_id_col = next((c for c in columns if c["name"] == "chat_id"), None)
        if chat_id_col is not None and chat_id_col["notnull"]:
            await self.conn.executescript(
                """
                ALTER TABLE articles RENAME TO articles_old;
                """
            )
            await self.conn.executescript(SCHEMA)
            old_cols = {c["name"] for c in await (await self.conn.execute("PRAGMA table_info(articles_old)")).fetchall()}
            select_cols = ", ".join(
                col if col in old_cols else f"NULL AS {col}"
                for col in (
                    "site", "article_id", "title", "url", "price", "likes", "status",
                    "thumbnail_url", "category", "mall", "delivery", "chat_id", "message_id",
                    "has_photo", "last_edited_at", "first_seen_at", "last_seen_at",
                    "last_checked_at", "deleted_at",
                )
            )
            await self.conn.execute(f"INSERT INTO articles SELECT {select_cols} FROM articles_old")
            await self.conn.execute("DROP TABLE articles_old")
            await self.conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "Database not connected"
        return self._conn

    async def get_max_numeric_article_id(self, site: str) -> int | None:
        """이 사이트에서 지금까지 한 번이라도 관측한 article_id 중 가장 큰 숫자값.

        게시글 번호는 사이트가 순차 발급하므로, 이 값보다 작은 번호는 오늘 새로
        쓰인 글일 수 없다 - 인기글 재노출 등으로 뒤늦게 크롤 범위(1~2페이지)에
        걸린 오래된 글을 "신규"로 오인해 전송하는 걸 막는 데 쓴다. deleted_at
        여부와 무관하게 전체를 본다 (한 번 봤던 번호는 삭제됐어도 여전히 유효한 상한선).
        """
        cursor = await self.conn.execute(
            "SELECT article_id FROM articles WHERE site = ?", (site,)
        )
        rows = await cursor.fetchall()
        ids = [int(row["article_id"]) for row in rows if row["article_id"].isdigit()]
        return max(ids) if ids else None

    async def get_active_articles(self, site: str) -> dict[str, TrackedArticle]:
        cursor = await self.conn.execute(
            "SELECT * FROM articles WHERE site = ? AND deleted_at IS NULL",
            (site,),
        )
        rows = await cursor.fetchall()
        return {row["article_id"]: TrackedArticle.from_row(row) for row in rows}

    async def insert_article(
        self,
        article: Article,
        chat_id: int,
        message_id: int,
        has_photo: bool,
        now: str,
    ) -> None:
        # ON CONFLICT로 upsert: check_exists 오탐으로 삭제 처리됐던 글이 나중에
        # 다시 "신규"로 감지되어도(PK가 이미 있음) 크래시하지 않고 그냥 되살린다.
        # first_seen_at은 최초 값을 유지한다.
        await self.conn.execute(
            """
            INSERT INTO articles (
                site, article_id, title, url, price, likes, status,
                thumbnail_url, category, mall, delivery, chat_id, message_id, has_photo,
                last_edited_at, first_seen_at, last_seen_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(site, article_id) DO UPDATE SET
                title = excluded.title,
                url = excluded.url,
                price = excluded.price,
                likes = excluded.likes,
                status = excluded.status,
                thumbnail_url = excluded.thumbnail_url,
                category = excluded.category,
                mall = excluded.mall,
                delivery = excluded.delivery,
                chat_id = excluded.chat_id,
                message_id = excluded.message_id,
                has_photo = excluded.has_photo,
                last_edited_at = excluded.last_edited_at,
                last_seen_at = excluded.last_seen_at,
                deleted_at = NULL
            """,
            (
                article.site,
                article.article_id,
                article.title,
                article.url,
                article.price,
                article.likes,
                article.status.value,
                article.thumbnail_url,
                article.category,
                article.mall,
                article.delivery,
                chat_id,
                message_id,
                int(has_photo),
                now,
                now,
                now,
            ),
        )
        await self.conn.commit()

    async def insert_baseline_articles(self, articles: list[Article], now: str) -> None:
        """사이트를 처음 크롤링할 때, 텔레그램 전송 없이 현재 목록을 기준선으로 저장한다.

        chat_id/message_id는 NULL로 남기고, 이후 내용이 바뀌어도 전송하지 않는다
        (기준선 시점에 이미 존재하던 글이라 "신규"가 아니므로) - DB만 조용히 갱신한다.
        """
        await self.conn.executemany(
            """
            INSERT INTO articles (
                site, article_id, title, url, price, likes, status,
                thumbnail_url, category, mall, delivery, chat_id, message_id, has_photo,
                last_edited_at, first_seen_at, last_seen_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0, NULL, ?, ?, NULL)
            ON CONFLICT(site, article_id) DO NOTHING
            """,
            [
                (
                    a.site,
                    a.article_id,
                    a.title,
                    a.url,
                    a.price,
                    a.likes,
                    a.status.value,
                    a.thumbnail_url,
                    a.category,
                    a.mall,
                    a.delivery,
                    now,
                    now,
                )
                for a in articles
            ],
        )
        await self.conn.commit()

    async def update_article(
        self,
        site: str,
        article_id: str,
        *,
        title: str,
        price: str | None,
        likes: int | None,
        status: ArticleStatus,
        thumbnail_url: str | None,
        category: str | None,
        mall: str | None,
        delivery: str | None,
        now: str,
        edited: bool,
    ) -> None:
        if edited:
            await self.conn.execute(
                """
                UPDATE articles
                SET title = ?, price = ?, likes = ?, status = ?, thumbnail_url = ?, category = ?,
                    mall = ?, delivery = ?, last_seen_at = ?, last_edited_at = ?
                WHERE site = ? AND article_id = ?
                """,
                (title, price, likes, status.value, thumbnail_url, category, mall, delivery, now, now, site, article_id),
            )
        else:
            await self.conn.execute(
                """
                UPDATE articles
                SET title = ?, price = ?, likes = ?, status = ?, thumbnail_url = ?, category = ?,
                    mall = ?, delivery = ?, last_seen_at = ?
                WHERE site = ? AND article_id = ?
                """,
                (title, price, likes, status.value, thumbnail_url, category, mall, delivery, now, site, article_id),
            )
        await self.conn.commit()

    async def touch_last_seen(self, site: str, article_id: str, now: str) -> None:
        await self.conn.execute(
            "UPDATE articles SET last_seen_at = ? WHERE site = ? AND article_id = ?",
            (now, site, article_id),
        )
        await self.conn.commit()

    async def touch_checked_at(self, site: str, article_id: str, now: str) -> None:
        await self.conn.execute(
            "UPDATE articles SET last_checked_at = ? WHERE site = ? AND article_id = ?",
            (now, site, article_id),
        )
        await self.conn.commit()

    async def mark_deleted(self, site: str, article_id: str, now: str) -> None:
        await self.conn.execute(
            "UPDATE articles SET deleted_at = ? WHERE site = ? AND article_id = ?",
            (now, site, article_id),
        )
        await self.conn.commit()

    async def purge_old(self, retention_cutoff: str) -> int:
        # 아직 살아있는(삭제 확인 안 된) 글은 아무리 오래돼도 지우지 않는다 - 그렇지 않으면
        # DB에서 사라진 글이 다음 크롤링에 "신규"로 오인되어 중복 전송된다. 이미 삭제
        # 확인된 글의 이력만 retention_days가 지나면 정리한다.
        cursor = await self.conn.execute(
            "DELETE FROM articles WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (retention_cutoff,),
        )
        await self.conn.commit()
        return cursor.rowcount

    async def seed_site_state(self, defaults: dict[str, bool]) -> None:
        """config.yaml의 enabled 값을 초기값으로 심는다.

        이미 site_state에 값이 있으면(과거 관리자 토글 이력) 덮어쓰지 않는다.
        """
        await self.conn.executemany(
            "INSERT INTO site_state (site, enabled) VALUES (?, ?) "
            "ON CONFLICT(site) DO NOTHING",
            [(site, int(enabled)) for site, enabled in defaults.items()],
        )
        await self.conn.commit()

    async def get_site_enabled(self, site: str) -> bool:
        cursor = await self.conn.execute(
            "SELECT enabled FROM site_state WHERE site = ?", (site,)
        )
        row = await cursor.fetchone()
        return bool(row["enabled"]) if row else True

    async def set_site_enabled(self, site: str, enabled: bool) -> None:
        await self.conn.execute(
            "INSERT INTO site_state (site, enabled) VALUES (?, ?) "
            "ON CONFLICT(site) DO UPDATE SET enabled = excluded.enabled",
            (site, int(enabled)),
        )
        await self.conn.commit()

    async def get_all_site_states(self) -> dict[str, bool]:
        cursor = await self.conn.execute("SELECT site, enabled FROM site_state")
        rows = await cursor.fetchall()
        return {row["site"]: bool(row["enabled"]) for row in rows}

    async def get_site_bootstrapped(self, site: str) -> bool:
        cursor = await self.conn.execute(
            "SELECT bootstrapped FROM site_state WHERE site = ?", (site,)
        )
        row = await cursor.fetchone()
        return bool(row["bootstrapped"]) if row else False

    async def set_site_bootstrapped(self, site: str) -> None:
        await self.conn.execute(
            "INSERT INTO site_state (site, enabled, bootstrapped) VALUES (?, 1, 1) "
            "ON CONFLICT(site) DO UPDATE SET bootstrapped = 1",
            (site,),
        )
        await self.conn.commit()

    async def get_site_last_success_at(self, site: str) -> str | None:
        cursor = await self.conn.execute(
            "SELECT last_success_at FROM site_state WHERE site = ?", (site,)
        )
        row = await cursor.fetchone()
        return row["last_success_at"] if row else None

    async def record_crawl_success(self, site: str, now: str) -> None:
        await self.conn.execute(
            "INSERT INTO site_state (site, enabled, last_crawl_at, last_success_at, last_error) "
            "VALUES (?, 1, ?, ?, NULL) "
            "ON CONFLICT(site) DO UPDATE SET last_crawl_at = ?, last_success_at = ?, last_error = NULL",
            (site, now, now, now, now),
        )
        await self.conn.commit()

    async def record_crawl_failure(self, site: str, now: str, error: str) -> None:
        await self.conn.execute(
            "INSERT INTO site_state (site, enabled, last_crawl_at, last_error) VALUES (?, 1, ?, ?) "
            "ON CONFLICT(site) DO UPDATE SET last_crawl_at = ?, last_error = ?",
            (site, now, error, now, error),
        )
        await self.conn.commit()

    async def get_site_report(self, site_keys: list[str]) -> dict[str, dict]:
        """관리자 패널용 사이트별 요약 정보(on/off, 추적 글 수, 마지막 성공/실패)를 모은다."""
        cursor = await self.conn.execute(
            "SELECT site, COUNT(*) AS n FROM articles WHERE deleted_at IS NULL GROUP BY site"
        )
        counts = {row["site"]: row["n"] for row in await cursor.fetchall()}

        cursor = await self.conn.execute(
            "SELECT site, enabled, bootstrapped, last_crawl_at, last_success_at, last_error FROM site_state"
        )
        states = {row["site"]: dict(row) for row in await cursor.fetchall()}

        report = {}
        for site in site_keys:
            state = states.get(site, {})
            report[site] = {
                "enabled": bool(state.get("enabled", True)),
                "bootstrapped": bool(state.get("bootstrapped", False)),
                "tracked": counts.get(site, 0),
                "last_crawl_at": state.get("last_crawl_at"),
                "last_success_at": state.get("last_success_at"),
                "last_error": state.get("last_error"),
            }
        return report

    async def record_price_event(
        self, site: str, article_id: str, old_price: str | None, new_price: str | None, now: str
    ) -> None:
        await self.conn.execute(
            "INSERT INTO price_events (site, article_id, old_price, new_price, changed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (site, article_id, old_price, new_price, now),
        )
        await self.conn.commit()

    async def get_top_articles_since(self, cutoff: str, limit: int) -> list[TrackedArticle]:
        """다이제스트용: 지정 시각 이후 처음 발견된 글 중 추천수 상위 N개."""
        cursor = await self.conn.execute(
            "SELECT * FROM articles WHERE first_seen_at >= ? AND deleted_at IS NULL "
            "ORDER BY likes DESC LIMIT ?",
            (cutoff, limit),
        )
        rows = await cursor.fetchall()
        return [TrackedArticle.from_row(row) for row in rows]

    async def get_latest_old_prices(self, site_article_ids: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
        """주어진 (site, article_id) 목록에 대해 가장 최근 가격 변동의 old_price를 찾는다.

        미니 웹앱에서 할인율을 계산할 때 사용 (price_events는 개인 봇 규모라 전체 스캔해도 가볍다).
        """
        if not site_article_ids:
            return {}
        wanted = set(site_article_ids)
        result: dict[tuple[str, str], str] = {}
        cursor = await self.conn.execute(
            "SELECT site, article_id, old_price FROM price_events ORDER BY changed_at DESC"
        )
        async for row in cursor:
            key = (row["site"], row["article_id"])
            if key in wanted and key not in result and row["old_price"]:
                result[key] = row["old_price"]
                if len(result) == len(wanted):
                    break
        return result

    async def get_mall_counts_since(self, cutoff: str) -> dict[str, int]:
        """다이제스트용: 지정 시각 이후 처음 발견된 글의 쇼핑몰별 등장 횟수."""
        cursor = await self.conn.execute(
            "SELECT mall, COUNT(*) AS n FROM articles "
            "WHERE first_seen_at >= ? AND deleted_at IS NULL AND mall IS NOT NULL "
            "GROUP BY mall ORDER BY n DESC",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        return {row["mall"]: row["n"] for row in rows}
