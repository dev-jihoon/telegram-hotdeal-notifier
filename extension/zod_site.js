// zod.kr의 핫딜 목록(https://zod.kr/deal)을 감시한다. 공통 보일러플레이트(등록/하트비트/
// 전송/챌린지 신호)는 common.js의 runBridge()가 담당한다 - 이 파일은 zod DOM에 맞는
// parseListing()만 정의한다.
//
// 셀렉터는 src/crawlers/zod.py의 _parse_listing()과 동일하게 유지한다 - 서버 파서와
// 결과가 어긋나면 같은 글이 다르게 보여서 계속 "변경됨"으로 오인될 수 있다.

(function () {
  // 개별 글 페이지(/deal/<id>)에서는 동작하지 않는다 - 목록 페이지(/deal)에서만 실행한다.
  if (location.pathname !== "/deal") return;

  const SITE = "zod";
  const ARTICLE_ID_RE = /\/deal\/(\d+)/;
  const END_KEYWORDS = ["품절", "종료", "매진", "마감"];

  function parseRow(row) {
    const link = row.querySelector("a");
    if (!link || !link.getAttribute("href")) return null;
    const href = link.getAttribute("href");
    // 스폰서 위젯(deal_partner) 블록은 실제 유저 게시글이 아니므로 건너뛴다.
    if (href.includes("deal_partner")) return null;
    const match = href.match(ARTICLE_ID_RE);
    if (!match) return null;
    const articleId = match[1];

    const titleTag = link.querySelector(".app-list-title-item");
    const title = titleTag ? titleTag.textContent.trim() : "";
    if (!title) return null;

    let status = "active";
    if (row.classList.contains("zod-board-list--deal-ended")) {
      status = "ended";
    } else if (END_KEYWORDS.some((kw) => title.includes(kw))) {
      status = "ended";
    }

    let price = null;
    let mall = null;
    let delivery = null;
    const metaList = link.querySelector(".app-list-meta.zod-board--deal-meta");
    if (metaList) {
      const dts = metaList.querySelectorAll("dt");
      const dds = metaList.querySelectorAll("dd");
      for (let i = 0; i < dts.length && i < dds.length; i++) {
        const label = dts[i].textContent.trim();
        const strong = dds[i].querySelector("strong");
        const value = strong ? strong.textContent.trim() : dds[i].textContent.trim();
        if (label.includes("홈페이지") || label.includes("장소")) mall = value;
        else if (label.includes("가격")) price = value;
        else if (label.includes("배송비")) delivery = value;
      }
    }

    let likes = null;
    const likesTag = link.querySelector(".app-list__voted-count");
    if (likesTag) {
      const text = likesTag.textContent.trim();
      if (/^\d+$/.test(text)) likes = parseInt(text, 10);
    }

    const thumb = link.querySelector(".app-thumbnail img");
    const thumbnailUrl = thumb && thumb.getAttribute("src") ? thumb.getAttribute("src") : null;

    return {
      article_id: articleId,
      title,
      url: `https://zod.kr/deal/${articleId}`,
      price,
      likes,
      delivery,
      mall,
      status,
      thumbnail_url: thumbnailUrl,
    };
  }

  function parseListing(doc) {
    const listTag = doc.querySelector("#board-list .zod-board-list--deal");
    if (!listTag) return [];
    const articles = [];
    for (const row of listTag.querySelectorAll("li")) {
      const article = parseRow(row);
      if (article) articles.push(article);
    }
    return articles;
  }

  runBridge({ site: SITE, parseListing, logPrefix: "[zod-bridge]" });
})();
