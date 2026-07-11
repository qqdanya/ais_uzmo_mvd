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

let activeTooltipTrigger = null;
let tooltipShowTimer = null;
let tooltipPositionFrame = null;

function tooltipPortal() {
  let portal = document.getElementById("app-tooltip-portal");
  if (portal) return portal;
  portal = document.createElement("div");
  portal.id = "app-tooltip-portal";
  portal.className = "app-tooltip-portal";
  portal.setAttribute("role", "tooltip");
  portal.hidden = true;
  document.body.append(portal);
  return portal;
}

function tooltipPlacementOrder(trigger) {
  if (trigger.closest(".table-action-stack") || trigger.dataset.tooltipPlacement === "left") {
    return ["left", "right", "top", "bottom"];
  }
  if (trigger.classList.contains("navigation-float-toggle") || trigger.dataset.tooltipPlacement === "right") {
    return ["right", "bottom", "top", "left"];
  }
  if (trigger.dataset.tooltipPlacement === "bottom") return ["bottom", "top", "left", "right"];
  return ["top", "bottom", "left", "right"];
}

function tooltipCoordinates(placement, triggerRect, tooltipRect, gap) {
  if (placement === "bottom") {
    return { x: triggerRect.left + (triggerRect.width - tooltipRect.width) / 2, y: triggerRect.bottom + gap };
  }
  if (placement === "left") {
    return { x: triggerRect.left - tooltipRect.width - gap, y: triggerRect.top + (triggerRect.height - tooltipRect.height) / 2 };
  }
  if (placement === "right") {
    return { x: triggerRect.right + gap, y: triggerRect.top + (triggerRect.height - tooltipRect.height) / 2 };
  }
  return { x: triggerRect.left + (triggerRect.width - tooltipRect.width) / 2, y: triggerRect.top - tooltipRect.height - gap };
}

function positionTooltip() {
  tooltipPositionFrame = null;
  const trigger = activeTooltipTrigger;
  const portal = document.getElementById("app-tooltip-portal");
  if (!trigger?.isConnected || !portal || portal.hidden) {
    hideTooltip();
    return;
  }

  const triggerRect = trigger.getBoundingClientRect();
  const tooltipRect = portal.getBoundingClientRect();
  const margin = 8;
  const gap = 9;
  let selected = null;
  for (const placement of tooltipPlacementOrder(trigger)) {
    const point = tooltipCoordinates(placement, triggerRect, tooltipRect, gap);
    const fits = point.x >= margin
      && point.y >= margin
      && point.x + tooltipRect.width <= window.innerWidth - margin
      && point.y + tooltipRect.height <= window.innerHeight - margin;
    if (fits) {
      selected = { placement, ...point };
      break;
    }
    if (!selected) selected = { placement, ...point };
  }

  const maxX = Math.max(margin, window.innerWidth - tooltipRect.width - margin);
  const maxY = Math.max(margin, window.innerHeight - tooltipRect.height - margin);
  const x = Math.min(Math.max(selected.x, margin), maxX);
  const y = Math.min(Math.max(selected.y, margin), maxY);
  portal.dataset.placement = selected.placement;
  portal.style.left = `${Math.round(x)}px`;
  portal.style.top = `${Math.round(y)}px`;
  portal.style.setProperty("--tooltip-arrow-x", `${Math.round(triggerRect.left + triggerRect.width / 2 - x)}px`);
  portal.style.setProperty("--tooltip-arrow-y", `${Math.round(triggerRect.top + triggerRect.height / 2 - y)}px`);
}

function scheduleTooltipPosition() {
  if (!activeTooltipTrigger || tooltipPositionFrame) return;
  tooltipPositionFrame = window.requestAnimationFrame(positionTooltip);
}

function showTooltip(trigger) {
  const title = trigger.dataset.cssTooltip || trigger.getAttribute("data-bs-title") || trigger.getAttribute("title");
  if (!title) return;
  window.clearTimeout(tooltipShowTimer);
  tooltipShowTimer = window.setTimeout(() => {
    activeTooltipTrigger = trigger;
    const portal = tooltipPortal();
    portal.textContent = title;
    portal.hidden = false;
    portal.classList.remove("is-visible");
    trigger.setAttribute("aria-describedby", portal.id);
    positionTooltip();
    window.requestAnimationFrame(() => portal.classList.add("is-visible"));
  }, 300);
}

function hideTooltip(trigger = activeTooltipTrigger) {
  window.clearTimeout(tooltipShowTimer);
  tooltipShowTimer = null;
  if (trigger?.getAttribute("aria-describedby") === "app-tooltip-portal") {
    trigger.removeAttribute("aria-describedby");
  }
  const portal = document.getElementById("app-tooltip-portal");
  portal?.classList.remove("is-visible");
  if (portal) portal.hidden = true;
  activeTooltipTrigger = null;
}

function tooltipTriggerFromEvent(event) {
  return event.target instanceof Element ? event.target.closest('[data-bs-toggle="tooltip"]') : null;
}

function registerTooltipPortal() {
  if (document.documentElement.dataset.tooltipPortalRegistered) return;
  document.documentElement.dataset.tooltipPortalRegistered = "true";
  document.addEventListener("mouseover", (event) => {
    const trigger = tooltipTriggerFromEvent(event);
    if (trigger && !trigger.contains(event.relatedTarget)) showTooltip(trigger);
  });
  document.addEventListener("mouseout", (event) => {
    const trigger = tooltipTriggerFromEvent(event);
    if (trigger && !trigger.contains(event.relatedTarget)) hideTooltip(trigger);
  });
  document.addEventListener("focusin", (event) => {
    const trigger = tooltipTriggerFromEvent(event);
    if (trigger) showTooltip(trigger);
  });
  document.addEventListener("focusout", (event) => {
    const trigger = tooltipTriggerFromEvent(event);
    if (trigger) hideTooltip(trigger);
  });
  window.addEventListener("resize", scheduleTooltipPosition);
  document.addEventListener("scroll", scheduleTooltipPosition, true);
}

function initTooltips() {
  registerTooltipPortal();
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
    const title = el.getAttribute("data-bs-title") || el.getAttribute("title") || el.dataset.cssTooltip;
    if (!title) return;
    el.removeAttribute("title");
    el.removeAttribute("data-ui-tooltip");
    window.bootstrap?.Tooltip?.getInstance(el)?.dispose();
    el.dataset.cssTooltip = title;
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
window.initTooltips = initTooltips;
window.showToast = showToast;
