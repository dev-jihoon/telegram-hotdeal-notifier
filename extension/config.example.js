// 이 파일을 config.js로 복사하고 실제 값으로 채우세요 (config.js는 git에 커밋되지 않습니다).
// cp config.example.js config.js

// 봇 서버의 공개 HTTPS 주소. config.yaml의 webapp.public_url과 동일한 값을 씁니다
// (nginx 등 리버스 프록시가 이미 그 포트로 연결되어 있으므로 그대로 재사용).
const WEBHOOK_BASE_URL = "https://your-domain.example.com";

// config.yaml의 webhook.secret과 반드시 동일해야 합니다. 아무 문자열이나 길고 무작위로.
const WEBHOOK_SECRET = "REPLACE_ME_WITH_LONG_RANDOM_STRING";
