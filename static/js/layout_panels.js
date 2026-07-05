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
