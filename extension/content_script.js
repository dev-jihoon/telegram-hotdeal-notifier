// 아카라이브의 아무 게시판 목록(https://arca.live/b/<board>)이나 감시한다.
//
// 처음엔 웹소켓으로 목록이 실시간 갱신될 거라 가정하고 MutationObserver로 새 글만
// 감지하는 방식으로 만들었는데, 실측해보니 목록 자체는 새로고침 없이 갱신되지 않았다.
// 그다음엔 탭은 그대로 두고 fetch()로 같은 URL을 주기적으로 다시 받아오는 방식으로
// 바꿨는데, 이것도 실측해보니 Cloudflare가 콘텐츠 스크립트의 fetch() 요청만 따로
// 403으로 막았다(같은 브라우저/쿠키인데도 일반 페이지 이동과는 다르게 취급됨). 그래서
// 지금은 아예 location.reload()로 진짜 페이지 이동을 매번 일으킨다 - 이러면 매 새로고침마다
// 콘텐츠 스크립트가 처음부터 다시 실행되므로, 그 시점에 라이브 문서를 한 번 스캔해 보내고
// 다음 새로고침을 예약하는 식으로 폴링 루프를 흉내낸다. 신규/수정/삭제 판정은 서버가
// (다른 사이트의 폴링 크롤러와 완전히 동일한 로직으로) 처리한다 - 그래서 이미지도 여기서
// 미리 안 받아온다: 어차피 서버가 신규로 확정한 글만 실제로 이미지가 필요한데, 그건 이
// 시점엔 알 수 없고, 서버의 기존 폴백(원본 썸네일 URL 직접 요청 → 실패 시 URL만 텔레그램에
// 넘겨 텔레그램 서버가 대신 가져가게 함)이 이미 있어 대부분 그걸로 충분하다.
//
// 셀렉터는 src/crawlers/arcalive.py의 _parse_listing()과 최대한 동일하게 유지한다 -
// 서버 파서와 결과가 어긋나면 같은 글이 다르게 보여서 계속 "변경됨"으로 오인될 수 있다.
// 핫딜(/b/hotdeal) 전용 필드(가격/배송/쇼핑몰/종료뱃지) 셀렉터는 다른 게시판엔 해당
// 요소가 아예 없으므로 항상 null로 자연스럽게 빠진다.

