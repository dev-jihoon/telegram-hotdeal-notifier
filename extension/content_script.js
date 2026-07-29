// 아카라이브 핫딜 목록(https://arca.live/b/hotdeal)을 감시한다.
// 셀렉터는 src/crawlers/arcalive.py의 _parse_listing()과 반드시 동일하게 유지해야 한다 -
// 서버 파서와 결과가 어긋나면 같은 글이 다르게 보여서 계속 "새 글"로 오인될 수 있다.

(function () {
  const SITE = "arcalive";
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
    const titleTag = row.querySelector("a.title.hybrid-title");
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
    const rows = table.querySelectorAll(".vrow.hybrid");
    const articles = [];
    for (const row of rows) {
      const article = await handleRow(row, true);
      if (article) articles.push(article);
    }
    if (articles.length > 0) {
      browser.runtime.sendMessage({ type: "batch", site: SITE, articles });
      console.log(`[hotdeal-bridge] initial batch sent: ${articles.length} articles`);
    }
  }

  function observeNewRows(table) {
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (!(node instanceof HTMLElement)) continue;
          const rows = node.matches?.(".vrow.hybrid")
            ? [node]
            : Array.from(node.querySelectorAll?.(".vrow.hybrid") || []);
          for (const row of rows) {
            handleRow(row, false).then((article) => {
              if (!article) return;
              browser.runtime.sendMessage({ type: "article", site: SITE, article });
              console.log(`[hotdeal-bridge] new article sent: ${article.article_id} ${article.title}`);
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
      console.error("[hotdeal-bridge] .list-table not found - page layout may have changed");
      return;
    }
    await scanInitialBatch(table);
    observeNewRows(table);
    setInterval(() => {
      browser.runtime.sendMessage({ type: "heartbeat", site: SITE });
    }, HEARTBEAT_INTERVAL_MS);
    console.log("[hotdeal-bridge] watching arcalive hotdeal list");
  }

  main();
})();
