// 아카라이브의 아무 게시판 목록(https://arca.live/b/<board>)이나 감시한다. 핫딜(/b/hotdeal)
// 전용 필드(가격/배송/쇼핑몰/종료뱃지) 셀렉터는 src/crawlers/arcalive.py의 _parse_listing()과
// 동일하게 유지하되, 다른 게시판엔 해당 요소가 아예 없으므로 항상 null로 자연스럽게 빠진다.

(function () {
  // 게시글 상세 페이지(/b/<board>/<id>)에서는 동작하지 않는다 - 목록 페이지(/b/<board>,
  // 페이지네이션 쿼리 포함)에서만 실행한다.
  const boardMatch = location.pathname.match(/^\/b\/([\w\d]+)\/?$/);
  if (!boardMatch) return;

  // 기존에 "arcalive"라는 사이트 키로 이미 배포되어 있던 핫딜 게시판만 하위호환을 위해
  // 그대로 "arcalive"를 쓰고, 그 외 게시판은 URL의 게시판 슬러그를 그대로 사이트 키로
  // 쓴다 (서버 config.yaml의 sites.<키>와 이름이 일치해야 한다).
  const SITE_ALIASES = { hotdeal: "arcalive" };
  const BOARD_SLUG = boardMatch[1];
  const SITE = SITE_ALIASES[BOARD_SLUG] || BOARD_SLUG;
  const LOG_PREFIX = "[arcalive-bridge]";
  const HEARTBEAT_INTERVAL_MS = 5 * 60 * 1000; // 5분
  const seen = new Set();

  function waitForElement(selector, timeoutMs = 15000) {
    return new Promise((resolve) => {
      const existing = document.querySelector(selector);
      if (existing) {
        resolve(existing);
        return;
      }
      const observer = new MutationObserver(() => {
        const el = document.querySelector(selector);
        if (el) {
          observer.disconnect();
          resolve(el);
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
      setTimeout(() => {
        observer.disconnect();
        resolve(document.querySelector(selector));
      }, timeoutMs);
    });
  }

  function parseRow(row) {
    // 썸네일 있는 "카드형" 게시판(아카라이브에서 hybrid 클래스가 붙음, 핫딜 게시판 등)은
    // a.title.hybrid-title을, 썸네일 없는 일반 텍스트 게시판은 a.title만 씁니다.
    const titleTag = row.querySelector("a.title.hybrid-title") || row.querySelector("a.title");
    if (!titleTag || !titleTag.getAttribute("href")) return null;
    const href = titleTag.getAttribute("href");
    const match = href.match(/\/b\/([\w\d]+)\/(\d+)/);
    if (!match) return null;
    const boardId = match[1];
    const articleId = match[2];

    // 직계 텍스트 노드만 모은다(뱃지 등 자식 요소 텍스트는 제외) - Python의
    // find_all(string=True, recursive=False)와 동일한 취지.
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

  async function fetchImageBase64(url) {
    if (!url) return null;
    try {
      const res = await fetch(url);
      if (!res.ok) return null;
      const blob = await res.blob();
      return await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result); // "data:image/...;base64,...."
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(blob);
      });
    } catch (e) {
      return null;
    }
  }

  // isInitialBatch가 true면(페이지 최초 스캔) 이미지를 안 받아온다 - 서버가 이 배치를
  // 조용히 기준선으로만 저장하고 전송하지 않으므로 이미지가 필요 없고, 수십 개를 한꺼번에
  // 받아오면 느려지기만 한다.
  async function handleRow(row, isInitialBatch) {
    const article = parseRow(row);
    if (!article || seen.has(article.article_id)) return null;
    seen.add(article.article_id);
    if (!isInitialBatch) {
      article.image_base64 = await fetchImageBase64(article.thumbnail_url);
    }
    return article;
  }

  async function scanInitialBatch(table) {
    const rows = table.querySelectorAll(".vrow");
    const articles = [];
    for (const row of rows) {
      const article = await handleRow(row, true);
      if (article) articles.push(article);
    }
    if (articles.length > 0) {
      browser.runtime.sendMessage({ type: "batch", site: SITE, articles });
      console.log(`${LOG_PREFIX} [${SITE}] initial batch sent: ${articles.length} articles`);
    }
  }

  function observeNewRows(table) {
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (!(node instanceof HTMLElement)) continue;
          const rows = node.matches?.(".vrow")
            ? [node]
            : Array.from(node.querySelectorAll?.(".vrow") || []);
          for (const row of rows) {
            handleRow(row, false).then((article) => {
              if (!article) return;
              browser.runtime.sendMessage({ type: "article", site: SITE, article });
              console.log(`${LOG_PREFIX} [${SITE}] new article sent: ${article.article_id} ${article.title}`);
            });
          }
        }
      }
    });
    observer.observe(table, { childList: true, subtree: true });
  }

  async function main() {
    const table = await waitForElement(".list-table");
    if (!table) {
      console.error(`${LOG_PREFIX} [${SITE}] .list-table not found - page layout may have changed`);
      return;
    }
    await scanInitialBatch(table);
    observeNewRows(table);
    setInterval(() => {
      browser.runtime.sendMessage({ type: "heartbeat", site: SITE });
    }, HEARTBEAT_INTERVAL_MS);
    console.log(`${LOG_PREFIX} watching arca.live board '${SITE}'`);
  }

  main();
})();