(function () {
  // 게시글 상세 페이지(/b/<board>/<id>)에서는 동작하지 않는다 - 목록 페이지(/b/<board>)
  // 에서만 실행한다.
  const boardMatch = location.pathname.match(/^\/b\/([\w\d]+)\/?$/);
  if (!boardMatch) return;

  // 기존에 "arcalive"라는 사이트 키로 이미 배포되어 있던 핫딜 게시판만 하위호환을 위해
  // 그대로 "arcalive"를 쓰고, 그 외 게시판은 URL의 게시판 슬러그를 그대로 사이트 키로
  // 쓴다 (서버 config.yaml의 sites.<키>와 이름이 일치해야 한다).
  const SITE_ALIASES = { hotdeal: "arcalive" };
  const BOARD_SLUG = boardMatch[1];
  const SITE = SITE_ALIASES[BOARD_SLUG] || BOARD_SLUG;
  const LOG_PREFIX = "[arcalive-bridge]";
  const RELOAD_INTERVAL_MS = 60 * 1000; // 1분 - 폴링 크롤러들의 기본 interval_seconds와 맞춤

  function parseRow(row) {
    // 게시판 종류마다 행 구조 자체가 다르다(실측 확인):
    // - 썸네일 있는 "카드형"(hybrid, 핫딜 등): <div class="vrow hybrid">가 행이고, 그 안에
    //   <a class="title hybrid-title" href="...">가 따로 있다.
    // - 썸네일 없는 일반 텍스트 게시판: <a class="vrow column" href="...">가 행 자체이고
    //   (별도의 title 링크가 없다), 제목 텍스트는 그 안의 <span class="title">에 들어있다.
    // 그래서 링크는 "행 자체가 a면 그걸, 아니면 안에서 찾기"로, 제목은 태그 종류와 무관하게
    // class="title"인 요소를 찾아서 처리한다.
    const linkTag = row.tagName === "A" && row.getAttribute("href")
      ? row
      : row.querySelector("a.title.hybrid-title") || row.querySelector("a[href]");
    if (!linkTag) return null;
    const href = linkTag.getAttribute("href");
    const match = href.match(/\/b\/([\w\d]+)\/(\d+)/);
    if (!match) return null;
    const boardId = match[1];
    const articleId = match[2];

    // 직계 텍스트 노드만 모은다(뱃지/아이콘 등 자식 요소 텍스트는 제외) - Python의
    // find_all(string=True, recursive=False)와 동일한 취지.
    const titleTag = row.querySelector(".title") || linkTag;
    let title = "";
    for (const node of titleTag.childNodes) {
      if (node.nodeType === Node.TEXT_NODE) title += node.textContent;
    }
    title = title.trim();
    if (!title) return null;

    const status = row.querySelector(".deal-close") ? "ended" : "active";

    let likes = null;
    const rateTag = row.querySelector(".col-rate");
    if (rateTag) {
      const text = rateTag.textContent.trim();
      if (/^-?\d+$/.test(text)) likes = parseInt(text, 10);
    }

    const priceTag = row.querySelector(".deal-price");
    const price = priceTag ? priceTag.textContent.trim() : null;

    const deliveryTag = row.querySelector(".deal-delivery");
    const delivery = deliveryTag ? deliveryTag.textContent.trim() : null;

    const mallTag = row.querySelector(".deal-store");
    const mall = mallTag ? mallTag.textContent.trim() : null;

    const categoryTag = row.querySelector(".badge");
    const category = categoryTag ? categoryTag.textContent.trim() : null;

    let thumbnailUrl = null;
    const thumbTag = row.querySelector(".vrow-preview img");
    if (thumbTag && thumbTag.getAttribute("src")) {
      let src = thumbTag.getAttribute("src");
      if (src.startsWith("//")) src = "https:" + src;
      // 'type=list'(저화질 목록용) 파라미터를 제거해 원본 화질을 받는다 - Python
      // _drop_list_size()와 동일한 취지.
      try {
        const u = new URL(src);
        u.searchParams.delete("type");
        thumbnailUrl = u.toString();
      } catch (e) {
        thumbnailUrl = src;
      }
    }

    return {
      article_id: articleId,
      title,
      url: `https://arca.live/b/${boardId}/${articleId}`,
      price,
      likes,
      delivery,
      mall,
      category,
      status,
      thumbnail_url: thumbnailUrl,
    };
  }

  // 컨테이너로 스코핑하지 않고 문서 전체에서 이 조합으로 글 행을 바로 찾는다 - 오픈소스
  // 아카라이브 확장 "Arca Refresher"(src/core/selector.jsx의 BOARD_ITEMS)가 실제로 쓰는
  // 셀렉터를 그대로 따른 것이다. 처음엔 .list-table로 스코핑했는데, 페이지에 다른 목적의
  // list-table(사이드바 위젯 등)이 더 있어서 엉뚱한 걸 잡아 실제 게시판에서 0건이
  // 나오는 걸 실측으로 확인했다. 공지(.notice)와 헤더 행(.head)은 제외한다.
  const BOARD_ITEMS_SELECTOR = ".vrow.column:not(.notice):not(.head), .vrow.hybrid";

  function parseListing(doc) {
    const articles = [];
    for (const row of doc.querySelectorAll(BOARD_ITEMS_SELECTOR)) {
      const article = parseRow(row);
      if (article) articles.push(article);
    }
    return articles;
  }

  function scanAndSend() {
    let articles;
    try {
      articles = parseListing(document);
    } catch (e) {
      console.error(`${LOG_PREFIX} [${SITE}] parse failed:`, e);
      return;
    }
    // 글 행을 하나도 못 찾으면 대부분 Cloudflare 챌린지가 다시 뜬 것이다(cf_clearance
    // 쿠키 만료 등 - 브라우저 세션에서 수동으로 다시 통과시켜야 풀린다). 진짜 빈 목록으로
    // 보내면 서버가 기존 추적 글을 전부 "계속 안 보임"으로 오판할 수 있으므로 이번
    // 사이클은 건너뛰되, 서버에는 별도 신호를 보내 관리자에게 즉시 알리게 한다 - 하트비트는
    // 계속 정상으로 찍히므로(확장 자체는 살아있음) 30분 무신호 알림만으론 이 문제를
    // 바로 못 잡는다.
    if (!articles || articles.length === 0) {
      console.warn(`${LOG_PREFIX} [${SITE}] listing empty/unparseable, skipping this cycle`);
      browser.runtime.sendMessage({ type: "challenge", site: SITE });
      return;
    }
    browser.runtime.sendMessage({ type: "batch", site: SITE, articles });
    console.log(`${LOG_PREFIX} [${SITE}] sent listing: ${articles.length} articles`);
  }

  function main() {
    browser.runtime.sendMessage({ type: "heartbeat", site: SITE });
    scanAndSend();
    // 콘텐츠 스크립트는 새로고침마다 처음부터 다시 실행되므로, 다음 사이클의 타이머는
    // 그 새 실행에서 또 새로 건다 - 별도의 반복 setInterval이 필요 없다.
    setTimeout(() => location.reload(), RELOAD_INTERVAL_MS);
    console.log(`${LOG_PREFIX} watching arca.live board '${SITE}' (reloading every ${RELOAD_INTERVAL_MS / 1000}s)`);
  }

  main();
})();
