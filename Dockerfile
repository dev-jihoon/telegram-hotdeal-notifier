FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libxslt1.1 xvfb xauth x11-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Cloudflare가 curl_cffi 흉내로는 못 뚫는 JS 챌린지를 거는 사이트(zod, arcalive 등)를 위해
# 실제로 JS를 실행하는 브라우저가 필요하다. 서버가 ARM64라 실제 Google Chrome(x86_64 전용)은
# 설치가 안 되고, headless 브라우저(Chromium/Firefox 둘 다, 스텔스 패치 포함)는 계속
# 차단당했다 - 실제 창모드(headless=False)로 띄우기 위해 Xvfb(가상 디스플레이)를 깐다.
RUN playwright install --with-deps firefox

COPY src ./src
COPY static ./static

ENV CONFIG_PATH=/app/config.yaml
ENV PYTHONUNBUFFERED=1

CMD ["xvfb-run", "-a", "python", "-m", "src.main"]
