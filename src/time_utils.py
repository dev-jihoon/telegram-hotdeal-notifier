from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def start_of_today_kst_iso() -> str:
    """KST 기준 오늘 00:00:00을 UTC ISO 문자열로 반환한다.

    다이제스트/미니앱의 "오늘의 인기 핫딜"이 자정을 걸치는 롤링 24시간이 아니라
    달력상 오늘 올라온 글만 보여주도록 이 값을 first_seen_at 필터 기준으로 쓴다.
    """
    start_kst = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    return start_kst.astimezone(timezone.utc).isoformat()
