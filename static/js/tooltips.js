// One body-level tooltip engine for the whole application.
//
// The IIFE is intentional. An older cached toasts.js used global `let`
// declarations with some of the same names; keeping this module scoped means
// a mixed old/new browser cache cannot make the entire file fail to parse.
(() => {
  "use strict";

  const TRIGGER_SELECTOR = '[data-bs-toggle="tooltip"]';
  const SHOW_DELAY_MS = 300;
  const VIEWPORT_MARGIN = 8;
  const TRIGGER_GAP = 9;
  const MAX_WIDTH = 240;

  let activeTrigger = null;
  let pendingTrigger = null;
  let showTimer = null;
  let trackingFrame = null;

  function tooltipElements() {
    let layer = document.getElementById("app-tooltip-layer");
    let bubble = document.getElementById("app-tooltip-portal");

    if (!layer) {
      layer = document.createElement("div");
      layer.id = "app-tooltip-layer";
      layer.className = "app-tooltip-layer";
      layer.hidden = true;
      document.body.append(layer);
    }

    if (!bubble) {
      bubble = document.createElement("div");
      bubble.id = "app-tooltip-portal";
      bubble.className = "app-tooltip-portal";
      bubble.setAttribute("role", "tooltip");
      bubble.hidden = true;
    }

    // Also repairs a portal created by an older hot-loaded implementation.
    if (bubble.parentElement !== layer) layer.append(bubble);
    return { layer, bubble };
  }

  function tooltipTitle(trigger) {
    const title = trigger.getAttribute("data-bs-title")
      || trigger.getAttribute("title")
      || trigger.dataset.tooltipTitle
      || "";
    trigger.removeAttribute("title");
    if (title) trigger.dataset.tooltipTitle = title;
    return title;
  }

  function placementOrder(trigger) {
    // Table buttons deliberately use the normal top placement. At the last
    // column the bubble is shifted horizontally while its arrow remains over
    // the button; changing the whole placement to `left` is the sideways jump
    // that was especially noticeable below 100% browser zoom.
    const preferred = trigger.dataset.tooltipPlacement
      || (trigger.classList.contains("navigation-float-toggle") && "right")
      || "top";
    const orders = {
      top: ["top", "bottom", "left", "right"],
      bottom: ["bottom", "top", "left", "right"],
      left: ["left", "right", "top", "bottom"],
      right: ["right", "left", "top", "bottom"],
    };
    return orders[preferred] || orders.top;
  }

  function pointFor(placement, triggerRect, bubbleRect) {
    const centeredX = triggerRect.left + (triggerRect.width - bubbleRect.width) / 2;
    const centeredY = triggerRect.top + (triggerRect.height - bubbleRect.height) / 2;
    if (placement === "bottom") return { x: centeredX, y: triggerRect.bottom + TRIGGER_GAP };
    if (placement === "left") return { x: triggerRect.left - bubbleRect.width - TRIGGER_GAP, y: centeredY };
    if (placement === "right") return { x: triggerRect.right + TRIGGER_GAP, y: centeredY };
    return { x: centeredX, y: triggerRect.top - bubbleRect.height - TRIGGER_GAP };
  }

  function mainAxisOverflow(placement, point, bubbleRect, bounds) {
    if (placement === "top") return Math.max(0, bounds.top - point.y);
    if (placement === "bottom") return Math.max(0, point.y + bubbleRect.height - bounds.bottom);
    if (placement === "left") return Math.max(0, bounds.left - point.x);
    return Math.max(0, point.x + bubbleRect.width - bounds.right);
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), Math.max(min, max));
  }

  function positionTooltip() {
    const trigger = activeTrigger;
    const layer = document.getElementById("app-tooltip-layer");
    const bubble = document.getElementById("app-tooltip-portal");
    if (!trigger?.isConnected || !layer || layer.hidden || !bubble || bubble.hidden) {
      if (activeTrigger) hideTooltip();
      return;
    }

    // The fixed layer is the source of truth for coordinates. Both it and the
    // trigger are measured by getBoundingClientRect(), then trigger coordinates
    // are converted to layer-local values. This remains one coordinate system
    // under browser zoom, OS scaling and fractional device-pixel ratios.
    const layerRect = layer.getBoundingClientRect();
    // Use only the layer's own measured box for both axes. Mixing this box
    // with documentElement.clientWidth/Height looks harmless at 100%, but the
    // two can be rounded on different pixel grids below 100% zoom. A trigger
    // near the last table column was then incorrectly treated as off-screen.
    const bounds = {
      left: VIEWPORT_MARGIN,
      top: VIEWPORT_MARGIN,
      right: layerRect.width - VIEWPORT_MARGIN,
      bottom: layerRect.height - VIEWPORT_MARGIN,
    };
    const availableWidth = Math.max(1, bounds.right - bounds.left);
    bubble.style.maxWidth = `${Math.max(16, Math.min(MAX_WIDTH, availableWidth))}px`;

    const viewportTriggerRect = trigger.getBoundingClientRect();
    const triggerRect = {
      left: viewportTriggerRect.left - layerRect.left,
      top: viewportTriggerRect.top - layerRect.top,
      right: viewportTriggerRect.right - layerRect.left,
      bottom: viewportTriggerRect.bottom - layerRect.top,
      width: viewportTriggerRect.width,
      height: viewportTriggerRect.height,
    };

    const measuredBubble = bubble.getBoundingClientRect();
    const bubbleRect = { width: measuredBubble.width, height: measuredBubble.height };
    let selected = null;

    // A placement flips only when it lacks room on its main axis. Overflow on
    // the cross axis is handled by shifting. Thus a tooltip over a last-column
    // button remains above that button instead of jumping to its left at a
    // particular zoom threshold.
    for (const placement of placementOrder(trigger)) {
      const point = pointFor(placement, triggerRect, bubbleRect);
      const overflow = mainAxisOverflow(placement, point, bubbleRect, bounds);
      const candidate = { placement, point, overflow };
      if (!selected || overflow < selected.overflow) selected = candidate;
      if (overflow === 0) {
        selected = candidate;
        break;
      }
    }

    const x = clamp(selected.point.x, bounds.left, bounds.right - bubbleRect.width);
    const y = clamp(selected.point.y, bounds.top, bounds.bottom - bubbleRect.height);
    bubble.dataset.placement = selected.placement;
    // Preserve fractional CSS pixels. Rounding here amplified drift at zoom
    // levels whose CSS pixels map to fractional device pixels.
    bubble.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    bubble.style.setProperty("--tooltip-arrow-x", `${triggerRect.left + triggerRect.width / 2 - x}px`);
    bubble.style.setProperty("--tooltip-arrow-y", `${triggerRect.top + triggerRect.height / 2 - y}px`);
  }

  function trackTooltip() {
    trackingFrame = null;
    if (!activeTrigger) return;
    positionTooltip();
    if (activeTrigger) trackingFrame = window.requestAnimationFrame(trackTooltip);
  }

  function scheduleTracking() {
    if (!activeTrigger || trackingFrame) return;
    trackingFrame = window.requestAnimationFrame(trackTooltip);
  }

  function showTooltip(trigger) {
    if (trigger === activeTrigger || trigger === pendingTrigger) return;
    const title = tooltipTitle(trigger);
    if (!title) return;
    hideTooltip();
    pendingTrigger = trigger;
    showTimer = window.setTimeout(() => {
      showTimer = null;
      pendingTrigger = null;
      if (!trigger.isConnected) return;

      activeTrigger = trigger;
      const { layer, bubble } = tooltipElements();
      bubble.textContent = title;
      layer.hidden = false;
      bubble.hidden = false;
      bubble.classList.remove("is-visible");
      trigger.setAttribute("aria-describedby", bubble.id);
      positionTooltip();
      void bubble.offsetWidth;
      bubble.classList.add("is-visible");
      scheduleTracking();
    }, SHOW_DELAY_MS);
  }

  function hideTooltip(trigger = null) {
    if (trigger && trigger !== activeTrigger && trigger !== pendingTrigger) return;
    window.clearTimeout(showTimer);
    showTimer = null;
    pendingTrigger = null;
    if (trackingFrame) window.cancelAnimationFrame(trackingFrame);
    trackingFrame = null;
    activeTrigger?.removeAttribute("aria-describedby");
    activeTrigger = null;

    const layer = document.getElementById("app-tooltip-layer");
    const bubble = document.getElementById("app-tooltip-portal");
    if (bubble) {
      bubble.classList.remove("is-visible");
      bubble.hidden = true;
    }
    if (layer) layer.hidden = true;
  }

  function triggerFromEvent(event) {
    return event.target instanceof Element ? event.target.closest(TRIGGER_SELECTOR) : null;
  }

  function registerTooltipEvents() {
    if (document.documentElement.dataset.tooltipsRegistered) return;
    document.documentElement.dataset.tooltipsRegistered = "true";
    document.addEventListener("mouseover", (event) => {
      const trigger = triggerFromEvent(event);
      if (trigger && !(event.relatedTarget instanceof Node && trigger.contains(event.relatedTarget))) {
        showTooltip(trigger);
      }
    });
    document.addEventListener("mouseout", (event) => {
      const trigger = triggerFromEvent(event);
      if (trigger && !(event.relatedTarget instanceof Node && trigger.contains(event.relatedTarget))) {
        hideTooltip(trigger);
      }
    });
    document.addEventListener("focusin", (event) => {
      const trigger = triggerFromEvent(event);
      if (trigger) showTooltip(trigger);
    });
    document.addEventListener("focusout", (event) => {
      const trigger = triggerFromEvent(event);
      if (trigger) hideTooltip(trigger);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") hideTooltip();
    });
    window.addEventListener("resize", scheduleTracking);
    document.addEventListener("scroll", scheduleTracking, true);
  }

  function initTooltips() {
    registerTooltipEvents();

    document.querySelectorAll(TRIGGER_SELECTOR).forEach((trigger) => {
      // Dispose a Bootstrap instance left behind by an older cached script.
      // Without this, two independently positioned bubbles can be visible.
      window.bootstrap?.Tooltip?.getInstance(trigger)?.dispose();
      tooltipTitle(trigger);
    });

    if (!activeTrigger) return;
    if (!activeTrigger.isConnected) {
      hideTooltip();
      return;
    }
    const bubble = document.getElementById("app-tooltip-portal");
    const title = tooltipTitle(activeTrigger);
    if (!title) hideTooltip();
    else if (bubble && !bubble.hidden) {
      bubble.textContent = title;
      scheduleTracking();
    }
  }

  window.initTooltips = initTooltips;
  window.hideAppTooltip = hideTooltip;

  // Register independently of app.js so a failure in an unrelated module
  // cannot silently fall back to native/Bootstrap tooltips.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTooltips, { once: true });
  } else {
    initTooltips();
  }
})();
