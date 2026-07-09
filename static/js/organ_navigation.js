// Territorial-organ and department navigation state.
function rememberSelectedOrgan(organId) {
  window.selectedOrgan = Number(organId);
  storeValue(ORGAN_STORAGE_KEY, String(window.selectedOrgan));
}

function findDepartmentBySlug(slug) {
  return Array.from(document.querySelectorAll(".department-item[data-department-slug]"))
    .find((item) => item.dataset.departmentSlug === slug);
}

function findOrganById(organId) {
  return Array.from(document.querySelectorAll(".organ-item[data-organ-id]"))
    .find((item) => item.dataset.organId === String(organId));
}

function rememberedSingleOrganId() {
  return window.selectedOrgan || storedValue(ORGAN_STORAGE_KEY);
}

function organSelectionMode() {
  return storedValue(ORGAN_MODE_KEY) === "multi" ? "multi" : "single";
}

function isMultiOrganMode() {
  return organSelectionMode() === "multi";
}

function checkedOrganIds() {
  return Array.from(document.querySelectorAll("[data-organ-checkbox]:checked")).map((input) => input.value);
}

function storeCheckedOrganIds() {
  storeValue(MULTI_ORGANS_KEY, checkedOrganIds().join(","));
  syncDashboardUrl();
}

function selectedOrganQueryString() {
  const params = new URLSearchParams();
  checkedOrganIds().forEach((id) => params.append("organ_ids", id));
  return params.toString();
}

function baseOrganIdForRequest() {
  return checkedOrganIds()[0] || window.selectedOrgan;
}

function loadOrganInfo(organId) {
  if (!organId || !window.htmx) return;
  window.htmx.ajax("GET", `/organs/${organId}/info/`, { target: "#organ-info", swap: "innerHTML" });
}

function renderMultiOrganInfo() {
  const target = document.getElementById("organ-info");
  if (!target) return;
  const count = checkedOrganIds().length;
  if (!count) {
    target.innerHTML = '<div class="empty-state">Выберите хотя бы один территориальный орган</div>';
    return;
  }
  target.innerHTML = `
    <div class="organ-info organ-info-summary">
      <div>
        <div class="small text-secondary">Сводный просмотр</div>
        <strong>Выбрано: ${count} территориальных органов</strong>
        <p class="mb-0 mt-2 text-secondary">Данные таблиц будут показаны по выбранным территориальным органам.</p>
      </div>
    </div>
  `;
}

function syncOrganModeButtons() {
  document.querySelectorAll("[data-organ-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.organMode === organSelectionMode());
  });
  const bulkActions = document.querySelector("[data-organ-bulk-actions]");
  if (bulkActions) bulkActions.hidden = !isMultiOrganMode();
  document.body.classList.toggle("is-multi-organ-mode", isMultiOrganMode());
}

function clearSingleOrganHighlight() {
  document.querySelectorAll("[data-organ-row], .organ-item").forEach((item) => {
    item.classList.remove("active");
    item.removeAttribute("aria-current");
  });
}

function restoreCheckedOrgans() {
  const saved = new Set((storedValue(MULTI_ORGANS_KEY) || "").split(",").filter(Boolean));
  document.querySelectorAll("[data-organ-checkbox]").forEach((checkbox) => {
    checkbox.checked = saved.has(checkbox.value);
  });
  return checkedOrganIds().length;
}

function clearActiveDepartment() {
  document.querySelectorAll(".department-item").forEach((item) => {
    item.classList.remove("active");
    item.removeAttribute("aria-current");
  });
}

function renderMultiOrganWorkspaceEmpty() {
  const workspace = document.getElementById("workspace");
  if (workspace) {
    workspace.innerHTML = '<div class="empty-state">Выберите хотя бы один территориальный орган</div>';
  }
}

function setOrganMode(mode) {
  const nextMode = mode === "multi" ? "multi" : "single";
  if (nextMode === "multi") {
    const activeOrgan = document.querySelector(".organ-item.active[data-organ-id]");
    if (activeOrgan) rememberSelectedOrgan(activeOrgan.dataset.organId);
  }
  storeValue(ORGAN_MODE_KEY, nextMode);
  if (isMultiOrganMode()) {
    clearSingleOrganHighlight();
    renderMultiOrganInfo();
  }
  syncOrganModeButtons();
  syncDashboardUrl();
}

function loadDepartment(department) {
  if (!department || !window.htmx) return;
  const departmentSlug = department.dataset.departmentSlug;
  if (isMultiOrganMode()) {
    const baseOrganId = baseOrganIdForRequest();
    const organQuery = selectedOrganQueryString();
    const query = departmentRequestQuery(departmentSlug);
    renderMultiOrganInfo();
    if (!baseOrganId || !organQuery) {
      clearActiveDepartment();
      document.getElementById("workspace").innerHTML = '<div class="empty-state">Выберите хотя бы один территориальный орган</div>';
      syncDashboardUrl();
      return;
    }
    storeValue(departmentStorageKey("multi"), departmentSlug);
    // Highlight here rather than in every caller, so the department panel
    // always matches whatever the workspace is actually showing.
    setActiveDepartment(department);
    const url = `/organs/${baseOrganId}/departments/${departmentSlug}/${query ? `?${query}` : ""}`;
    window.htmx.ajax("GET", url, { target: "#workspace", swap: "innerHTML" });
    syncDashboardUrl();
    return;
  }
  if (!window.selectedOrgan) {
    const activeOrgan = document.querySelector(".organ-item.active[data-organ-id]") || document.querySelector(".organ-item[data-organ-id]");
    window.selectedOrgan = activeOrgan ? Number(activeOrgan.dataset.organId) : null;
  }
  if (!window.selectedOrgan) return;
  storeValue(departmentStorageKey(window.selectedOrgan), departmentSlug);
  setActiveDepartment(department);
  const query = departmentRequestQuery(departmentSlug);
  const url = `/organs/${window.selectedOrgan}/departments/${departmentSlug}/${query ? `?${query}` : ""}`;
  window.htmx.ajax("GET", url, { target: "#workspace", swap: "innerHTML" });
  syncDashboardUrl();
}

