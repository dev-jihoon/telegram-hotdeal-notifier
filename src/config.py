from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TelegramConfig:
    bot_token: str
    default_chat_id: int
    admin_chat_id: int
    # admin_chat_id는 하위 호환을 위해 그대로 필수 필드로 남겨두고, 추가 관리자만
    # 여기 더한다 - 기존 config.yaml은 이 필드 없이도 그대로 동작한다.
    additional_admin_chat_ids: list[int] = field(default_factory=list)

    @property
    def all_admin_chat_ids(self) -> list[int]:
        return [self.admin_chat_id, *self.additional_admin_chat_ids]


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
class WebhookConfig:
    """Cloudflare 차단이 너무 강한 사이트(아카라이브 등)를 브라우저 확장에서 대신 감지해
    서버로 밀어넣을 때 쓰는 인증 - extension/ 폴더 참고."""

    enabled: bool = False
    secret: str | None = None
    # 하트비트가 이 시간(분) 이상 안 오면 관리자에게 "웹훅 소스가 죽은 것 같다" 알림을 보낸다.
    heartbeat_stale_minutes: int = 30


@dataclass
class Config:
    telegram: TelegramConfig
    database: DatabaseConfig
    crawl: CrawlConfig
    digest: DigestConfig
    webapp: WebappConfig
    display: DisplayConfig
    webhook: WebhookConfig
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
    webhook = WebhookConfig(**raw.get("webhook", {}))

    sites: dict[str, SiteConfig] = {}
    for key, site_raw in (raw.get("sites") or {}).items():
        site_raw = site_raw or {}
        sites[key] = SiteConfig(key=key, **site_raw)

    return Config(
        telegram=telegram, database=database, crawl=crawl,
        digest=digest, webapp=webapp, display=display, webhook=webhook, sites=sites,
    )
