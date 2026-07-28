(function () {
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  const listEl = document.getElementById("deal-list");
  const statusEl = document.getElementById("status");

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function openLink(url) {
    if (tg && tg.openLink) {
      tg.openLink(url);
    } else {
      window.open(url, "_blank");
    }
  }

  function renderDeal(deal) {
    const card = document.createElement("a");
    card.className = "deal-card";
    card.href = deal.url;
    card.addEventListener("click", (e) => {
      e.preventDefault();
      openLink(deal.url);
    });

    const tags = [deal.site_label, deal.mall, deal.category].filter(Boolean).join(" · ");

    const priceHtml = deal.price
      ? `<span>${escapeHtml(deal.price)}</span>` +
        (deal.discount_pct ? `<span class="deal-discount">-${deal.discount_pct}%</span>` : "")
      : "";

    const metaParts = [];
    if (deal.likes !== null && deal.likes !== undefined) metaParts.push(`👍 ${deal.likes}`);
    if (deal.delivery) metaParts.push(`🚚 ${escapeHtml(deal.delivery)}`);

    card.innerHTML = `
      <img class="deal-thumb" src="${deal.thumbnail_url || ""}" onerror="this.style.visibility='hidden'" alt="">
      <div class="deal-info">
        <div class="deal-tags">${escapeHtml(tags)}</div>
        <div class="deal-title">${escapeHtml(deal.title)}</div>
        <div class="deal-price-row">${priceHtml}</div>
        <div class="deal-meta">${metaParts.join(" · ")}</div>
      </div>
    `;
    return card;
  }

  async function loadDeals() {
    try {
      const res = await fetch("/api/deals", {
        headers: { "X-Telegram-Init-Data": (tg && tg.initData) || "" },
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      listEl.innerHTML = "";
      if (!data.deals || data.deals.length === 0) {
        statusEl.textContent = "오늘 올라온 핫딜이 아직 없습니다.";
        listEl.appendChild(statusEl);
        return;
      }
      data.deals.forEach((deal) => listEl.appendChild(renderDeal(deal)));
    } catch (err) {
      statusEl.textContent = "불러오지 못했습니다. 잠시 후 다시 시도해주세요.";
      listEl.innerHTML = "";
      listEl.appendChild(statusEl);
      console.error(err);
    }
  }

  loadDeals();
})();
