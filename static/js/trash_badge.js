(() => {
  let refreshPromise = null;

  function refreshTrashCount() {
    const link = document.querySelector("[data-trash-menu-link]");
    const badge = link?.querySelector("[data-trash-menu-count]");
    const url = link?.dataset.trashCountUrl;
    if (!badge || !url) return Promise.resolve();
    if (refreshPromise) return refreshPromise;
    refreshPromise = fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => {
        if (!payload) return;
        const count = Number(payload.count) || 0;
        badge.textContent = String(count);
        badge.hidden = count === 0;
      })
      .finally(() => { refreshPromise = null; });
    return refreshPromise;
  }

  document.addEventListener("htmx:afterRequest", (event) => {
    const method = String(event.detail?.requestConfig?.verb || "GET").toUpperCase();
    if (event.detail?.successful && method !== "GET") refreshTrashCount();
  });
  window.refreshTrashCount = refreshTrashCount;
})();
