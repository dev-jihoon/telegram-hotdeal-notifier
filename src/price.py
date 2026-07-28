import re

_PRICE_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,})\s*원")


def extract_price(title: str) -> str | None:
    """제목에서 '99,000원' 형태의 가격 후보를 추출한다.

    "정가 → 할인가" 형태로 쓰이는 경우가 많아, 여러 개가 발견되면 제목에서
    가장 마지막에 등장하는 가격(보통 최종 할인가)을 사용한다.
    """
    matches = list(_PRICE_RE.finditer(title))
    if not matches:
        return None
    return matches[-1].group(0)
