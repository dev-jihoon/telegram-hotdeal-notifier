FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Cloudflare가 curl_cffi 흉내로는 못 뚫는 JS 챌린지를 거는 사이트(zod 등)를 위해 실제로 JS를
# 실행하는 헤드리스 브라우저가 필요하다. Chromium은 headless 자동화 특유의 신호(CDP 등)로
# 오히려 더 강하게 차단당하는 사례가 있어 Firefox를 쓴다. --with-deps가 필요한 시스템
# 라이브러리까지 설치한다.
RUN playwright install --with-deps firefox

COPY src ./src
COPY static ./static

ENV CONFIG_PATH=/app/config.yaml
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.main"]
