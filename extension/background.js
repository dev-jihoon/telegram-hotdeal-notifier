// config.js가 먼저 로드되어 WEBHOOK_BASE_URL, WEBHOOK_SECRET 전역 변수를 정의해둔다.
// 콘텐츠 스크립트는 시크릿을 직접 들고 있지 않고(페이지 컨텍스트에 더 가까워서), 여기
// 백그라운드에서만 시크릿을 붙여 실제 요청을 보낸다.

const HEARTBEAT_INTERVAL_MS = 5 * 60 * 1000; // 5분

async function postWebhook(site, path, body) {
  try {
    const res = await fetch(`${WEBHOOK_BASE_URL}/webhook/${site}/${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Webhook-Secret": WEBHOOK_SECRET,
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      console.error(`[hotdeal-bridge] ${site}/${path} failed: ${res.status} ${await res.text()}`);
    }
    return res.ok;
  } catch (e) {
    console.error(`[hotdeal-bridge] ${site}/${path} error:`, e);
    return false;
  }
}

browser.runtime.onMessage.addListener((msg) => {
  if (!msg || !msg.site) return;
  if (msg.type === "batch") {
    return postWebhook(msg.site, "batch", { articles: msg.articles });
  }
  if (msg.type === "article") {
    return postWebhook(msg.site, "article", msg.article);
  }
  if (msg.type === "heartbeat") {
    return postWebhook(msg.site, "heartbeat", {});
  }
});

// 콘텐츠 스크립트가 (탭이 백그라운드로 밀려도) 계속 하트비트를 보내도록 여기서도
// 독립적으로 한 번 더 주기적으로 보낸다 - "확장 자체는 살아있다"는 최소 신호.
setInterval(() => {
  postWebhook("arcalive", "heartbeat", {});
}, HEARTBEAT_INTERVAL_MS);
