import re

_PRICE_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,})\s*원")
_WON_DIGITS_RE = re.compile(r"\d[\d,]*")
_MALL_RE = re.compile(r"^\s*\[([^\[\]]+)\]")
# 쇼핑몰명이 아니라 카테고리/분류 표기로 쓰이는 게 확인된 값들 (예: 쿨앤조이의 "[기타]"는
# 실제로는 카테고리 태그라 이 값이 나오면 쇼핑몰로 취급하지 않는다).
_MALL_DENYLIST = {"기타", "이벤트정보", "정보", "공지", "기타정보"}


def extract_price(title: str) -> str | None:
    """제목에서 '99,000원' 형태의 가격 후보를 추출한다.

    "정가 → 할인가" 형태로 쓰이는 경우가 많아, 여러 개가 발견되면 제목에서
    가장 마지막에 등장하는 가격(보통 최종 할인가)을 사용한다.
    """
    matches = list(_PRICE_RE.finditer(title))
    if not matches:
        return None
    return matches[-1].group(0)


def parse_won(price_str: str | None) -> int | None:
    """'99,000원' 같은 가격 문자열을 정수로 변환한다 (할인율 계산용)."""
    if not price_str:
        return None
    match = _WON_DIGITS_RE.search(price_str)
    if not match:
        return None
    digits = match.group(0).replace(",", "")
    return int(digits) if digits.isdigit() else None


def extract_mall(title: str) -> str | None:
    """제목 맨 앞의 '[쇼핑몰]' 패턴에서 쇼핑몰명을 추출한다.

    대부분의 사이트 제목이 이 관례를 따른다. 구조화된 필드가 있는 사이트는
    그 값으로 덮어쓴다.
    """
    match = _MALL_RE.match(title)
    if not match:
        return None
    mall = match.group(1).strip()
    if not mall or mall in _MALL_DENYLIST:
        return None
    return mall
