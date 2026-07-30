// config.js가 먼저 로드되어 WEBHOOK_BASE_URL, WEBHOOK_SECRET 전역 변수를 정의해둔다.
// 콘텐츠 스크립트는 시크릿을 직접 들고 있지 않고(페이지 컨텍스트에 더 가까워서), 여기
// 백그라운드에서만 시크릿을 붙여 실제 요청을 보낸다.
//
// 하트비트는 사이트마다(게시판마다) 다르므로 여기서 고정된 사이트로 독자적으로 보내지
// 않는다 - 각 게시판을 감시 중인 content_script.js가 자기 사이트 키로 직접 보낸다.

const RELOAD_ALARM_NAME = "arcalive-bridge-reload";

// 감시 중인 탭 id -> 사이트 키. content_script.js가 로드될 때마다 "register"로
// 자기 자신을 등록한다 - 새로고침으로 매번 스크립트가 다시 실행되므로 여기서 매번
// 갱신되고, 탭이 닫히면 onRemoved로 정리된다.
const watchedTabs = new Map();

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

browser.runtime.onMessage.addListener((msg, sender) => {
  if (!msg || !msg.site) return;
  if (msg.type === "register" && sender.tab) {
    watchedTabs.set(sender.tab.id, msg.site);
    return;
  }
  if (msg.type === "batch") {
    return postWebhook(msg.site, "batch", { articles: msg.articles });
  }
  if (msg.type === "heartbeat") {
    return postWebhook(msg.site, "heartbeat", {});
  }
  if (msg.type === "challenge") {
    return postWebhook(msg.site, "challenge", {});
  }
});

browser.tabs.onRemoved.addListener((tabId) => watchedTabs.delete(tabId));

// content_script.js 자체의 setTimeout/location.reload()는 탭이 (noVNC 세션에 아무도
// 접속해 있지 않는 등) 백그라운드로 오래 머무르면 브라우저가 타이머를 강하게 스로틀링해서
// 안 돌 때가 있었다(웹탑에 실제로 들어가야 그제서야 밀린 게 한꺼번에 처리됨). 확장의
// alarms API는 탭 가시성과 무관하게 계속 정확히 발화하므로, 새로고침 자체를 여기
// 백그라운드에서 예약한다.
browser.alarms.create(RELOAD_ALARM_NAME, { periodInMinutes: 1 });
browser.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== RELOAD_ALARM_NAME) return;
  for (const tabId of watchedTabs.keys()) {
    browser.tabs.reload(tabId).catch(() => watchedTabs.delete(tabId));
  }
});
