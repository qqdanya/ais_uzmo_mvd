// Header/footer sizing and collapsible dashboard panels.
function syncHeaderHeight() {
  const header = document.querySelector(".app-header");
  const footer = document.querySelector(".app-footer");
  if (header) {
    document.documentElement.style.setProperty("--app-header-height", `${Math.ceil(header.getBoundingClientRect().height)}px`);
  }
  if (footer) {
    document.documentElement.style.setProperty("--app-footer-height", `${Math.ceil(footer.getBoundingClientRect().height)}px`);
  }
}

function readCollapsedPanels() {
  try {
    const state = JSON.parse(localStorage.getItem(COLLAPSED_PANELS_KEY)) || {};
    if (state.navigation !== undefined) {
      state.organs = Boolean(state.navigation);
      if (state.navigation) state.departments = true;
      delete state.navigation;
      writeCollapsedPanels(state);
    }
    return state;
  } catch {
    return {};
  }
}

function writeCollapsedPanels(state) {
  localStorage.setItem(COLLAPSED_PANELS_KEY, JSON.stringify(state));
}

let dashboardPanelAnimationRunning = false;

function panelRect(element) {
  if (!element) return null;
  const rect = element.getBoundingClientRect();
  return rect.width && rect.height ? rect : null;
}

function flipPanelElement(element, firstRect, duration = 440) {
  const lastRect = panelRect(element);
  if (!firstRect || !lastRect || typeof element.animate !== "function") return null;
  const deltaX = firstRect.left - lastRect.left;
  const scaleX = firstRect.width / lastRect.width;
  if (Math.abs(deltaX) < .5 && Math.abs(scaleX - 1) < .001) return null;
  return element.animate(
    [
      { transform: `translateX(${deltaX}px) scaleX(${scaleX})`, transformOrigin: "left center" },
      { transform: "translateX(0) scaleX(1)", transformOrigin: "left center" },
    ],
    { duration, easing: "cubic-bezier(.4, 0, .2, 1)" },
  );
}

async function toggleCollapsedPanel(panel) {
  if (dashboardPanelAnimationRunning) return;
  const grid = document.getElementById("dashboard-grid");
  if (!grid || !["organs", "departments"].includes(panel)) return;
  const state = readCollapsedPanels();
  const collapsing = !Boolean(state[panel]);
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const targetPanel = grid.querySelector(panel === "organs" ? ".organ-panel" : ".department-panel");
  const workspace = grid.querySelector(".workspace-panel");
  const organPanel = grid.querySelector(".organ-panel");
  const departmentPanel = grid.querySelector(".department-panel");
  const canAnimate = !reduceMotion && typeof workspace?.animate === "function";

  dashboardPanelAnimationRunning = true;
  grid.classList.add("is-panel-animating");
  try {
    if (canAnimate && collapsing && targetPanel) {
      const fadeOut = targetPanel.animate(
        [{ opacity: 1, transform: "translateX(0)" }, { opacity: 0, transform: "translateX(-18px)" }],
        { duration: 180, easing: "ease-in", fill: "forwards" },
      );
      await fadeOut.finished.catch(() => {});
      fadeOut.cancel();
    }

    const firstRects = {
      workspace: panelRect(workspace),
      organs: panelRect(organPanel),
      departments: panelRect(departmentPanel),
    };
    state[panel] = collapsing;
    writeCollapsedPanels(state);
    applyCollapsedPanels();

    if (!canAnimate) return;
    const animations = [
      flipPanelElement(workspace, firstRects.workspace),
      flipPanelElement(organPanel, firstRects.organs),
      flipPanelElement(departmentPanel, firstRects.departments),
    ].filter(Boolean);
    if (!collapsing && targetPanel) {
      animations.push(targetPanel.animate(
        [{ opacity: 0, transform: "translateX(-18px)" }, { opacity: 1, transform: "translateX(0)" }],
        { duration: 360, easing: "ease-out" },
      ));
    }
    await Promise.all(animations.map((animation) => animation.finished.catch(() => {})));
  } finally {
    grid.classList.remove("is-panel-animating");
    dashboardPanelAnimationRunning = false;
  }
}

function applyCollapsedPanels() {
  const grid = document.getElementById("dashboard-grid");
  if (!grid) return;
  const state = readCollapsedPanels();
  const organsCollapsed = Boolean(state.organs);
  const departmentsCollapsed = Boolean(state.departments);
  grid.classList.toggle("is-organs-collapsed", organsCollapsed);
  grid.classList.toggle("is-departments-collapsed", departmentsCollapsed);
  document.querySelectorAll("[data-panel-toggle]").forEach((button) => {
    const panel = button.dataset.panelToggle;
    if (!["organs", "departments"].includes(panel)) return;
    const collapsed = panel === "organs" ? organsCollapsed : departmentsCollapsed;
    button.classList.toggle("active", collapsed);
    button.setAttribute("aria-pressed", String(collapsed));
    const isFloatingToggle = button.classList.contains("navigation-float-toggle");
    let title;
    if (isFloatingToggle) {
      title = "Показать территориальные органы";
    } else if (panel === "organs") {
      title = organsCollapsed ? "Показать территориальные органы" : "Свернуть территориальные органы";
    } else {
      title = departmentsCollapsed ? "Показать отделы" : "Свернуть отделы";
    }
    button.setAttribute("data-bs-title", title);
    button.setAttribute("aria-label", title);
    const icon = button.querySelector("i");
    if (icon) {
      icon.className = `bi ${collapsed ? "bi-chevron-right" : "bi-chevron-left"}`;
    }
  });
  initTooltips();
}
