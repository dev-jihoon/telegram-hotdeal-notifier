FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libxslt1.1 xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Cloudflare가 curl_cffi 흉내로는 못 뚫는 JS 챌린지를 거는 사이트(zod 등)를 위해 실제로 JS를
# 실행하는 브라우저가 필요하다. Chromium/headless 모드 둘 다 자동화 특유의 신호로 오히려 더
# 강하게 차단당하는 사례가 있어, Firefox를 "진짜 창을 띄운" 모드로 쓴다(src/crawlers/browser.py
# 의 headless=False) - 컨테이너엔 화면이 없으므로 xvfb(가상 디스플레이)가 필요해서 같이
# 설치하고, 아래 CMD를 xvfb-run으로 감싼다. --with-deps가 필요한 시스템 라이브러리까지 설치한다.
RUN playwright install --with-deps firefox

COPY src ./src
COPY static ./static

ENV CONFIG_PATH=/app/config.yaml
ENV PYTHONUNBUFFERED=1

CMD ["xvfb-run", "-a", "python", "-m", "src.main"]
