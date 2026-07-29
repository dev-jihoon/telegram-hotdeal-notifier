from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .config import Config
from .db import Database

CATEGORY_LABELS: dict[str, str] = {
    "display": "표시 문구",
    "digest": "다이제스트",
    "crawl": "크롤링",
}


@dataclass
class SettingSpec:
    key: str  # DB 저장 키 겸 콜백 데이터 (예: "digest.hour")
    label: str
    category: str  # CATEGORY_LABELS의 키
    type: type  # bool | int | str
    get: Callable[[Config], Any]
    set: Callable[[Config, Any], None]


def _spec(key: str, label: str, category: str, type_: type) -> SettingSpec:
    section, field = key.split(".", 1)
    return SettingSpec(
        key=key,
        label=label,
        category=category,
        type=type_,
        get=lambda c, _s=section, _f=field: getattr(getattr(c, _s), _f),
        set=lambda c, v, _s=section, _f=field: setattr(getattr(c, _s), _f, v),
    )


# 여기 없는 값(봇 토큰, chat_id, DB 경로, 웹앱 포트/공개주소 등)은 재배포 없이 바꾸면
# 오히려 사고가 나거나(인프라 설정과 어긋남) 의미가 없어서 config.yaml에만 남겨둔다.
SETTINGS: list[SettingSpec] = [
    _spec("display.show_site_name", "사이트명 표시 ([뽐뿌] 같은 접두사)", "display", bool),
    _spec("display.webapp_button_label", "미니앱 버튼 문구", "display", str),
    _spec("display.webapp_title", "미니앱 페이지 제목", "display", str),
    _spec("display.webapp_empty_message", "미니앱 '오늘 글 없음' 문구", "display", str),
    _spec("display.digest_header", "다이제스트 헤더 문구", "display", str),
    _spec("display.digest_mall_ranking_label", "다이제스트 쇼핑몰 랭킹 라벨", "display", str),
    _spec("digest.enabled", "다이제스트 사용 여부", "digest", bool),
    _spec("digest.hour", "다이제스트 발송 시각 (시, 0-23, KST)", "digest", int),
    _spec("digest.minute", "다이제스트 발송 시각 (분)", "digest", int),
    _spec("digest.top_n", "다이제스트 TOP 개수", "digest", int),
    _spec("crawl.listing_pages", "한 번에 확인할 목록 페이지 수", "crawl", int),
    _spec("crawl.retention_days", "삭제된 글 DB 보관 일수", "crawl", int),
    _spec("crawl.likes_edit_throttle_minutes", "추천수만 바뀐 경우 수정 최소 간격(분)", "crawl", int),
    _spec("crawl.failure_alert_threshold", "연속 실패 알림 임계값(회)", "crawl", int),
    _spec("crawl.failure_realert_every", "실패 재알림 주기(회)", "crawl", int),
    _spec("crawl.deletion_check_cooldown_minutes", "삭제 확인 쿨다운(분)", "crawl", int),
    _spec("crawl.max_deletion_checks_per_cycle", "사이클당 삭제 확인 상한(개)", "crawl", int),
    _spec("crawl.resume_silent_threshold_minutes", "재개 시 무음 처리 임계값(분)", "crawl", int),
]

_BY_KEY: dict[str, SettingSpec] = {spec.key: spec for spec in SETTINGS}


def get_spec(key: str) -> SettingSpec | None:
    return _BY_KEY.get(key)


def serialize(spec: SettingSpec, value: Any) -> str:
    if spec.type is bool:
        return "1" if value else "0"
    return str(value)


def deserialize(spec: SettingSpec, raw: str) -> Any:
    if spec.type is bool:
        return raw == "1"
    if spec.type is int:
        return int(raw)
    return raw


def format_value(spec: SettingSpec, value: Any) -> str:
    if spec.type is bool:
        return "켜짐" if value else "꺼짐"
    return str(value)


def parse_user_input(spec: SettingSpec, raw: str) -> Any:
    """관리자가 답장으로 보낸 텍스트를 설정값으로 변환한다. bool은 버튼 토글 전용이라 여기 안 옴."""
    raw = raw.strip()
    if spec.type is int:
        return int(raw)
    return raw


async def apply_db_overrides(config: Config, db: Database) -> None:
    """DB에 저장된 관리자 편집값을 config.yaml 기본값 위에 덮어쓴다.

    재배포 전에는 config.yaml 값이 기본값 역할을 하고, 관리자가 텔레그램에서 한 번이라도
    편집하면 그 값이 DB에 남아 다음 재시작에도 계속 우선 적용된다.
    """
    stored = await db.get_all_settings()
    for spec in SETTINGS:
        if spec.key in stored:
            spec.set(config, deserialize(spec, stored[spec.key]))
