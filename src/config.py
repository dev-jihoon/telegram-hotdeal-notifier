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


@dataclass
class SiteConfig:
    key: str
    enabled: bool = True
    chat_id: int | None = None
    interval_seconds: int = 60


@dataclass
class Config:
    telegram: TelegramConfig
    database: DatabaseConfig
    crawl: CrawlConfig
    sites: dict[str, SiteConfig] = field(default_factory=dict)


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    telegram = TelegramConfig(**raw["telegram"])
    database = DatabaseConfig(**raw.get("database", {}))
    crawl = CrawlConfig(**raw.get("crawl", {}))

    sites: dict[str, SiteConfig] = {}
    for key, site_raw in (raw.get("sites") or {}).items():
        site_raw = site_raw or {}
        sites[key] = SiteConfig(key=key, **site_raw)

    return Config(telegram=telegram, database=database, crawl=crawl, sites=sites)
