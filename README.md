# telegram-hotdeal-notifier

한국 주요 커뮤니티(뽐뿌, 클리앙, 루리웹, 아카라이브, 에펨코리아, 쿨앤조이, 다모앙, 퀘이사존, zod)의
핫딜 게시판을 주기적으로 크롤링해 텔레그램으로 알림을 보내는 봇입니다.

- 원글이 삭제되면 텔레그램 메시지도 삭제됩니다
- 핫딜이 종료/품절되면 텔레그램 메시지에 취소선이 적용됩니다
- 원글 제목/가격이 수정되면 텔레그램 메시지도 함께 수정됩니다. 가격이 실제로 내려간 경우
  `~~99,000원~~ → 89,000원 (-10%)` 처럼 변동 내역과 할인율을 함께 보여줍니다
  (우리가 직접 관측한 하락만 근거로 삼고, 제목에서 "정가"를 추측하지 않습니다)
- 추천수, 가격, 카테고리, 쇼핑몰, 배송비, 썸네일을 표시합니다 (사이트가 제공하는 값만, 없으면 생략)
- 상태는 SQLite에 저장되어 재시작해도 삭제/수정 감지가 끊기지 않습니다
- 크롤러가 연속으로 실패하면 관리자 채팅으로 알림을 보냅니다
- 관리자가 봇과의 1:1 채팅에서 `/sites` 명령으로 사이트별 크롤링을 켜고 끌 수 있습니다
- 사이트를 처음 크롤링할 때는 기존 글을 한꺼번에 "신규"로 전송하지 않고 조용히 기준선만
  저장합니다. 그 이후부터 실제로 새로 올라오거나 바뀐 글만 알림이 갑니다.
- (선택) 매일 정해진 시각에 추천수 TOP N + 인기 쇼핑몰 랭킹을 앨범+텍스트로 요약 전송합니다
- (선택) "오늘의 인기 핫딜"을 텔레그램 미니 웹앱으로 볼 수 있습니다

## 시작하기

```bash
git clone <이 저장소 URL>
cd telegram-hotdeal-notifier
cp config.example.yaml config.yaml
cp docker-compose.example.yml docker-compose.yml
```

`config.yaml`을 열어 아래 값을 채웁니다.

