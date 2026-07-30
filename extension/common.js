// 여러 사이트(아카라이브/zod 등)의 콘텐츠 스크립트가 공유하는 보일러플레이트.
// 사이트별 파일(arcalive_site.js, zod_site.js)은 parseListing(doc)만 정의해서
// runBridge()에 넘긴다 - register/heartbeat/스캔/전송/챌린지 신호는 여기서 한 번만
// 구현한다.
//
// 새로고침 스케줄링은 여기서 하지 않는다 - background.js의 alarms API가 담당한다
// (탭이 오래 백그라운드에 있으면 페이지 자체의 setTimeout이 브라우저에 의해 강하게
// 스로틀링되는 문제가 실측으로 확인돼서, alarms 기반으로 옮겼다). 이 파일은 로드될
// 때마다(최초 진입 + 매 새로고침마다) 자신을 background.js에 등록만 한다.
//
// 이미지는 여기서 미리 안 받아온다 - 어차피 서버가 신규로 확정한 글만 실제로 이미지가
// 필요한데, 그건 이 시점엔 알 수 없고, 서버의 기존 폴백(원본 썸네일 URL 직접 요청 →
// 실패 시 URL만 텔레그램에 넘겨 텔레그램 서버가 대신 가져가게 함)이 이미 있어 대부분
// 그걸로 충분하다.

function runBridge({ site, parseListing, logPrefix }) {
  function scanAndSend() {
    let articles;
    try {
      articles = parseListing(document);
    } catch (e) {
      console.error(`${logPrefix} [${site}] parse failed:`, e);
      return;
    }
    // 글 행을 하나도 못 찾으면 대부분 Cloudflare 챌린지가 다시 뜬 것이다(쿠키 만료 등 -
    // 브라우저 세션에서 수동으로 다시 통과시켜야 풀린다). 진짜 빈 목록으로 보내면 서버가
    // 기존 추적 글을 전부 "계속 안 보임"으로 오판할 수 있으므로 이번 사이클은 건너뛰되,
    // 서버에는 별도 신호를 보내 관리자에게 즉시 알리게 한다 - 하트비트는 계속 정상으로
    // 찍히므로(확장 자체는 살아있음) 30분 무신호 알림만으론 이 문제를 바로 못 잡는다.
    if (!articles || articles.length === 0) {
      console.warn(`${logPrefix} [${site}] listing empty/unparseable, skipping this cycle`);
      browser.runtime.sendMessage({ type: "challenge", site });
      return;
    }
    browser.runtime.sendMessage({ type: "batch", site, articles });
    console.log(`${logPrefix} [${site}] sent listing: ${articles.length} articles`);
  }

  browser.runtime.sendMessage({ type: "register", site });
  browser.runtime.sendMessage({ type: "heartbeat", site });
  scanAndSend();
  console.log(`${logPrefix} watching '${site}'`);
}
