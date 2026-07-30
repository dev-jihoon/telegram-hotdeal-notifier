// 에펨코리아 핫딜 목록(https://www.fmkorea.com/hotdeal)을 감시한다. 공통 보일러플레이트
// (등록/하트비트/전송/챌린지 신호)는 common.js의 runBridge()가 담당한다 - 이 파일은
// 에펨코리아 DOM에 맞는 parseListing()만 정의한다.
//
// 에펨코리아 자체 "보안 시스템"이 Cloudflare Turnstile을 쓰는 걸 응답 HTML에서 확인했다
// (challenges.cloudflare.com/turnstile 스크립트 로드) - IP 자체를 막는 게 아니라
// 브라우저 세션/쿠키 기반 챌린지라, 아카라이브/zod와 동일한 방식이 통한다.
//
// 셀렉터는 src/crawlers/fmkorea.py의 _parse_listing()과 동일하게 유지한다 - 서버 파서와
// 결과가 어긋나면 같은 글이 다르게 보여서 계속 "변경됨"으로 오인될 수 있다.

(function () {
  // 목록 페이지(/hotdeal)에서만 동작한다 - 개별 글 페이지는 /<숫자 id> 형태라 경로가 다르다.
  if (location.pathname !== "/hotdeal") return;

  const SITE = "fmkorea";
  const END_KEYWORDS = ["품절", "종료", "매진", "마감"];
  const PRICE_RE = /(\d{1,3}(?:,\d{3})+|\d{4,})\s*원/g;

  function extractPriceFromTitle(title) {
    const matches = [...title.matchAll(PRICE_RE)];
    if (matches.length === 0) return null;
    // "정가 → 할인가"처럼 여러 개면 마지막(보통 최종가)을 쓴다 - Python extract_price()와 동일.
    return matches[matches.length - 1][0];
  }

  function parseRow(row) {
    const titleH3 = row.querySelector("h3.title");
    if (!titleH3) return null;
    const titleLink = titleH3.querySelector("a");
    if (!titleLink || !titleLink.getAttribute("href")) return null;
    const href = titleLink.getAttribute("href").replace(/^\/+/, "");
    if (!/^\d+$/.test(href)) return null;
    const articleId = href;

    const titleSpan = titleLink.querySelector(".ellipsis-target");
    let title;
    if (titleSpan) {
      title = titleSpan.textContent.trim();
    } else {
      let text = "";
      for (const node of titleLink.childNodes) {
        if (node.nodeType === Node.TEXT_NODE) text += node.textContent;
      }
      title = text.trim();
    }
    if (!title) return null;

    let status = "active";
    if (END_KEYWORDS.some((kw) => title.includes(kw))) status = "ended";

    let likes = null;
    const voteTag = row.querySelector(".pc_voted_count .count");
    if (voteTag) {
      const text = voteTag.textContent.trim();
      if (/^-?\d+$/.test(text)) likes = parseInt(text, 10);
    }

    let price = null;
    let mall = null;
    let delivery = null;
    for (const span of row.querySelectorAll(".hotdeal_info span")) {
      const text = span.textContent;
      const link = span.querySelector("a");
      if (!link) continue;
      if (text.includes("가격")) price = link.textContent.trim();
      else if (text.includes("쇼핑몰")) mall = link.textContent.trim();
      else if (text.includes("배송")) delivery = link.textContent.trim();
    }
    if (price === null) price = extractPriceFromTitle(title);

    let thumbnailUrl = null;
    const thumbTag = row.querySelector("img.thumb");
    if (thumbTag) {
      const src = thumbTag.getAttribute("data-original") || thumbTag.getAttribute("src");
      if (src && !src.includes("transparent.gif")) {
        thumbnailUrl = src.startsWith("//") ? `https:${src}` : src;
      }
    }

    const categoryTag = row.querySelector(".category a");
    const category = categoryTag ? categoryTag.textContent.trim() : null;

    return {
      article_id: articleId,
      title,
      url: `https://www.fmkorea.com/${articleId}`,
      price,
      likes,
      delivery,
      mall,
      category,
      status,
      thumbnail_url: thumbnailUrl,
    };
  }

  function parseListing(doc) {
    const articles = [];
    for (const row of doc.querySelectorAll("#content .fm_best_widget ul li")) {
      const article = parseRow(row);
      if (article) articles.push(article);
    }
    return articles;
  }

  runBridge({ site: SITE, parseListing, logPrefix: "[fmkorea-bridge]" });
})();
