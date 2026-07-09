// Presence ping: keeps the authenticated user's activity timestamp fresh.
const PRESENCE_HEARTBEAT_MS = 30000;

function cookieValue(name) {
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`))
    ?.slice(name.length + 1) || "";
}

function sendPresencePing() {
  const url = document.body?.dataset.presenceUrl;
  if (!url) return;
  fetch(url, {
    method: "POST",
    credentials: "same-origin",
    keepalive: true,
    headers: {
      "X-CSRFToken": decodeURIComponent(cookieValue("csrftoken")),
      "X-Requested-With": "XMLHttpRequest",
    },
  }).catch(() => {});
}

function startPresenceHeartbeat() {
  if (!document.body?.dataset.presenceUrl) return;
  if (window.__presenceHeartbeatStarted) return;
  window.__presenceHeartbeatStarted = true;
  sendPresencePing();
  window.setInterval(sendPresencePing, PRESENCE_HEARTBEAT_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) sendPresencePing();
  });
}

document.addEventListener("DOMContentLoaded", startPresenceHeartbeat);

window.startPresenceHeartbeat = startPresenceHeartbeat;
