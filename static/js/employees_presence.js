// Employees: live online/offline refresh without page reload.
function updateClassWithPrefix(element, prefix, value) {
  if (!element) return;
  [...element.classList].forEach((className) => {
    if (className.startsWith(prefix)) element.classList.remove(className);
  });
  element.classList.add(`${prefix}${value}`);
}

function markPresenceUpdated(element) {
  if (!element) return;
  element.classList.remove("admin-presence-updated");
  // Force reflow so repeated updates replay the subtle pulse.
  void element.offsetWidth;
  element.classList.add("admin-presence-updated");
}

async function refreshEmployeesPresence() {
  const screen = document.querySelector("[data-employees-presence-url]");
  if (!screen || document.hidden) return;
  const url = screen.dataset.employeesPresenceUrl;
  if (!url) return;
  try {
    const response = await fetch(url, {
      method: "GET",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    if (!response.ok) return;
    const payload = await response.json();
    Object.entries(payload.kpis || {}).forEach(([key, value]) => {
      const target = document.querySelector(`[data-employees-kpi="${key}"]`);
      if (target && target.textContent.trim() !== String(value)) {
        target.textContent = value;
        markPresenceUpdated(target.closest(".admin-requests-kpi-card") || target);
      }
    });
    Object.entries(payload.tabs || {}).forEach(([key, value]) => {
      const target = document.querySelector(`[data-employees-tab-count="${key}"]`);
      if (target && target.textContent.trim() !== String(value)) {
        target.textContent = value;
        markPresenceUpdated(target);
      }
    });
    (payload.employees || []).forEach((employee) => {
      document.querySelectorAll(`[data-employee-activity="${employee.id}"]`).forEach((activity) => {
        if (activity.textContent.trim() !== employee.activity_label) markPresenceUpdated(activity);
        activity.textContent = employee.activity_label;
        updateClassWithPrefix(activity, "is-", employee.activity_state);
      });
      document.querySelectorAll(`[data-employee-last-seen="${employee.id}"]`).forEach((lastSeen) => {
        if (lastSeen.textContent.trim() !== employee.last_seen) markPresenceUpdated(lastSeen);
        lastSeen.textContent = employee.last_seen;
      });
      document.querySelectorAll(`[data-employee-activation="${employee.id}"]`).forEach((activation) => {
        activation.textContent = employee.activation_label;
        updateClassWithPrefix(activation, "is-", employee.activation_state);
      });
    });
  } catch (error) {
    // Presence refresh is opportunistic; keep the page usable if the request fails.
  }
}

function startEmployeesPresenceRefresh() {
  if (!document.querySelector("[data-employees-presence-url]")) return;
  refreshEmployeesPresence();
  window.setInterval(refreshEmployeesPresence, 30000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshEmployeesPresence();
  });
}

document.addEventListener("DOMContentLoaded", startEmployeesPresenceRefresh);
