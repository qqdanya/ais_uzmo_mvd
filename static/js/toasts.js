// Toast notifications and auto-dismissed alerts.
function autoDismissAlerts() {
  document.querySelectorAll(".alert[data-auto-dismiss]").forEach((alert) => {
    if (alert.dataset.dismissScheduled) return;
    alert.dataset.dismissScheduled = "true";
    const delay = Number(alert.dataset.autoDismiss) || 6000;
    window.setTimeout(() => {
      const instance = bootstrap.Alert.getOrCreateInstance(alert);
      instance.close();
    }, delay);
  });
}

function showToast(message, level = "success") {
  if (!message) return;
  const stack = document.querySelector(".toast-stack") || document.body.appendChild(document.createElement("div"));
  stack.classList.add("toast-stack");
  const toast = document.createElement("div");
  const alertLevel = level === "error" ? "danger" : level;
  toast.className = `app-toast alert alert-${alertLevel} alert-dismissible fade show`;
  toast.setAttribute("role", "alert");
  toast.dataset.autoDismiss = "5000";
  toast.append(document.createTextNode(message));
  const close = document.createElement("button");
  close.type = "button";
  close.className = "btn-close";
  close.dataset.bsDismiss = "alert";
  close.setAttribute("aria-label", "Закрыть");
  toast.append(close);
  stack.appendChild(toast);
  autoDismissAlerts();
}
window.autoDismissAlerts = autoDismissAlerts;
window.showToast = showToast;
