// config.js가 먼저 로드되어 WEBHOOK_BASE_URL, WEBHOOK_SECRET 전역 변수를 정의해둔다.
// 콘텐츠 스크립트는 시크릿을 직접 들고 있지 않고(페이지 컨텍스트에 더 가까워서), 여기
// 백그라운드에서만 시크릿을 붙여 실제 요청을 보낸다.
//
// 하트비트는 사이트마다(게시판마다) 다르므로 여기서 고정된 사이트로 독자적으로 보내지
// 않는다 - 각 게시판을 감시 중인 content_script.js가 자기 사이트 키로 직접 보낸다.

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
      console.error(`[arcalive-bridge] ${site}/${path} failed: ${res.status} ${await res.text()}`);
    }
    return res.ok;
  } catch (e) {
    console.error(`[arcalive-bridge] ${site}/${path} error:`, e);
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
