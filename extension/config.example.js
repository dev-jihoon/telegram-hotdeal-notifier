// 이 파일을 config.js로 복사하고 실제 값으로 채우세요 (config.js는 git에 커밋되지 않습니다).
// cp config.example.js config.js

// 봇 서버의 공개 HTTPS 주소. config.yaml의 webapp.public_url과 동일한 값을 씁니다
// (nginx 등 리버스 프록시가 이미 그 포트로 연결되어 있으므로 그대로 재사용).
const WEBHOOK_BASE_URL = "https://your-domain.example.com";

// config.yaml의 webhook.secret과 반드시 동일해야 합니다. 아무 문자열이나 길고 무작위로.
const WEBHOOK_SECRET = "REPLACE_ME_WITH_LONG_RANDOM_STRING";

// 이 확장은 https://arca.live/b/<게시판>을 열어두면 아무 게시판이나 감시합니다. 각
// 게시판은 URL의 게시판 슬러그(예: leagueoflegends)를 사이트 키로 써서 웹훅을 보내므로,
// 받는 쪽 서버의 config.yaml에도 sites.<같은 키>가 있어야 합니다 (기존 핫딜 게시판
// /b/hotdeal만 예외로 하위호환을 위해 "arcalive" 키를 그대로 씁니다).
