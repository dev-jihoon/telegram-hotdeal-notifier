from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TelegramConfig:
    bot_token: str
    default_chat_id: int
    admin_chat_id: int


@dataclass
class DatabaseConfig:
    path: str = "data/hotdeals.db"


@dataclass
class CrawlConfig:
    listing_pages: int = 2
    retention_days: int = 5
    likes_edit_throttle_minutes: int = 10
    failure_alert_threshold: int = 3
    failure_realert_every: int = 30
    deletion_check_cooldown_minutes: int = 30
    max_deletion_checks_per_cycle: int = 15
    resume_silent_threshold_minutes: int = 20


@dataclass
class SiteConfig:
    key: str
    enabled: bool = True
    chat_id: int | None = None
    interval_seconds: int = 60


@dataclass
class DigestConfig:
    enabled: bool = False
    hour: int = 9
    minute: int = 0
    top_n: int = 5
    chat_id: int | None = None


@dataclass
class WebappConfig:
    enabled: bool = False
    port: int = 8080
    public_url: str | None = None
    short_name: str | None = None


@dataclass
class DisplayConfig:
    """메시지/다이제스트/미니앱에 노출되는 문구를 운영자가 바꿀 수 있게 하는 설정."""

    show_site_name: bool = True
    webapp_button_label: str = "🔥 인기 핫딜"
    webapp_title: str = "🔥 오늘의 인기 핫딜"
    webapp_empty_message: str = "오늘 올라온 핫딜이 아직 없습니다."
    digest_header: str = "🔥 오늘의 인기 핫딜 TOP"
    digest_mall_ranking_label: str = "🏪 오늘의 인기 쇼핑몰"


@dataclass
class Config:
    telegram: TelegramConfig
    database: DatabaseConfig
    crawl: CrawlConfig
    digest: DigestConfig
    webapp: WebappConfig
    display: DisplayConfig
    sites: dict[str, SiteConfig] = field(default_factory=dict)


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    telegram = TelegramConfig(**raw["telegram"])
    database = DatabaseConfig(**raw.get("database", {}))
    crawl = CrawlConfig(**raw.get("crawl", {}))
    digest = DigestConfig(**raw.get("digest", {}))
    webapp = WebappConfig(**raw.get("webapp", {}))
    display = DisplayConfig(**raw.get("display", {}))

    sites: dict[str, SiteConfig] = {}
    for key, site_raw in (raw.get("sites") or {}).items():
        site_raw = site_raw or {}
        sites[key] = SiteConfig(key=key, **site_raw)

    return Config(
        telegram=telegram, database=database, crawl=crawl,
        digest=digest, webapp=webapp, display=display, sites=sites,
    )
