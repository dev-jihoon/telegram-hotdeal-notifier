FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# zod는 Cloudflare가 curl_cffi 흉내로는 못 뚫는 JS 챌린지를 걸어놔서, 실제로 JS를 실행하는
# 헤드리스 브라우저(Chromium)가 필요하다. --with-deps가 필요한 시스템 라이브러리까지 설치한다.
RUN playwright install --with-deps chromium

COPY src ./src
COPY static ./static

ENV CONFIG_PATH=/app/config.yaml
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.main"]
