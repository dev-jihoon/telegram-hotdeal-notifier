// 아카라이브의 아무 게시판 목록(https://arca.live/b/<board>)이나 감시한다.
// 공통 보일러플레이트(등록/하트비트/전송/챌린지 신호)는 common.js의 runBridge()가
// 담당한다 - 이 파일은 아카라이브 DOM에 맞는 parseListing()만 정의한다.
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

  runBridge({ site: SITE, parseListing, logPrefix: "[arcalive-bridge]" });
})();
