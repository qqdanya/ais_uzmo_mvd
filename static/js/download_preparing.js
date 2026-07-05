// Download preparation indicators for generated files.
var downloadPreparingNoticeTimer = null;
var DOWNLOAD_READY_COOKIE_PREFIX = "download-ready-";
var activeDownloads = new Map();

function showDownloadPreparingNotice(label) {
  const stack = document.querySelector(".toast-stack") || document.body.appendChild(document.createElement("div"));
  stack.classList.add("toast-stack");
  let notice = stack.querySelector("[data-download-preparing-notice]");
  if (!notice) {
    notice = document.createElement("div");
    notice.className = "app-toast download-preparing-notice alert alert-info show";
    notice.dataset.downloadPreparingNotice = "true";
    notice.setAttribute("role", "status");
    stack.appendChild(notice);
  }
  notice.replaceChildren();
  const spinner = document.createElement("span");
  spinner.className = "spinner-border spinner-border-sm";
  spinner.setAttribute("aria-hidden", "true");
  const content = document.createElement("span");
  content.className = "download-preparing-text";
  const title = document.createElement("strong");
  title.textContent = label;
  const hint = document.createElement("span");
  hint.textContent = "Файл начнет скачиваться автоматически.";
  content.append(title, hint);
  notice.append(spinner, content);
  window.clearTimeout(downloadPreparingNoticeTimer);
  downloadPreparingNoticeTimer = window.setTimeout(() => notice.remove(), 600000);
}

function hideDownloadPreparingNotice() {
  window.clearTimeout(downloadPreparingNoticeTimer);
  document.querySelector("[data-download-preparing-notice]")?.remove();
}

function refreshDownloadPreparingNotice() {
  const nextDownload = activeDownloads.values().next().value;
  if (nextDownload) {
    showDownloadPreparingNotice(nextDownload.label);
  } else {
    hideDownloadPreparingNotice();
  }
}

function isIconOnlyDownload(trigger) {
  return !trigger.textContent.trim();
}

function restorePreparingDownload(trigger) {
  if (!trigger?.dataset.downloadOriginalHtml) return;
  trigger.innerHTML = trigger.dataset.downloadOriginalHtml;
  trigger.classList.remove("is-preparing");
  trigger.classList.remove("is-preparing-icon");
  trigger.removeAttribute("aria-disabled");
  delete trigger.dataset.downloadOriginalHtml;
  delete trigger.dataset.downloadPreparingActive;
  delete trigger.dataset.downloadPreparingKey;
}

function downloadReadyCookieName(token) {
  return `${DOWNLOAD_READY_COOKIE_PREFIX}${token}`;
}

function hasCookie(name) {
  return document.cookie.split(";").some((item) => item.trim().startsWith(`${name}=`));
}

function clearCookie(name) {
  document.cookie = `${name}=; Max-Age=0; path=/`;
}

function downloadToken() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID().replace(/-/g, "");
  return `${Date.now()}${Math.random().toString(36).slice(2)}`;
}

function downloadUrlWithToken(href, token) {
  const url = new URL(href, window.location.href);
  url.searchParams.set("download_token", token);
  return url.toString();
}

function downloadKey(trigger) {
  if (trigger.dataset.downloadKey) return trigger.dataset.downloadKey;
  const url = new URL(trigger.href, window.location.href);
  url.searchParams.delete("download_token");
  return `${url.pathname}?${url.searchParams.toString()}`;
}

function restorePreparingDownloadsByKey(key) {
  document.querySelectorAll("a[data-download-preparing]").forEach((trigger) => {
    if (downloadKey(trigger) === key) restorePreparingDownload(trigger);
  });
}

function syncActiveDownloadButtons(root = document) {
  root.querySelectorAll?.("a[data-download-preparing]").forEach((trigger) => {
    const key = downloadKey(trigger);
    const active = activeDownloads.get(key);
    if (active && trigger.dataset.downloadPreparingActive !== "true") {
      markPreparingDownload(trigger, key, active.label);
    }
  });
}

function waitForDownloadStart(token, key) {
  const cookieName = downloadReadyCookieName(token);
  const startedAt = Date.now();
  const interval = window.setInterval(() => {
    if (hasCookie(cookieName)) {
      window.clearInterval(interval);
      clearCookie(cookieName);
      activeDownloads.delete(key);
      restorePreparingDownloadsByKey(key);
      refreshDownloadPreparingNotice();
      return;
    }
    if (Date.now() - startedAt > 600000) {
      window.clearInterval(interval);
      activeDownloads.delete(key);
      restorePreparingDownloadsByKey(key);
      refreshDownloadPreparingNotice();
    }
  }, 500);
}

function markPreparingDownload(trigger, key = downloadKey(trigger), label = null) {
  label = label || trigger.dataset.downloadPreparing || "Подготовка файла...";
  const iconOnly = isIconOnlyDownload(trigger);
  trigger.dataset.downloadOriginalHtml = trigger.innerHTML;
  trigger.dataset.downloadPreparingActive = "true";
  trigger.dataset.downloadPreparingKey = key;
  trigger.classList.add("is-preparing");
  trigger.setAttribute("aria-disabled", "true");
  trigger.replaceChildren();

  const spinner = document.createElement("span");
  spinner.className = "spinner-border spinner-border-sm";
  spinner.setAttribute("aria-hidden", "true");
  if (iconOnly) {
    trigger.classList.add("is-preparing-icon");
    trigger.append(spinner);
  } else {
    const text = document.createElement("span");
    text.textContent = label;
    trigger.append(spinner, text);
  }

  bootstrap.Tooltip.getInstance(trigger)?.hide();
  showDownloadPreparingNotice(label);
}

window.showDownloadPreparingNotice = showDownloadPreparingNotice;
window.hideDownloadPreparingNotice = hideDownloadPreparingNotice;
window.refreshDownloadPreparingNotice = refreshDownloadPreparingNotice;
window.restorePreparingDownload = restorePreparingDownload;
window.downloadToken = downloadToken;
window.downloadUrlWithToken = downloadUrlWithToken;
window.downloadKey = downloadKey;
window.syncActiveDownloadButtons = syncActiveDownloadButtons;
window.waitForDownloadStart = waitForDownloadStart;
window.markPreparingDownload = markPreparingDownload;
window.DownloadPreparing = {
  showDownloadPreparingNotice,
  hideDownloadPreparingNotice,
  refreshDownloadPreparingNotice,
  restorePreparingDownload,
  downloadToken,
  downloadUrlWithToken,
  downloadKey,
  syncActiveDownloadButtons,
  waitForDownloadStart,
  markPreparingDownload,
};
