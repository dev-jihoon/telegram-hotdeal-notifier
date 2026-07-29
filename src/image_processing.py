from __future__ import annotations

import asyncio
import io
import logging

import aiohttp
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

TARGET_W = 1280
TARGET_H = 720


async def fetch_letterboxed(url: str, timeout: int = 10) -> bytes | None:
    """썸네일을 내려받아 16:9 캔버스로 정규화한다.

    세로/정사각형 사진이 대부분이라 메시지마다 높이가 들쭉날쭉했던 걸 통일하기 위해,
    원본을 확대+블러한 배경 위에 원본 비율 그대로(찌그러뜨리지 않고) 중앙 배치한다.
    실패하면 None을 반환하고, 호출부에서 원본 URL 전송 등으로 폴백한다.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    return None
                raw = await resp.read()
    except Exception:
        logger.debug("failed to download thumbnail %s", url, exc_info=True)
        return None

    try:
        return await asyncio.to_thread(_letterbox, raw)
    except Exception:
        logger.warning("failed to letterbox thumbnail %s", url, exc_info=True)
        return None


def _letterbox(raw: bytes) -> bytes:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = img.size

    # 배경: 캔버스를 꽉 채우도록 확대+크롭한 뒤 블러 처리
    bg_scale = max(TARGET_W / w, TARGET_H / h)
    bw, bh = max(1, round(w * bg_scale)), max(1, round(h * bg_scale))
    bg = img.resize((bw, bh))
    left = (bw - TARGET_W) // 2
    top = (bh - TARGET_H) // 2
    bg = bg.crop((left, top, left + TARGET_W, top + TARGET_H))
    bg = bg.filter(ImageFilter.GaussianBlur(30))

    # 전경: 원본 비율을 유지한 채(찌그러뜨리지 않고) 캔버스 안에 맞춰 중앙 배치
    fg_scale = min(TARGET_W / w, TARGET_H / h)
    fw, fh = max(1, round(w * fg_scale)), max(1, round(h * fg_scale))
    fg = img.resize((fw, fh))
    fx = (TARGET_W - fw) // 2
    fy = (TARGET_H - fh) // 2
    bg.paste(fg, (fx, fy))

    buf = io.BytesIO()
    bg.save(buf, format="JPEG", quality=85)
    return buf.getvalue()
