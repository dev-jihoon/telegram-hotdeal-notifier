# telegram-hotdeal-notifier

한국 주요 커뮤니티(뽐뿌, 클리앙, 루리웹, 아카라이브, 에펨코리아, 쿨앤조이, 다모앙, 퀘이사존, zod)의
핫딜 게시판을 주기적으로 크롤링해 텔레그램으로 알림을 보내는 봇입니다.

- 원글이 삭제되면 텔레그램 메시지도 삭제됩니다
- 핫딜이 종료/품절되면 텔레그램 메시지에 취소선이 적용됩니다
- 원글 제목/가격이 수정되면 텔레그램 메시지도 함께 수정됩니다
- 추천수, 가격, 카테고리, 썸네일을 표시합니다 (사이트가 제공하는 값만, 없으면 생략)
- 상태는 SQLite에 저장되어 재시작해도 삭제/수정 감지가 끊기지 않습니다
- 크롤러가 연속으로 실패하면 관리자 채팅으로 알림을 보냅니다
- 관리자가 봇과의 1:1 채팅에서 `/sites` 명령으로 사이트별 크롤링을 켜고 끌 수 있습니다
- 사이트를 처음 크롤링할 때는 기존 글을 한꺼번에 "신규"로 전송하지 않고 조용히 기준선만
  저장합니다. 그 이후부터 실제로 새로 올라오거나 바뀐 글만 알림이 갑니다.

## 시작하기

```bash
git clone <이 저장소 URL>
cd telegram-hotdeal-notifier
cp config.example.yaml config.yaml
```

`config.yaml`을 열어 아래 값을 채웁니다.

- `telegram.bot_token`: [@BotFather](https://t.me/BotFather)에서 발급받은 봇 토큰
- `telegram.default_chat_id`: 핫딜을 올릴 채널/그룹의 chat_id (봇을 관리자로 초대해야 합니다)
- `telegram.admin_chat_id`: 크롤러 실패 알림과 `/sites` 사이트 on/off 메뉴를 받을 chat_id.
  개인 텔레그램 계정의 user id를 넣고, 반드시 그 계정으로 봇과 먼저 1:1 대화를 시작(`/start`)해
  두세요. 봇은 먼저 DM을 보낼 수 없습니다.

그 다음 실행합니다.

```bash
docker compose up -d --build
docker compose logs -f
```

## 사이트 추가하기

1. `src/crawlers/<site>.py` 파일을 만들고 `BaseCrawler`를 상속한 클래스를 작성합니다.
   `fetch()`에서 `Article` 목록을 반환하면 됩니다. 필요하면 `check_exists()`도
   오버라이드해 삭제 감지 로직을 커스터마이즈할 수 있습니다.
2. 클래스에 `@register_crawler("<site>")` 데코레이터를 붙입니다.
3. `config.yaml`의 `sites:` 아래에 같은 키로 항목을 추가합니다.

```python
# src/crawlers/newsite.py
from .base import BaseCrawler
from .registry import register_crawler
from ..models import Article

@register_crawler("newsite")
class NewSiteCrawler(BaseCrawler):
    async def fetch(self) -> list[Article]:
        ...
```

```yaml
# config.yaml
sites:
  newsite:
    enabled: true
    interval_seconds: 60
    chat_id: -1009999999999  # 이 사이트만 다른 채널로 보내고 싶을 때 (선택, 생략시 default_chat_id)
```

파일을 `src/crawlers/`에 두기만 하면 자동으로 로드됩니다(별도 등록 파일 수정 불필요).

새로 추가한 사이트도 처음 크롤링될 때는 자동으로 "기준선만 저장하고 조용히 대기"하므로,
사이트를 추가하거나 `enabled: true`로 켜도 기존 글이 한꺼번에 쏟아지지 않습니다.

## 관리자 기능 (`/sites`)

`telegram.admin_chat_id`로 지정한 계정이 봇과의 1:1 채팅에서 `/sites`를 보내면, 사이트별
현재 상태(✅ 켜짐 / ⛔ 꺼짐)가 버튼으로 표시됩니다. 버튼을 누르면 즉시 토글되고, 재시작해도
유지됩니다(SQLite에 저장). `config.yaml`의 `enabled` 값은 최초 1회 기본값으로만 쓰이고,
그 이후에는 이 토글이 우선합니다. 새로 켠 사이트도 처음엔 조용히 기준선만 저장한 뒤 다음
사이클부터 알림이 갑니다.

## 알려진 제약사항

- **가격/추천수**: 사이트가 가격을 별도 필드로 제공하면(아카라이브, 퀘이사존, 에펨코리아, 다모앙,
  쿨앤조이) 그 값을 그대로 사용합니다. 그렇지 않은 사이트(뽐뿌, 클리앙, 루리웹)는 제목에서
  정규식으로 가격을 추출하므로 100% 정확하지 않을 수 있습니다.
- **카테고리**: 사이트가 카테고리/분류를 제공하는 경우에만 표시됩니다(다모앙, zod는 목록에서
  카테고리를 제공하지 않아 항상 생략됩니다).
- **퀘이사존/다모앙/zod**: Cloudflare 봇 차단이 걸려 있어 브라우저 TLS/HTTP2 핑거프린트를
  흉내내는 `curl_cffi`로 우회합니다. 서버 환경(특히 IP 평판)에 따라 다시 막힐 수 있습니다.
  계속 막히면 `config.yaml`에서 `enabled: false`로 끄고 다른 사이트만 사용하세요.
- **에펨코리아**: 자체 "보안 시스템"이 있어 짧은 시간에 반복 요청하면 일시적으로 430 응답을
  돌려줄 수 있습니다. `interval_seconds`를 너무 짧게 잡지 마세요(기본값 60초 이상 권장).
- **종료/품절 감지**: 사이트가 구조화된 상태 뱃지를 제공하면(뽐뿌, 클리앙, 아카라이브, 다모앙,
  퀘이사존) 이를 사용하고, 그렇지 않으면(루리웹, 쿨앤조이, 에펨코리아) 제목에 "품절/종료/매진/마감"
  키워드가 있는지로 판단하는 best-effort 방식입니다.

## 설정 항목

`config.example.yaml`에 모든 옵션과 설명이 주석으로 포함되어 있습니다. 주요 항목:

| 항목 | 설명 | 기본값 |
|---|---|---|
| `crawl.listing_pages` | 사이트별로 한 번에 확인할 목록 페이지 수 | 2 |
| `crawl.retention_days` | 이 기간이 지난 글은 DB에서 정리 | 5 |
| `crawl.likes_edit_throttle_minutes` | 추천수만 바뀐 경우 메시지 수정 최소 간격(분) | 10 |
| `crawl.failure_alert_threshold` | 연속 실패 시 관리자 알림을 보내는 횟수 | 3 |
| `sites.<key>.interval_seconds` | 사이트별 크롤링 주기(초) | 60 |