function setActiveOrgan(organ) {
  document.querySelectorAll("[data-organ-row], .organ-item").forEach((item) => {
    item.classList.remove("active");
    item.removeAttribute("aria-current");
  });
  organ.closest("[data-organ-row]")?.classList.add("active");
  organ.classList.add("active");
  organ.setAttribute("aria-current", "true");
  rememberSelectedOrgan(organ.dataset.organId);
}

function setActiveDepartment(department) {
  const departments = department.closest(".department-list");
  if (departments) {
    departments.querySelectorAll(".department-item").forEach((item) => {
      item.classList.remove("active");
      item.removeAttribute("aria-current");
    });
  }
  department.classList.add("active");
  department.setAttribute("aria-current", "true");
}

// Deep-linking: mirror the dashboard navigation state into the URL query
// (?organ= / ?organs= / ?department= / ?table=) so views can be shared,
// bookmarked and survive refresh. URL params are applied by writing into the
// same localStorage keys the existing restore logic already reads, so
// restoring a link reuses the normal boot path instead of a parallel one.
// ?organs=all means "every organ available to the viewer" — it stays correct
// when new organs appear and keeps the address bar short. Partial lists use
// "-" as the separator because URLSearchParams percent-encodes commas.
const DASHBOARD_URL_PARAMS = ["organ", "organs", "department", "table"];
const DASHBOARD_SLUG_PATTERN = /^[\w-]+$/;

function allOrganCheckboxValues() {
  return Array.from(document.querySelectorAll("[data-organ-checkbox]")).map((input) => input.value);
}

function applyDashboardUrlState() {
  if (window.location.pathname !== "/") return;
  const params = new URLSearchParams(window.location.search);
  const organsParam = params.get("organs") || "";
  const organs = organsParam === "all"
    ? allOrganCheckboxValues()
    : organsParam.split(/[-,]/).filter((id) => /^\d+$/.test(id));
  const organ = /^\d+$/.test(params.get("organ") || "") ? params.get("organ") : "";
  const department = DASHBOARD_SLUG_PATTERN.test(params.get("department") || "") ? params.get("department") : "";
  const table = DASHBOARD_SLUG_PATTERN.test(params.get("table") || "") ? params.get("table") : "";
  if (!organs.length && !organ) return;
  if (organs.length) {
    storeValue(ORGAN_MODE_KEY, "multi");
    storeValue(MULTI_ORGANS_KEY, organs.join(","));
    if (department) storeValue(departmentStorageKey("multi"), department);
  } else {
    storeValue(ORGAN_MODE_KEY, "single");
    storeValue(ORGAN_STORAGE_KEY, organ);
    if (department) storeValue(departmentStorageKey(organ), department);
  }
  if (department && table) storeValue(departmentTableStorageKey(department), table);
}

function syncDashboardUrl() {
  if (window.location.pathname !== "/" || !window.history?.replaceState) return;
  const params = new URLSearchParams(window.location.search);
  DASHBOARD_URL_PARAMS.forEach((name) => params.delete(name));
  let department = "";
  if (isMultiOrganMode()) {
    const ids = checkedOrganIds();
    if (ids.length) {
      const everyOrganChecked = ids.length === allOrganCheckboxValues().length;
      params.set("organs", everyOrganChecked ? "all" : ids.join("-"));
    }
    department = storedValue(departmentStorageKey("multi")) || "";
  } else if (window.selectedOrgan) {
    params.set("organ", String(window.selectedOrgan));
    department = storedValue(departmentStorageKey(window.selectedOrgan)) || "";
  }
  if (department) {
    params.set("department", department);
    const table = storedValue(departmentTableStorageKey(department));
    if (table) params.set("table", table);
  }
  const query = params.toString();
  window.history.replaceState(window.history.state, "", query ? `/?${query}` : "/");
}

// dashboard_context() always server-renders the same default organ/department/
// table (see views.py), and that state is only ever reflected in the DOM
// through #table-area's own hx-get URL and the workspace's department-slug
// attribute (organ/department items never get an SSR "active" class). Reading
// it back lets initApp() compare the resolved localStorage state against what
// the server actually rendered, so a returning visitor whose saved state
// happens to match the default also skips the redundant re-fetch — not just
// a visitor with nothing saved at all.
function serverRenderedWorkspaceState() {
  const workspace = document.querySelector("[data-tables-workspace]");
  const tableArea = document.getElementById("table-area");
  if (!workspace || !tableArea) return null;
  const match = (tableArea.getAttribute("hx-get") || "").match(/\/organs\/(\d+)\/tables\/([^/?]+)\//);
  if (!match) return null;
  return { organId: match[1], departmentSlug: workspace.dataset.departmentSlug, tableKey: match[2] };
}

function preferredDepartmentForOrgan(organId) {
  if (isMultiOrganMode()) {
    const savedMultiSlug = storedValue(departmentStorageKey("multi"));
    if (savedMultiSlug) {
      const savedDepartment = findDepartmentBySlug(savedMultiSlug);
      if (savedDepartment) return savedDepartment;
    }
  }
  const savedSlug = storedValue(departmentStorageKey(organId));
  if (savedSlug) {
    const savedDepartment = findDepartmentBySlug(savedSlug);
    if (savedDepartment) return savedDepartment;
  }
  return document.querySelector(".department-item[data-department-slug]");
}
