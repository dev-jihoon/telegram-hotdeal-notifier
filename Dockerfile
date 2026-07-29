FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libxslt1.1 wget gnupg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Cloudflare가 curl_cffi 흉내로는 못 뚫는 JS 챌린지를 거는 사이트(zod, arcalive 등)를 위해
# 실제로 JS를 실행하는 브라우저가 필요하다. Playwright가 번들로 까는 Chromium/Firefox는
# 자동화 전용으로 특수 패치된 빌드라 실제 배포판 브라우저와 미묘하게 달라서(TLS 스택 등)
# 계속 차단당했다 - 그래서 수백만 명이 쓰는 바로 그 바이너리인 실제 Google Chrome을 설치하고
# Playwright가 channel="chrome"으로 그걸 직접 조종하게 한다(src/crawlers/browser.py).
# --with-deps로 Chromium 계열이 공통으로 필요한 시스템 라이브러리를 먼저 깐다.
RUN playwright install --with-deps chromium
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

COPY src ./src
COPY static ./static

ENV CONFIG_PATH=/app/config.yaml
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.main"]
