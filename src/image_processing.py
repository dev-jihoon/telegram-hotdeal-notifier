from __future__ import annotations

import asyncio
import io
import logging
from urllib.parse import urlsplit

import aiohttp
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

TARGET_W = 1280
TARGET_H = 720

# 전경 확대 시 원본의 세로/가로 중 잘려나가는(크롭되는) 비율의 상한. 세로로 아주 긴
# 이미지를 "원본 비율 그대로 축소(contain)"하면 폭이 너무 좁아져(양옆에 블러만 크게
# 남아) 정작 중요한 내용이 작게 보인다 - 이 비율까지는 크롭을 허용해 더 확대하고,
# 그 이상은 내용이 너무 잘릴 수 있어 확대를 멈춘다.
MAX_CROP_FRACTION = 0.5

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def fetch_letterboxed(url: str, timeout: int = 10) -> bytes | None:
    """썸네일을 내려받아 16:9 캔버스로 정규화한다.

    세로/정사각형 사진이 대부분이라 메시지마다 높이가 들쭉날쭉했던 걸 통일하기 위해,
    원본을 확대+블러한 배경 위에 원본을 중앙 배치한다.
    실패하면 None을 반환하고, 호출부에서 원본 URL 전송 등으로 폴백한다.
    """
    try:
        parts = urlsplit(url)
        # 일부 사이트(퀘이사존 등)의 이미지 CDN은 리퍼러 없는 요청을 핫링크 방지로 403
        # 처리한다 - 이미지가 걸려있던 사이트 자체를 리퍼러로 보내 우회한다.
        headers = {"User-Agent": _UA, "Referer": f"{parts.scheme}://{parts.netloc}/"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    return None
                raw = await resp.read()
    except Exception:
        logger.debug("failed to download thumbnail %s", url, exc_info=True)
        return None

    return await letterbox_raw_bytes(raw)


async def letterbox_raw_bytes(raw: bytes) -> bytes | None:
    """이미 확보된 이미지 바이트를 16:9 캔버스로 정규화한다.

    브라우저 확장(웹훅 소스)처럼 이미지를 이미 다운로드해서 보내오는 경우, 서버가
    원본 사이트에 또 요청을 보낼 필요 없이 이 함수로 바로 정규화한다.
    """
    try:
        return await asyncio.to_thread(_letterbox, raw)
    except Exception:
        logger.warning("failed to letterbox raw image bytes", exc_info=True)
        return None


def _letterbox(raw: bytes) -> bytes:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = img.size

    contain_scale = min(TARGET_W / w, TARGET_H / h)
    cover_scale = max(TARGET_W / w, TARGET_H / h)

    # 배경: 캔버스를 꽉 채우도록 확대+크롭한 뒤 블러 처리
    bw, bh = max(1, round(w * cover_scale)), max(1, round(h * cover_scale))
    bg = img.resize((bw, bh))
    left = (bw - TARGET_W) // 2
    top = (bh - TARGET_H) // 2
    bg = bg.crop((left, top, left + TARGET_W, top + TARGET_H))
    bg = bg.filter(ImageFilter.GaussianBlur(30))

    # 전경: MAX_CROP_FRACTION만큼은 크롭을 허용하는 한도 내에서 최대한 확대(cover는 넘지
    # 않음)한 뒤, 캔버스 폭/높이 중 넘치는 쪽만 중앙 크롭한다. 일반 비율(16:9에 가까운)
    # 이미지는 그 한도 안에서 cover 스케일에 도달해 예전과 동일하게 꽉 채워진다.
    keep_fraction = 1 - MAX_CROP_FRACTION
    max_scale_by_crop = min(TARGET_H / (h * keep_fraction), TARGET_W / (w * keep_fraction))
    fg_scale = max(contain_scale, min(cover_scale, max_scale_by_crop))
    fw, fh = max(1, round(w * fg_scale)), max(1, round(h * fg_scale))
    fg = img.resize((fw, fh))
    crop_w, crop_h = min(fw, TARGET_W), min(fh, TARGET_H)
    fleft, ftop = (fw - crop_w) // 2, (fh - crop_h) // 2
    fg = fg.crop((fleft, ftop, fleft + crop_w, ftop + crop_h))
    fx, fy = (TARGET_W - crop_w) // 2, (TARGET_H - crop_h) // 2
    bg.paste(fg, (fx, fy))

    buf = io.BytesIO()
    bg.save(buf, format="JPEG", quality=85)
    return buf.getvalue()