- `telegram.bot_token`: [@BotFather](https://t.me/BotFather)에서 발급받은 봇 토큰
- `telegram.default_chat_id`: 핫딜을 올릴 채널/그룹의 chat_id (봇을 관리자로 초대해야 합니다)
- `telegram.admin_chat_id`: 크롤러 실패 알림과 `/sites` 사이트 on/off 메뉴를 받을 chat_id.
  개인 텔레그램 계정의 user id를 넣고, 반드시 그 계정으로 봇과 먼저 1:1 대화를 시작(`/start`)해
  두세요. 봇은 먼저 DM을 보낼 수 없습니다.
- `telegram.additional_admin_chat_ids`: 관리자를 더 추가하고 싶을 때 (선택, 리스트). 여기
  적힌 계정들도 admin_chat_id와 동일하게 모든 관리자 명령을 쓸 수 있고 알림도 같이 받습니다.
  마찬가지로 각 계정이 먼저 봇과 1:1 대화를 시작해둬야 합니다.

그 다음 실행합니다.

```bash
docker compose up -d --build
docker compose logs -f
```

> **같은 DB를 대상으로 봇을 중복 실행하지 마세요.** 인스턴스가 두 개 이상 뜨면(예: 이전
> 프로세스를 Ctrl+C가 아니라 Ctrl+Z로 멈추고 다시 실행, 또는 서로 다른 폴더에서 각각
> `docker compose up`) 부트스트랩/삭제 판정이 서로 경합해서 옛날 글이 새 글로 재전송되는
> 등 데이터가 꼬입니다. 이를 막기 위해 시작 시점에 `data/*.lock` 파일로 잠금을 걸어서,
> 이미 실행 중인 인스턴스가 있으면 새 프로세스는 바로 에러를 내고 종료합니다.

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

## 관리자 기능

`telegram.admin_chat_id`로 지정한 계정만 봇과의 1:1 채팅에서 아래 명령을 쓸 수 있습니다.

- `/start` — 사용 가능한 명령어 안내
- `/sites` — 사이트별 on/off 버튼. 버튼에 추적 중인 글 수도 함께 표시됩니다
  (예: `✅ 뽐뿌 (41)`). 누르면 즉시 토글되고 재시작해도 유지됩니다(SQLite에 저장).
  `config.yaml`의 `enabled` 값은 최초 1회 기본값으로만 쓰이고, 이후에는 이 토글이
  우선합니다. 새로 켠 사이트도 처음엔 조용히 기준선만 저장한 뒤 다음 사이클부터
  알림이 갑니다.
- `/status` — 사이트별 추적 글 수, 마지막 성공/실패 시각, 실패 사유를 한눈에 보여줍니다.
  🔄 새로고침 버튼으로 다시 조회할 수 있습니다.
- `/settings` — 메시지/다이제스트/미니앱 문구와 크롤링 관련 세부 설정을 카테고리별로 보고
  편집합니다. 켜짐/꺼짐 값은 버튼으로 바로 토글되고, 글자/숫자 값은 버튼을 누른 뒤 다음
  메시지로 새 값을 보내면 반영됩니다. **재배포나 재시작 없이 바로 적용**되고 SQLite에 저장돼
  이후 재시작에도 유지됩니다 — `config.yaml`의 해당 값은 한 번도 편집 전이었을 때만 쓰이는
  기본값 역할만 합니다. 봇 토큰/chat_id/DB 경로/웹앱 포트·공개주소처럼 재배포 없이 바꾸면
  오히려 인프라 설정과 어긋나는 값은 여기 포함하지 않고 `config.yaml`에만 둡니다.
- `/admins` — 각 핫딜 메시지 아래에 붙는 "관리자 1:1 문의" 버튼을 관리합니다. 여러 명 등록
  가능하고, 버튼을 누르면 그 관리자와의 텔레그램 1:1 채팅(`https://t.me/<username>`)이
  열립니다. ➕ 추가를 누른 뒤 `버튼 문구|username` 형식으로 답장하면 등록되고(예: `📩
  문의하기|dev_jihoon`), 각 항목 옆 ❌로 삭제할 수 있습니다. 재배포 없이 바로 적용되고
  SQLite에 저장됩니다.

## 일일 다이제스트

`config.yaml`에서 `digest.enabled: true`로 켜면 매일 `digest.hour:digest.minute`(한국시간)에
그날(한국시간 자정 기준, 롤링 24시간이 아님) 처음 올라온 글 중 추천수 상위 `digest.top_n`개를
정리해서 보냅니다. 헤더 문구, 쇼핑몰 랭킹 라벨은 `display.*` 설정(또는 `/settings`)으로
바꿀 수 있습니다.

순위/제목/가격/추천수와 실제 링크, 인기 쇼핑몰 랭킹을 담은 텍스트 메시지 하나로 전송합니다.
(앨범 미리보기도 고려했지만, 미디어그룹 항목에는 버튼을 못 붙여서 다른 알림 메시지들과 버튼
구성이 달라지는 게 더 어색해 텍스트 메시지로 통일했습니다.)

기본적으로 `telegram.default_chat_id`로 가고, `digest.chat_id`를 지정하면 다른 채널로 보낼 수
있습니다.

## 텔레그램 미니 웹앱

`config.yaml`에서 `webapp.enabled: true`로 켜면 "오늘의 인기 핫딜"을 웹뷰로 볼 수 있는 미니
웹앱이 함께 뜹니다 (같은 컨테이너 안에서 `webapp.port`로 리슨). 목록은 다이제스트와 동일하게
그날(한국시간 자정 기준) 올라온 글만 보여줍니다. 페이지 제목, 사이트명 표시 여부, 빈 목록
문구, 버튼 문구는 `display.*` 설정(또는 `/settings`)으로 바꿀 수 있습니다.

**배포하려면 HTTPS 도메인이 필요합니다** (텔레그램 미니앱은 HTTP를 허용하지 않습니다). nginx
리버스 프록시 예시:

```nginx
server {
    listen 443 ssl;
    server_name hotdeal.example.com;
    # ssl_certificate ...;  # Let's Encrypt 등

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
    }
}
```

도메인이 준비되면 `config.yaml`의 `webapp.public_url`에 그 주소를 적어주세요. 그러면 봇이
시작될 때 자동으로 봇과의 1:1 대화 메뉴에 "🔥 인기 핫딜" 버튼을 항상 노출합니다
(`set_chat_menu_button`, 1:1 대화 전용 기능이라 여기서만 진짜 미니앱으로 바로 열립니다).

**채널/그룹 메시지에도 미니앱 버튼을 붙이려면** (핫딜 알림의 "바로가기" 옆, 다이제스트의
"📱 웹에서 더보기") 한 단계가 더 필요합니다 — 텔레그램은 채널/그룹 인라인 버튼에 미니앱 전용
`web_app` 타입을 허용하지 않아서, 일반 URL 버튼처럼 보이지만 텔레그램이 특별 처리해서 진짜
미니앱으로 열어주는 "다이렉트 링크"를 대신 씁니다. 이 링크를 쓰려면 BotFather에 Mini App을
등록해야 합니다.

1. [@BotFather](https://t.me/BotFather)에게 `/newapp`을 보냅니다
2. 봇을 선택하고 앱 제목/설명/아이콘을 입력합니다
3. Web App URL을 물어보면 `webapp.public_url`과 동일한 주소를 입력합니다
4. 마지막에 짧은 이름(short name)을 정하게 되는데, 이 값을 `config.yaml`의
   `webapp.short_name`에 그대로 적습니다 (예: `hotdeals`)

`short_name`을 채우면 `https://t.me/<봇 유저네임>/<short_name>` 딥링크가 만들어져 이후
전송되는 모든 핫딜 메시지와 다이제스트에 자동으로 버튼이 붙습니다. `short_name` 없이
`public_url`만 있으면 다이제스트에는 일반 링크 버튼이 붙지만, 채널 알림 메시지에는 안 붙습니다
(그냥 보통 브라우저로 열리긴 하지만, 텔레그램이 진짜 미니앱으로 인식하려면 위 딥링크 형식이
필요합니다). 둘 다 비워두면 웹서버는 뜨지만 어디에도 버튼이 연결되지 않습니다.

미니앱 API(`/api/deals`)는 요청이 실제로 텔레그램 미니앱을 통해 온 것인지 `X-Telegram-Init-Data`
헤더를 봇 토큰으로 HMAC 검증해서 확인하고, 검증에 실패하면 403을 반환합니다 — 아무나 이 API를
긁어가지 못하도록 하는 최소한의 보호 장치입니다.

## 브라우저 확장으로 Cloudflare 우회 (아카라이브)

아카라이브는 Cloudflare 봇 차단이 매우 강해서 `curl_cffi` TLS 위장, 헤드리스/헤드풀
Playwright(Chromium/Firefox), 실제 브라우저 쿠키 주입까지 시도했지만 서버에서 실행하는 모든
자동화 방식이 동일하게 차단됩니다. 대신 **이미 Cloudflare 챌린지를 통과한 상태로 계속 켜둘 수
있는 브라우저 세션**(예: webtop 컨테이너의 Firefox)에 `extension/` 폴더의 확장 프로그램을 설치해
아카라이브 게시판 목록 페이지(`/b/<게시판>`, 아무 게시판이나 가능)를 열어두면, 확장이 폴링
크롤러와 똑같은 주기(기본 1분)로 같은 URL을 다시 `fetch()`해(이미 통과한 세션의 쿠키가 그대로
실려 나갑니다) 목록 전체를 파싱해 서버로 보냅니다. 처음엔 아카라이브가 웹소켓으로 목록을
실시간 갱신할 거라 보고 MutationObserver로 새 글만 감지하려 했지만, 실제로는 새로고침 없이는
목록 자체가 갱신되지 않는 걸 확인해 이 방식으로 바꿨습니다. 서버는 받은 목록 전체를 폴링
크롤러의 `sync_site`와 완전히 동일한 로직(`sync_webhook_listing`)으로 처리합니다 - 신규/수정
판정은 같고, 삭제 판정만 다릅니다: 서버가 아카라이브에 직접 요청을 보낼 수 없어 개별 페이지로
재확인할 수 없으므로, 목록에서 쿨다운 기간(`crawl.deletion_check_cooldown_minutes`) 이상 계속
빠져 있으면 삭제로 간주합니다. 썸네일 이미지는 확장이 미리 받아오지 않습니다 - 어차피 서버가
신규로 확정한 글만 이미지가 필요한데 그건 확장이 스크랩하는 시점엔 알 수 없고, 서버의 기존
폴백(원본 썸네일 URL을 서버가 직접 요청 → 실패하면 URL을 텔레그램에 그대로 넘겨 텔레그램
서버가 대신 가져가게 함)으로 대부분 충분합니다.

**서버 설정**

1. `config.yaml`에서 `webhook.enabled: true`, `webhook.secret`에 긴 무작위 문자열을 채우고,
   `webhook.sites`에 확장이 담당할 사이트 키를 적습니다(예: `["arcalive"]`) — 이 목록에
   있어야 하트비트 끊김 감지 대상이 됩니다.
2. `sites.arcalive`는 **`enabled: true`로 켜둔 채** 유지하세요 — `enabled`는 폴링 루프뿐
   아니라 웹훅 수신 여부도 같이 결정하는 값이라(`db.get_site_enabled`), `false`로 끄면
   폴링 크롤러뿐 아니라 웹훅으로 들어오는 데이터도 전부 무시됩니다. 대신 폴링 크롤러가
   등록돼 있는 사이트(아카라이브처럼 이미 크롤러 코드가 있는 경우)는 Cloudflare에 계속
   막혀 매 사이클 실패하지만, 그 자체는 무해합니다(기존 `failure_alert_threshold` 알림만
   따로 옵니다) — 신경 쓰이면 `interval_seconds`를 크게(예: 3600) 잡아 요청 빈도만 줄이세요.

**확장 설정 및 설치**

1. `cp extension/config.example.js extension/config.js` 후, `WEBHOOK_BASE_URL`(봇 서버의
   `webapp.public_url`과 동일, 같은 도커 네트워크라면 컨테이너 이름으로도 가능)과
   `WEBHOOK_SECRET`(`config.yaml`의 `webhook.secret`과 동일)을 채웁니다. `extension/config.js`는
   시크릿이 들어있어 git에 커밋되지 않습니다.
2. Cloudflare를 이미 통과한 Firefox 세션(webtop 등)에 `extension/` 폴더를 임시 부가 기능으로
   로드합니다: `about:debugging` → "이 Firefox" → "임시 부가 기능 로드" → `manifest.json` 선택.
   (재부팅/컨테이너 재시작마다 다시 로드해야 합니다 — 영구 설치하려면 Firefox 엔터프라이즈
   정책(`policies.json`)의 `ExtensionSettings`로 서명되지 않은 확장을 허용하도록 설정해야
   합니다.)
3. 그 세션에서 감시하고 싶은 게시판(`https://arca.live/b/<게시판>`, 기존 핫딜이면
   `/b/hotdeal`)을 열어두고 계속 켜져 있게 둡니다. 게시판마다 서버 `config.yaml`의
   `sites:`에 같은 키(URL의 게시판 슬러그, 핫딜만 예외로 `arcalive`)로 항목이 있어야 합니다
   - 폴링 크롤러가 없는 사이트라도 등록만 해두면 웹훅 전용으로 동작합니다.

**동작 확인**

- 브라우저 콘솔(F12)에 `[arcalive-bridge] ...` 로그가 찍히면 확장이 정상 동작 중입니다.
  `listing empty/unparseable` 경고가 반복되면 `cf_clearance` 쿠키가 만료된 것일 수 있으니
  그 세션에서 페이지를 한 번 새로고침해 챌린지를 다시 통과시켜야 합니다.
- 서버의 `/status`(관리자 `/status` 명령)에서 해당 사이트의 "마지막 성공" 시각이 계속
  갱신되면 웹훅이 도착하고 있다는 뜻입니다 — 폴링을 꺼둔 사이트라도 웹훅/하트비트가
  `last_success_at`을 갱신합니다.
- 확장이 `webhook.heartbeat_stale_minutes`(기본 30분) 넘게 아무 신호도 안 보내면(하트비트
  포함) 관리자 채팅으로 경고가 갑니다 — 브라우저 세션이나 확장이 죽었을 가능성이 큽니다.

**보안 참고**: 웹훅 엔드포인트(`/webhook/{site}/article`, `/batch`, `/heartbeat`)는
`X-Webhook-Secret` 헤더가 `webhook.secret`과 정확히 일치해야만 요청을 받아들입니다
(`hmac.compare_digest`로 비교, 타이밍 공격 방지). `webhook.enabled`가 꺼져 있거나
`webhook.secret`이 비어 있으면 이 엔드포인트들은 항상 404를 반환합니다.

## 알려진 제약사항

- **가격/추천수**: 사이트가 가격을 별도 필드로 제공하면(아카라이브, 퀘이사존, 에펨코리아, 다모앙,
  쿨앤조이) 그 값을 그대로 사용합니다. 그렇지 않은 사이트(뽐뿌, 클리앙, 루리웹)는 제목에서
  정규식으로 가격을 추출하므로 100% 정확하지 않을 수 있습니다.
- **카테고리**: 사이트가 카테고리/분류를 제공하는 경우에만 표시됩니다(다모앙, zod는 목록에서
  카테고리를 제공하지 않아 항상 생략됩니다).
- **아카라이브**: Cloudflare 차단이 너무 강해 서버에서 실행하는 어떤 자동화 방식으로도 뚫리지
  않아, 폴링 크롤러 대신 브라우저 확장(`extension/`)이 웹훅으로 글을 밀어넣는 방식을 씁니다.
  자세한 설정은 위 "브라우저 확장으로 Cloudflare 우회" 절을 참고하세요.
- **퀘이사존/다모앙/zod**: Cloudflare 봇 차단이 걸려 있어 브라우저 TLS/HTTP2 핑거프린트를
  흉내내는 `curl_cffi`로 우회합니다. 서버 환경(특히 IP 평판)에 따라 다시 막힐 수 있고,
  Cloudflare 설정이 더 엄격한 사이트는 curl_cffi 흉내로도 못 뚫는 경우가 있습니다(직접
  헤드리스 브라우저로 우회를 시도해봤지만 이 수준의 차단에는 효과가 없었습니다). 계속
  막히면 `config.yaml`에서 `enabled: false`로 끄고 다른 사이트만 사용하세요.
- **에펨코리아**: 자체 "보안 시스템"이 있어 짧은 시간에 반복 요청하면 일시적으로 430 응답을
  돌려줄 수 있습니다. `interval_seconds`를 너무 짧게 잡지 마세요(기본값 60초 이상 권장).
  이 430 응답과 실제 "삭제됨"을 구분할 방법이 없어, 삭제 감지는 확실한 404일 때만 동작합니다
  (안전한 쪽으로 치우쳐 있어, 만약 오판이 있다면 "삭제를 못 잡아냄"이지 "잘못 삭제 처리"는 아닙니다).
- **이미지 화질**: 뽐뿌/아카라이브/퀘이사존은 목록 썸네일 URL을 가공해 원본 화질 이미지를 씁니다.
  나머지 사이트(에펨코리아/zod/쿨앤조이/루리웹/다모앙)는 목록 페이지 자체에 저화질 썸네일만
  있거나(에펨코리아/zod) 아예 이미지가 없어(쿨앤조이/루리웹/다모앙), 원본을 쓰려면 게시글마다
  상세 페이지를 추가로 요청해야 하므로 현재는 지원하지 않습니다.
- **이미지 비율 통일**: 세로/정사각형 썸네일이 대부분이라 메시지마다 높이가 들쭉날쭉해지는 걸
  막기 위해, 전송 전에 항상 16:9 캔버스(원본을 확대+블러한 배경 위에 중앙 배치)로 정규화합니다
  (`src/image_processing.py`, Pillow 사용). 세로로 아주 긴 사진은 원본 비율 그대로 축소하면
  폭이 너무 좁아져 내용이 작게 보이므로, 최대 50%까지는 상하 크롭을 허용해 조금 더 확대합니다.
  다운로드/처리에 실패하면 원본 URL로 폴백하며, 일부 사이트(퀘이사존 등)의 이미지 CDN은
  리퍼러 없는 요청을 핫링크 방지로 차단해 이미지가 안 나올 수 있어 요청 시 원본 사이트를
  리퍼러로 함께 보냅니다.
- **삭제 감지 요청 빈도**: 목록에서 사라진 글마다 매 사이클 개별 페이지를 새로 요청하면, 추적
  개수가 쌓일수록 요청도 늘어나 사이트의 비정상 접근 탐지에 걸려 크롤러 IP 자체가 차단될 수
  있습니다(실제로 개발 중 coolenjoy가 이런 패턴으로 IP를 차단한 사례가 있었습니다). 그래서
  한 번 확인한 글은 `deletion_check_cooldown_minutes`(기본 30분) 동안 재확인하지 않고,
  사이클당 확인 개수도 `max_deletion_checks_per_cycle`(기본 15개)로 제한합니다.
- **쇼핑몰 랭킹**: 대부분 제목 맨 앞 `[쇼핑몰]` 표기를 그대로 사용하는 휴리스틱이라, 사이트가
  이 표기를 카테고리 용도로 쓰면(예: 쿨앤조이의 `[기타]`) 잘못 잡힐 수 있어 알려진 오탐 값은
  걸러내고 있습니다(`src/price.py`의 `_MALL_DENYLIST`). 완벽하지 않을 수 있습니다.
- **종료/품절 감지**: 사이트가 구조화된 상태 뱃지를 제공하면(뽐뿌, 클리앙, 아카라이브, 다모앙,
  퀘이사존) 이를 사용하고, 그렇지 않으면(루리웹, 쿨앤조이, 에펨코리아) 제목에 "품절/종료/매진/마감"
  키워드가 있는지로 판단하는 best-effort 방식입니다.

## 설정 항목

`config.example.yaml`에 모든 옵션과 설명이 주석으로 포함되어 있습니다. 주요 항목:

| 항목 | 설명 | 기본값 |
|---|---|---|
| `crawl.listing_pages` | 사이트별로 한 번에 확인할 목록 페이지 수 | 2 |
| `crawl.retention_days` | 삭제 확인된 글의 DB 이력을 이 기간 후 정리 (살아있는 글은 지우지 않음) | 5 |
| `crawl.likes_edit_throttle_minutes` | 추천수만 바뀐 경우 메시지 수정 최소 간격(분) | 10 |
| `crawl.failure_alert_threshold` | 연속 실패 시 관리자 알림을 보내는 횟수 | 3 |
| `sites.<key>.interval_seconds` | 사이트별 크롤링 주기(초) | 60 |
| `digest.enabled` | 일일 다이제스트 사용 여부 | false |
| `digest.hour` / `digest.minute` | 다이제스트 전송 시각 (KST) | 9:00 |
| `digest.top_n` | 다이제스트에 보여줄 인기글 수 | 5 |
| `webapp.enabled` | 미니 웹앱 사용 여부 | false |
| `webapp.port` | 미니 웹앱 웹서버 포트 | 8080 |
| `webapp.public_url` | 미니 웹앱의 실제 HTTPS 주소 (nginx 등으로 연결) | (없음) |
| `webapp.short_name` | BotFather `/newapp`으로 등록한 Mini App 짧은 이름 (채널 메시지 버튼용) | (없음) |
| `webhook.enabled` | 브라우저 확장 웹훅 수신 여부 | false |
| `webhook.secret` | 확장의 `WEBHOOK_SECRET`과 일치해야 하는 인증 시크릿 | (없음) |
| `webhook.heartbeat_stale_minutes` | 이만큼(분) 확장 신호가 끊기면 관리자에게 경고 | 30 |
| `webhook.sites` | 하트비트 끊김 감지 대상 사이트 키 목록 (여기 없으면 신호가 끊겨도 경고 안 함) | `[]` |
| `display.show_site_name` | 메시지에 `[뽐뿌]` 같은 사이트명 접두사 표시 여부 | true |
| `display.webapp_button_label` / `webapp_title` / `webapp_empty_message` | 미니앱 관련 버튼/제목/빈 목록 문구 | 코드 참고 |
| `display.digest_header` / `digest_mall_ranking_label` | 다이제스트 헤더/쇼핑몰 랭킹 라벨 문구 | 코드 참고 |

`display.*`와 `crawl.*`, `digest.*` 항목은 관리자 `/settings` 명령으로도 재배포 없이 바로
편집할 수 있습니다 (위 "관리자 기능" 참고). `config.yaml` 값은 한 번도 편집하지 않았을 때만
쓰이는 기본값입니다.
