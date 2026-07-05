window.selectedOrgan = window.selectedOrgan || null;
const ORGAN_STORAGE_KEY = "asu-zmo:selected-organ";
const ORGAN_MODE_KEY = "asu-zmo:organ-mode";
const MULTI_ORGANS_KEY = "asu-zmo:multi-organs";
const DEPARTMENT_STORAGE_PREFIX = "asu-zmo:last-department:";
const DEPARTMENT_TABLE_PREFIX = "asu-zmo:last-table:";
const TABLE_STATE_PREFIX = "asu-zmo:table-state:";
const COLLAPSED_PANELS_KEY = "asu-zmo:collapsed-panels";
const PRESENCE_HEARTBEAT_MS = 30000;
let htmxRequests = 0;
let loadingFailsafeTimer = null;
function storedValue(key) {
  try {
    return localStorage.getItem(key) ?? sessionStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function storeValue(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    try {
      sessionStorage.setItem(key, value);
    } catch (fallbackError) {
      // Browser storage can be unavailable in strict privacy modes.
    }
  }
}

function removeStoredValue(key) {
  try {
    localStorage.removeItem(key);
    sessionStorage.removeItem(key);
  } catch (error) {
    // Nothing to clean up when storage is unavailable.
  }
}

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
  sendPresencePing();
  window.setInterval(sendPresencePing, PRESENCE_HEARTBEAT_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) sendPresencePing();
  });
}

function formatLocalDateTime(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function rememberSelectedOrgan(organId) {
  window.selectedOrgan = Number(organId);
  storeValue(ORGAN_STORAGE_KEY, String(window.selectedOrgan));
}

function departmentStorageKey(organId) {
  return `${DEPARTMENT_STORAGE_PREFIX}${organId}`;
}

function departmentTableStorageKey(departmentSlug) {
  return `${DEPARTMENT_TABLE_PREFIX}${departmentSlug}`;
}

function tableStateStorageKey(departmentSlug, tableKey) {
  return `${TABLE_STATE_PREFIX}${departmentSlug}:${tableKey}`;
}

function activeDepartmentSlug() {
  return document.querySelector("[data-tables-workspace]")?.dataset.departmentSlug
    || document.querySelector(".department-item.active[data-department-slug]")?.dataset.departmentSlug
    || "";
}

function savedTableKeyForDepartment(departmentSlug) {
  const savedKey = storedValue(departmentTableStorageKey(departmentSlug));
  if (savedKey) return savedKey;
  return findTableTab(departmentSlug)?.dataset.tableKey || "";
}

function savedTableQuery(departmentSlug, tableKey) {
  return storedValue(tableStateStorageKey(departmentSlug, tableKey)) || "";
}

function currentTableDateDefaults(scope = document) {
  const form = scope.querySelector?.("[data-table-filter-form]") || document.querySelector("[data-table-filter-form]");
  if (!form) return {};
  return {
    dateFrom: form.dataset.defaultDateFrom || "",
    dateTo: form.dataset.defaultDateTo || "",
  };
}

function normalizeSavedTableParams(params, defaults = {}) {
  params.delete("page");
  params.delete("table");
  params.delete("organ_ids");
  if (params.get("date_from") === defaults.dateFrom) params.delete("date_from");
  if (params.get("date_to") === defaults.dateTo) params.delete("date_to");
  return params;
}

function withCurrentOrganSelection(params) {
  params.delete("organ_ids");
  if (isMultiOrganMode()) {
    checkedOrganIds().forEach((id) => params.append("organ_ids", id));
  }
  return params;
}

function findTableTab(departmentSlug, tableKey = "") {
  const workspace = document.querySelector(`[data-tables-workspace][data-department-slug="${CSS.escape(departmentSlug)}"]`);
  const selector = tableKey ? `[data-table-tab="true"][data-table-key="${CSS.escape(tableKey)}"]` : '[data-table-tab="true"][data-table-key]';
  return workspace?.querySelector(selector) || null;
}

function departmentRequestQuery(departmentSlug) {
  const tableKey = savedTableKeyForDepartment(departmentSlug);
  const params = normalizeSavedTableParams(new URLSearchParams(savedTableQuery(departmentSlug, tableKey)));
  if (tableKey) params.set("table", tableKey);
  return withCurrentOrganSelection(params).toString();
}

function tableUrlWithSavedState(tab) {
  const departmentSlug = tab.closest("[data-tables-workspace]")?.dataset.departmentSlug || activeDepartmentSlug();
  const tableKey = tab.dataset.tableKey;
  if (!departmentSlug || !tableKey) return tab.getAttribute("hx-get");
  const url = new URL(tab.getAttribute("hx-get"), window.location.href);
  const params = normalizeSavedTableParams(new URLSearchParams(savedTableQuery(departmentSlug, tableKey)));
  withCurrentOrganSelection(params);
  url.search = params.toString();
  return `${url.pathname}${url.search}`;
}

function saveTableStateFromUrl(urlValue, scope = document) {
  if (!urlValue) return;
  const departmentSlug = activeDepartmentSlug();
  if (!departmentSlug) return;
  const url = new URL(urlValue, window.location.href);
  const match = url.pathname.match(/\/organs\/\d+\/tables\/([^/]+)\//);
  if (!match) return;
  const tableKey = match[1];
  const params = normalizeSavedTableParams(url.searchParams, currentTableDateDefaults(scope));
  storeValue(departmentTableStorageKey(departmentSlug), tableKey);
  storeValue(tableStateStorageKey(departmentSlug, tableKey), params.toString());
}

function isResetTableStateTrigger(element) {
  return Boolean(element?.closest?.("[data-reset-table-state]"));
}

function saveTableStateFromHtmxEvent(event) {
  if (event.detail?.target?.id !== "table-area") return;
  if (isResetTableStateTrigger(event.detail?.requestConfig?.elt)) {
    clearCurrentTableState();
    return;
  }
  const url = event.detail?.xhr?.responseURL || event.detail?.requestConfig?.path;
  saveTableStateFromUrl(url, event.detail.target);
}

function clearCurrentTableState() {
  const departmentSlug = activeDepartmentSlug();
  const tableKey = document.querySelector('[data-table-tab="true"].active[data-table-key]')?.dataset.tableKey;
  if (!departmentSlug || !tableKey) return;
  removeStoredValue(tableStateStorageKey(departmentSlug, tableKey));
}

function clearOrganSelectionFromDepartmentTableStates(departmentSlug = activeDepartmentSlug()) {
  if (!departmentSlug) return;
  document.querySelectorAll(`[data-tables-workspace][data-department-slug="${CSS.escape(departmentSlug)}"] [data-table-tab="true"][data-table-key]`).forEach((tab) => {
    const tableKey = tab.dataset.tableKey;
    const savedQuery = savedTableQuery(departmentSlug, tableKey);
    if (savedQuery) {
      const params = normalizeSavedTableParams(new URLSearchParams(savedQuery));
      if (params.toString()) {
        storeValue(tableStateStorageKey(departmentSlug, tableKey), params.toString());
      } else {
        removeStoredValue(tableStateStorageKey(departmentSlug, tableKey));
      }
    }
    const url = new URL(tab.getAttribute("hx-get"), window.location.href);
    url.searchParams.delete("organ_ids");
    tab.setAttribute("hx-get", `${url.pathname}${url.search}`);
  });
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
}

function resetTableStateToSingleOrgan(organId) {
  clearOrganSelectionFromDepartmentTableStates();
  const organ = findOrganById(rememberedSingleOrganId()) || findOrganById(organId) || document.querySelector(".organ-item.active[data-organ-id]");
  document.querySelectorAll("[data-organ-checkbox]").forEach((checkbox) => {
    checkbox.checked = false;
  });
  storeCheckedOrganIds();
  setOrganMode("single");
  if (organ) {
    setActiveOrgan(organ);
    loadOrganInfo(organ.dataset.organId);
    return organ.dataset.organId;
  }
  return "";
}

function normalizeAuthInput(input) {
  const value = input.value.replace(/[^\x21-\x7E]/g, "");
  if (input.value !== value) input.value = value;
}

function normalizeSearchText(value) {
  return String(value || "").trim().toLocaleLowerCase("ru-RU");
}

function setLoading(isLoading) {
  const progress = document.getElementById("htmx-progress");
  if (!progress) return;
  progress.classList.toggle("is-active", isLoading);
}

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

function syncLoadingState() {
  setLoading(htmxRequests > 0);
  if (loadingFailsafeTimer) {
    window.clearTimeout(loadingFailsafeTimer);
    loadingFailsafeTimer = null;
  }
  if (htmxRequests > 0) {
    loadingFailsafeTimer = window.setTimeout(() => {
      htmxRequests = 0;
      setLoading(false);
    }, 30000);
  }
}

function startHtmxRequest() {
  htmxRequests += 1;
  syncLoadingState();
}

function finishHtmxRequest() {
  htmxRequests = Math.max(0, htmxRequests - 1);
  syncLoadingState();
}

function resetHtmxLoading() {
  htmxRequests = 0;
  syncLoadingState();
}

function syncRequestPhotoPicker(box) {
  const selectedBox = box.querySelector("[data-request-photo-selected]");
  const checkboxes = Array.from(box.querySelectorAll("[data-request-photo-checkbox]"));
  const selectedIds = new Set(Array.from(selectedBox?.querySelectorAll("[data-request-photo-hidden]") || []).map((input) => input.value));
  checkboxes.forEach((checkbox) => {
    checkbox.checked = selectedIds.has(checkbox.value);
  });
  box.querySelector("[data-request-photo-count]").textContent = String(selectedIds.size);
  checkboxes.forEach((checkbox) => {
    checkbox.closest(".request-photo-option")?.classList.toggle("is-selected", checkbox.checked);
  });
}

function setRequestPhotoSelected(checkbox) {
  const box = checkbox.closest("[data-request-photo-box]");
  const selectedBox = box?.querySelector("[data-request-photo-selected]");
  if (!box || !selectedBox) return;
  selectedBox.querySelectorAll(`[data-request-photo-hidden][value="${CSS.escape(checkbox.value)}"]`).forEach((input) => input.remove());
  if (checkbox.checked) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "attached_photos";
    input.value = checkbox.value;
    input.dataset.requestPhotoHidden = "true";
    selectedBox.append(input);
  }
  syncRequestPhotoPicker(box);
}

function detachRequestPhoto(button) {
  const box = button.closest("[data-request-photo-box]");
  if (!box) return;
  const photoId = button.dataset.detachRequestPhoto;
  box.querySelectorAll(`[data-request-photo-hidden][value="${CSS.escape(photoId)}"]`).forEach((input) => input.remove());
  box.querySelectorAll(`[data-request-photo-checkbox][value="${CSS.escape(photoId)}"]`).forEach((checkbox) => {
    checkbox.checked = false;
  });
  button.closest("[data-request-linked-photo]")?.remove();
  const list = box.querySelector("[data-request-linked-photos]");
  if (list && !list.querySelector("[data-request-linked-photo]") && !list.querySelector("[data-request-linked-empty]")) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.dataset.requestLinkedEmpty = "true";
    empty.textContent = "К заявке фотографии не прикреплены";
    list.append(empty);
  }
  syncRequestPhotoPicker(box);
}

function scrollRequestPhotoPickerIntoView(box) {
  if (!box) return;
  const panel = box.querySelector("[data-request-photo-panel]");
  if (!panel || panel.hidden) return;

  window.requestAnimationFrame(() => {
    const target = box.querySelector("[data-request-photo-scroll-anchor]") || panel;
    const modalBody = target.closest(".modal-body");
    const container = modalBody || document.scrollingElement || document.documentElement;
    const targetRect = target.getBoundingClientRect();

    if (modalBody) {
      const containerRect = modalBody.getBoundingClientRect();
      const nextTop = modalBody.scrollTop + targetRect.bottom - containerRect.bottom + 24;
      modalBody.scrollTo({ top: Math.max(0, nextTop), behavior: "smooth" });
      return;
    }

    const viewportBottom = window.innerHeight || document.documentElement.clientHeight;
    const nextTop = window.scrollY + targetRect.bottom - viewportBottom + 32;
    if (targetRect.bottom > viewportBottom - 24) {
      window.scrollTo({ top: Math.max(0, nextTop), behavior: "smooth" });
    }
  });
}

function scheduleRequestPhotoPickerScroll(box) {
  if (!box) return;
  window.setTimeout(() => scrollRequestPhotoPickerIntoView(box), 40);
}

function refreshCurrentTableArea() {
  const tableArea = document.getElementById("table-area");
  if (!tableArea || !window.htmx) return;
  const activeTab = document.querySelector('[data-table-tab="true"].active');
  const url = activeTab?.getAttribute("hx-get") || tableArea.getAttribute("hx-get");
  if (url) window.htmx.ajax("GET", url, { target: "#table-area", swap: "innerHTML" });
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

function filterCurrentTable(input) {
  const tableWrap = input.closest("#table-area") || document;
  const query = normalizeSearchText(input.value);
  let visibleRows = 0;
  const rows = Array.from(tableWrap.querySelectorAll(".data-row"));
  const groupedRows = rows.reduce((groups, row) => {
    const group = row.dataset.rowGroup;
    if (!group) return groups;
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(row);
    return groups;
  }, new Map());

  groupedRows.forEach((groupRows) => {
    const groupText = normalizeSearchText(groupRows.map((row) => row.textContent).join(" "));
    const isVisible = !query || groupText.includes(query);
    groupRows.forEach((row) => {
      row.hidden = !isVisible;
    });
    if (isVisible) visibleRows += groupRows.length;
  });

  rows.filter((row) => !row.dataset.rowGroup).forEach((row) => {
    const isVisible = !query || normalizeSearchText(row.textContent).includes(query);
    row.hidden = !isVisible;
    if (isVisible) visibleRows += 1;
  });
  const empty = tableWrap.querySelector(".table-empty-filter");
  if (empty) empty.hidden = visibleRows > 0 || !query;
}

function clearTableGroupHover(scope = document) {
  scope.querySelectorAll(".data-row.is-group-hover").forEach((row) => {
    row.classList.remove("is-group-hover");
  });
}

function setTableGroupHover(row) {
  const group = row.dataset.rowGroup;
  if (!group) return;
  const tableWrap = row.closest(".table-wrap") || document;
  clearTableGroupHover(tableWrap);
  tableWrap.querySelectorAll(`.data-row[data-row-group="${CSS.escape(group)}"]`).forEach((groupRow) => {
    groupRow.classList.add("is-group-hover");
  });
}

function todayInputValue() {
  const date = new Date();
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

function fillCompletedDate(form) {
  const status = form.querySelector('[name="status"]');
  const completedDate = form.querySelector('[name="completed_at"]') || form.querySelector('[name="due_date"]');
  if (!status || !completedDate) return;
  if (status.value === "done" && !completedDate.value) {
    completedDate.value = todayInputValue();
  }
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
      document.getElementById("workspace").innerHTML = '<div class="empty-state">Выберите хотя бы один территориальный орган</div>';
      return;
    }
    storeValue(departmentStorageKey("multi"), departmentSlug);
    const url = `/organs/${baseOrganId}/departments/${departmentSlug}/${query ? `?${query}` : ""}`;
    window.htmx.ajax("GET", url, { target: "#workspace", swap: "innerHTML" });
    return;
  }
  if (!window.selectedOrgan) {
    const activeOrgan = document.querySelector(".organ-item.active[data-organ-id]") || document.querySelector(".organ-item[data-organ-id]");
    window.selectedOrgan = activeOrgan ? Number(activeOrgan.dataset.organId) : null;
  }
  if (!window.selectedOrgan) return;
  storeValue(departmentStorageKey(window.selectedOrgan), departmentSlug);
  const query = departmentRequestQuery(departmentSlug);
  const url = `/organs/${window.selectedOrgan}/departments/${departmentSlug}/${query ? `?${query}` : ""}`;
  window.htmx.ajax("GET", url, { target: "#workspace", swap: "innerHTML" });
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

function scrollAfterPaginationSwap(event) {
  const trigger = event.detail?.requestConfig?.elt;
  const pagination = trigger?.closest?.("[data-pagination-scroll]");
  if (!pagination) return;
  const targetSelector = pagination.dataset.paginationScroll;
  if (!targetSelector) return;
  const swapTarget = event.detail?.target;
  const target = targetSelector === "self" ? swapTarget : swapTarget?.querySelector?.(targetSelector);
  if (!target) return;
  target.scrollTo?.({ top: 0, left: target.scrollLeft, behavior: "smooth" });
}

function isEditableTarget(target) {
  return Boolean(target?.closest?.("input, textarea, select, [contenteditable='true'], [data-custom-select]"));
}

function isVisibleElement(element) {
  return Boolean(element && !element.disabled && element.getClientRects().length);
}

function focusCurrentSearch() {
  const modal = document.querySelector("#modal-root.show .modal-content");
  const scopes = [modal, document.getElementById("workspace"), document].filter(Boolean);
  const selectors = [
    "#request-photo-search-input",
    "#photo-search-input",
    "[id^='table-search-']",
    "[data-table-search]",
    "#organ-search",
  ];
  for (const scope of scopes) {
    for (const selector of selectors) {
      const input = scope.querySelector(selector);
      if (!isVisibleElement(input)) continue;
      input.focus();
      input.select?.();
      return true;
    }
  }
  return false;
}

function closeOpenModal() {
  const modalElement = document.getElementById("modal-root");
  if (!modalElement?.classList.contains("show")) return false;
  bootstrap.Modal.getInstance(modalElement)?.hide();
  return true;
}

function isAppModalOpen() {
  return document.getElementById("modal-root")?.classList.contains("show");
}

function lockDocumentScrollForModal() {
  document.documentElement.classList.add("app-modal-scroll-locked");
}

function unlockDocumentScrollForModal() {
  document.documentElement.classList.remove("app-modal-scroll-locked");
}

function isScrollableY(element) {
  const style = window.getComputedStyle(element);
  return ["auto", "scroll"].includes(style.overflowY) && element.scrollHeight > element.clientHeight;
}

function closestScrollableModalElement(target, dialog) {
  let element = target instanceof Element ? target : null;
  while (element && element !== dialog.parentElement) {
    if (dialog.contains(element) && isScrollableY(element)) return element;
    if (element === dialog) break;
    element = element.parentElement;
  }
  const modalBody = dialog.querySelector(".modal-body");
  return modalBody && isScrollableY(modalBody) ? modalBody : null;
}

function preventBackgroundModalScroll(event) {
  if (!isAppModalOpen()) return;
  const dialog = event.target?.closest?.("#modal-root .modal-dialog");
  if (!dialog) {
    event.preventDefault();
    return;
  }
  const scrollElement = closestScrollableModalElement(event.target, dialog);
  if (!scrollElement) {
    event.preventDefault();
    return;
  }
  const deltaY = event.deltaY || 0;
  if (!deltaY) return;
  const scrollTop = scrollElement.scrollTop;
  const maxScrollTop = scrollElement.scrollHeight - scrollElement.clientHeight;
  const canScrollDown = deltaY > 0 && scrollTop < maxScrollTop;
  const canScrollUp = deltaY < 0 && scrollTop > 0;
  if (event.target?.closest?.(".modal-body") && (canScrollDown || canScrollUp)) return;
  event.preventDefault();
  if (canScrollDown || canScrollUp) {
    scrollElement.scrollTop += deltaY;
  }
}

document.addEventListener("wheel", preventBackgroundModalScroll, { passive: false });
document.addEventListener("touchmove", preventBackgroundModalScroll, { passive: false });

const appModalRoot = document.getElementById("modal-root");
appModalRoot?.addEventListener("show.bs.modal", lockDocumentScrollForModal);
appModalRoot?.addEventListener("hidden.bs.modal", unlockDocumentScrollForModal);
appModalRoot?.addEventListener("shown.bs.modal", () => {
  const input = appModalRoot.querySelector("[autofocus]");
  if (!isVisibleElement(input)) return;
  input.focus();
  input.select?.();
});

document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target.id === "modal-content") {
    initCustomSelects(event.detail.target);
    initTooltips();
    autoDismissAlerts();
    bootstrap.Modal.getOrCreateInstance(document.getElementById("modal-root")).show();
    const bulkForm = event.detail.target.querySelector("[data-bulk-photo-form]");
    if (bulkForm) {
      PhotoUpload.renderPendingBulkPhotoFiles(bulkForm);
    }
    event.detail.target.querySelectorAll("[data-request-photo-box]").forEach(syncRequestPhotoPicker);
    syncActiveDownloadButtons(event.detail.target);
    return;
  }
  saveTableStateFromHtmxEvent(event);
  initCustomSelects(event.detail.target);
  initTooltips();
  autoDismissAlerts();
  event.detail.target.querySelectorAll?.("[data-request-photo-box]").forEach((box) => {
    syncRequestPhotoPicker(box);
    scheduleRequestPhotoPickerScroll(box);
  });
  const requestPhotoBox = event.detail.target.closest?.("[data-request-photo-box]");
  if (requestPhotoBox) {
    syncRequestPhotoPicker(requestPhotoBox);
    scheduleRequestPhotoPickerScroll(requestPhotoBox);
  }
  syncActiveDownloadButtons(event.detail.target);
  applyCollapsedPanels();
  scrollAfterPaginationSwap(event);
});

document.body.addEventListener("htmx:configRequest", (event) => {
  if (!isResetTableStateTrigger(event.detail?.elt)) return;
  const organId = event.detail.elt.dataset.resetOrganId;
  const restoredOrganId = resetTableStateToSingleOrgan(organId);
  event.detail.parameters?.delete?.("organ_ids");
  if (event.detail.parameters && typeof event.detail.parameters === "object" && !event.detail.parameters.delete) {
    delete event.detail.parameters.organ_ids;
  }
  if (event.detail.path) {
    const url = new URL(event.detail.path, window.location.href);
    url.searchParams.delete("organ_ids");
    if (restoredOrganId) {
      url.pathname = url.pathname.replace(/\/organs\/\d+\//, `/organs/${restoredOrganId}/`);
    }
    event.detail.path = `${url.pathname}${url.search}`;
  }
});

document.body.addEventListener("htmx:beforeRequest", startHtmxRequest);

document.body.addEventListener("htmx:afterRequest", finishHtmxRequest);

document.body.addEventListener("htmx:responseError", (event) => {
  resetHtmxLoading();
  const status = event.detail?.xhr?.status;
  const message = status === 413
    ? "Слишком большой объем данных для одного запроса. Фотографии будут надежнее загружаться пакетами."
    : "Не удалось выполнить действие.";
  showToast(message, "danger");
});

document.body.addEventListener("htmx:sendError", () => {
  resetHtmxLoading();
  showToast("Не удалось отправить запрос.", "danger");
});

document.body.addEventListener("htmx:timeout", () => {
  resetHtmxLoading();
  showToast("Запрос выполнялся слишком долго.", "warning");
});

document.body.addEventListener("htmx:abort", resetHtmxLoading);

document.body.addEventListener("htmx:swapError", () => {
  resetHtmxLoading();
  showToast("Не удалось обновить данные на странице.", "danger");
});

document.body.addEventListener("toast", (event) => {
  const detail = event.detail || {};
  const value = detail.value || detail;
  showToast(value.message || value, value.level);
});

document.body.addEventListener("requestPhotosChanged", refreshCurrentTableArea);

document.body.addEventListener("modal:close", () => {
  const modal = bootstrap.Modal.getInstance(document.getElementById("modal-root"));
  if (modal) modal.hide();
});

document.addEventListener("submit", (event) => {
  const bulkForm = event.target.closest("[data-bulk-photo-form]");
  if (!bulkForm) return;
  event.preventDefault();
  event.stopPropagation();
  PhotoUpload.uploadBulkPhotos(bulkForm);
}, true);

document.addEventListener("input", (event) => {
  if (event.target.matches(".auth-ascii-input")) {
    normalizeAuthInput(event.target);
    return;
  }
  if (event.target.matches("[data-tmc-product-input]")) {
    requestTmcProductSuggestions(event.target);
    return;
  }
  if (event.target.matches("[data-table-search]")) {
    filterCurrentTable(event.target);
    return;
  }
  if (event.target.id !== "organ-search") return;
  const query = normalizeSearchText(event.target.value);
  document.querySelectorAll("[data-organ-row]").forEach((item) => {
    if (!query) {
      item.hidden = false;
      item.style.order = "";
      return;
    }
    const organMatch = normalizeSearchText(item.dataset.organSearch).includes(query);
    const childMatch = normalizeSearchText(item.dataset.childSearch).includes(query);
    item.hidden = !organMatch && !childMatch;
    item.style.order = organMatch ? "0" : "1";
  });
});

document.addEventListener("mouseover", (event) => {
  const row = event.target.closest(".data-row[data-row-group]");
  if (row) setTableGroupHover(row);
});

document.addEventListener("mouseout", (event) => {
  const tableWrap = event.target.closest(".table-wrap");
  if (tableWrap && !tableWrap.contains(event.relatedTarget)) {
    clearTableGroupHover(tableWrap);
  }
});

document.addEventListener("change", (event) => {
  if (event.target.matches("[data-request-photo-checkbox]")) {
    setRequestPhotoSelected(event.target);
    return;
  }

  const status = event.target.closest('[data-tmc-request-form] [name="status"], [data-status-form] [name="status"]');
  if (status) {
    fillCompletedDate(status.closest("[data-tmc-request-form], [data-status-form]"));
    return;
  }
  if (event.target.matches("[data-single-file-picker] input[type='file']")) {
    PhotoUpload.updateSingleFilePicker(event.target);
    return;
  }
  if (!event.target.matches("[data-bulk-photo-input]")) return;
  const form = event.target.closest("[data-bulk-photo-form]");
  if (form) PhotoUpload.renderBulkPhotoFiles(form, event.target.files);
});

document.addEventListener("dragover", (event) => {
  const dropzone = PhotoUpload.photoDropTarget(event);
  if (!dropzone) return;
  event.preventDefault();
  PhotoUpload.clearPhotoDragState();
  dropzone.classList.add("is-dragover");
});

document.addEventListener("dragleave", (event) => {
  const dropzone = PhotoUpload.photoDropTarget(event);
  if (!dropzone || dropzone.contains(event.relatedTarget)) return;
  dropzone.classList.remove("is-dragover");
});

document.addEventListener("drop", (event) => {
  const dropzone = PhotoUpload.photoDropTarget(event);
  if (!dropzone) return;
  event.preventDefault();
  PhotoUpload.clearPhotoDragState();
  PhotoUpload.openBulkPhotoModal(dropzone, event.dataTransfer.files);
});

document.addEventListener("beforeinput", (event) => {
  if (!event.target.matches(".auth-ascii-input") || !event.data) return;
  if (/[^\x21-\x7E]/.test(event.data)) event.preventDefault();
});


function updateAdminFilterOrgBox(box) {
  if (!box) return;
  const items = Array.from(box.querySelectorAll(".admin-org-filter-item"));
  const checkboxes = items.map((item) => item.querySelector('input[type="checkbox"][name="organ_ids"]')).filter(Boolean);
  const checked = checkboxes.filter((checkbox) => checkbox.checked);
  items.forEach((item) => {
    const checkbox = item.querySelector('input[type="checkbox"][name="organ_ids"]');
    item.classList.toggle("is-selected", Boolean(checkbox?.checked));
  });
  const meta = box.querySelector(".admin-org-filter-toggle-meta strong");
  if (meta) {
    if (!checkboxes.length || checked.length === checkboxes.length) {
      meta.textContent = "выбраны все";
    } else if (checked.length === 1) {
      meta.textContent = "выбран 1";
    } else if (checked.length === 0) {
      meta.textContent = "ничего не выбрано";
    } else {
      meta.textContent = `выбрано ${checked.length}`;
    }
  }

  const form = box.closest("form");
  let emptyMarker = form?.querySelector('input[name="organ_filter_empty"][data-admin-organ-empty-marker]');
  if (form && checkboxes.length && checked.length === 0) {
    if (!emptyMarker) {
      emptyMarker = document.createElement("input");
      emptyMarker.type = "hidden";
      emptyMarker.name = "organ_filter_empty";
      emptyMarker.dataset.adminOrganEmptyMarker = "true";
      form.append(emptyMarker);
    }
    emptyMarker.value = "1";
  } else {
    emptyMarker?.remove();
  }
}

function initAdminFilterOrgBoxes() {
  document.querySelectorAll(".admin-org-filter-box").forEach(updateAdminFilterOrgBox);
}

document.addEventListener("change", (event) => {
  const checkbox = event.target.closest('input[type="checkbox"][name="organ_ids"]');
  if (!checkbox) return;
  updateAdminFilterOrgBox(checkbox.closest(".admin-org-filter-box"));
});

document.addEventListener("DOMContentLoaded", initAdminFilterOrgBoxes);

document.addEventListener("click", (event) => {

  const adminFilterSelectAll = event.target.closest("[data-admin-filter-organ-select-all]");
  if (adminFilterSelectAll) {
    event.preventDefault();
    const box = adminFilterSelectAll.closest(".admin-org-filter-box");
    box?.querySelectorAll('input[type="checkbox"][name="organ_ids"]').forEach((checkbox) => {
      checkbox.checked = true;
    });
    updateAdminFilterOrgBox(box);
    return;
  }

  const adminFilterClearAll = event.target.closest("[data-admin-filter-organ-clear-all]");
  if (adminFilterClearAll) {
    event.preventDefault();
    const box = adminFilterClearAll.closest(".admin-org-filter-box");
    box?.querySelectorAll('input[type="checkbox"][name="organ_ids"]').forEach((checkbox) => {
      checkbox.checked = false;
    });
    updateAdminFilterOrgBox(box);
    return;
  }

  const preparingDownload = event.target.closest("a[data-download-preparing]");
  if (preparingDownload) {
    const key = downloadKey(preparingDownload);
    const activeDownload = activeDownloads.get(key);
    if (preparingDownload.dataset.downloadPreparingActive === "true") {
      event.preventDefault();
      showDownloadPreparingNotice(activeDownload?.label || preparingDownload.dataset.downloadPreparing || "Файл уже готовится...");
      return;
    }
    if (activeDownload) {
      event.preventDefault();
      showDownloadPreparingNotice(activeDownload.label);
      return;
    }
    if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && preparingDownload.target !== "_blank") {
      event.preventDefault();
      const token = downloadToken();
      const label = preparingDownload.dataset.downloadPreparing || "Подготовка файла...";
      activeDownloads.set(key, { token, label, startedAt: Date.now() });
      markPreparingDownload(preparingDownload, key, label);
      waitForDownloadStart(token, key);
      window.location.href = downloadUrlWithToken(preparingDownload.href, token);
    }
    return;
  }

  const tab = event.target.closest('[data-table-tab="true"][data-table-key]');
  if (!tab) return;
  const departmentSlug = tab.closest("[data-tables-workspace]")?.dataset.departmentSlug;
  if (departmentSlug) {
    storeValue(departmentTableStorageKey(departmentSlug), tab.dataset.tableKey);
    tab.setAttribute("hx-get", tableUrlWithSavedState(tab));
  }
}, true);

document.addEventListener("click", (event) => {
  const resetTableState = event.target.closest("[data-reset-table-state]");
  if (resetTableState) {
    clearCurrentTableState();
    const restoredOrganId = resetTableStateToSingleOrgan(resetTableState.dataset.resetOrganId);
    if (restoredOrganId) {
      const url = new URL(resetTableState.getAttribute("hx-get") || resetTableState.href, window.location.href);
      url.searchParams.delete("organ_ids");
      url.pathname = url.pathname.replace(/\/organs\/\d+\//, `/organs/${restoredOrganId}/`);
      const nextUrl = `${url.pathname}${url.search}`;
      resetTableState.setAttribute("hx-get", nextUrl);
      resetTableState.setAttribute("href", nextUrl);
    }
  }

  const organMode = event.target.closest("[data-organ-mode]");
  if (organMode) {
    event.preventDefault();
    setOrganMode(organMode.dataset.organMode);
    if (!isMultiOrganMode()) {
      const organ = findOrganById(rememberedSingleOrganId()) || document.querySelector(".organ-item[data-organ-id]");
      if (organ) {
        setActiveOrgan(organ);
        loadOrganInfo(organ.dataset.organId);
      }
      const department = preferredDepartmentForOrgan(window.selectedOrgan);
      if (department) {
        setActiveDepartment(department);
        loadDepartment(department);
      }
      return;
    }
    const department = checkedOrganIds().length ? preferredDepartmentForOrgan(window.selectedOrgan) : null;
    if (department) {
      setActiveDepartment(department);
      loadDepartment(department);
    } else {
      clearActiveDepartment();
      renderMultiOrganWorkspaceEmpty();
    }
    return;
  }

  const selectAll = event.target.closest("[data-organ-select-all]");
  if (selectAll) {
    event.preventDefault();
    document.querySelectorAll("[data-organ-checkbox]").forEach((checkbox) => {
      if (!checkbox.closest("[data-organ-row]")?.hidden) checkbox.checked = true;
    });
    storeCheckedOrganIds();
    const department = preferredDepartmentForOrgan(window.selectedOrgan);
    if (department) loadDepartment(department);
    return;
  }

  const clearAll = event.target.closest("[data-organ-clear-all]");
  if (clearAll) {
    event.preventDefault();
    document.querySelectorAll("[data-organ-checkbox]").forEach((checkbox) => {
      checkbox.checked = false;
    });
    storeCheckedOrganIds();
    renderMultiOrganInfo();
    clearActiveDepartment();
    renderMultiOrganWorkspaceEmpty();
    return;
  }

  const productSuggestion = event.target.closest("[data-tmc-product-suggestion]");
  if (productSuggestion) {
    chooseTmcProductSuggestion(productSuggestion);
    return;
  }


  if (!event.target.closest("[data-tmc-product-field]")) closeAllTmcProductSuggestions();

  const panelToggle = event.target.closest("[data-panel-toggle]");
  if (panelToggle) {
    const state = readCollapsedPanels();
    const panel = panelToggle.dataset.panelToggle;
    state[panel] = !state[panel];
    writeCollapsedPanels(state);
    applyCollapsedPanels();
    return;
  }

  const bulkPicker = event.target.closest("[data-bulk-photo-picker]");
  if (bulkPicker) {
    bulkPicker.closest("[data-bulk-photo-form]")?.querySelector("[data-bulk-photo-input]")?.click();
    return;
  }

  const bulkRemove = event.target.closest("[data-remove-bulk-photo]");
  if (bulkRemove) {
    const form = bulkRemove.closest("[data-bulk-photo-form]");
    if (form) PhotoUpload.removeBulkPhotoFile(form, Number(bulkRemove.dataset.removeBulkPhoto));
    return;
  }

  const singleFileButton = event.target.closest("[data-single-file-button]");
  if (singleFileButton) {
    singleFileButton.closest("[data-single-file-picker]")?.querySelector("input[type='file']")?.click();
    return;
  }

  const requestPhotoToggle = event.target.closest("[data-request-photo-toggle]");
  if (requestPhotoToggle) {
    const box = requestPhotoToggle.closest("[data-request-photo-box]");
    const panel = box?.querySelector("[data-request-photo-panel]");
    if (!box || !panel) return;
    panel.hidden = !panel.hidden;
    syncRequestPhotoPicker(box);
    if (!panel.hidden) scheduleRequestPhotoPickerScroll(box);
    return;
  }

  const detachPhoto = event.target.closest("[data-detach-request-photo]");
  if (detachPhoto) {
    detachRequestPhoto(detachPhoto);
    return;
  }

  const addTmcItem = event.target.closest("[data-add-tmc-item]");
  if (addTmcItem) {
    const list = addTmcItem.closest("[data-tmc-request-form]")?.querySelector("[data-tmc-items]");
    const row = list?.querySelector("[data-tmc-item-row]");
    if (!list || !row) return;
    const clone = row.cloneNode(true);
    clone.querySelectorAll("input").forEach((input) => {
      input.value = input.name === "item_unit" ? "шт." : "";
    });
    list.append(clone);
    clone.querySelector("input")?.focus();
    return;
  }

  const removeTmcItem = event.target.closest("[data-remove-tmc-item]");
  if (removeTmcItem) {
    const list = removeTmcItem.closest("[data-tmc-items]");
    const rows = list?.querySelectorAll("[data-tmc-item-row]");
    if (!list || !rows) return;
    if (rows.length > 1) {
      removeTmcItem.closest("[data-tmc-item-row]")?.remove();
    } else {
      rows[0].querySelectorAll("input").forEach((input) => {
        input.value = input.name === "item_unit" ? "шт." : "";
      });
    }
    return;
  }

  const passwordToggle = event.target.closest("[data-password-toggle]");
  if (passwordToggle) {
    const input = document.getElementById(passwordToggle.getAttribute("aria-controls"));
    if (!input) return;
    const shouldShow = input.type === "password";
    input.type = shouldShow ? "text" : "password";
    passwordToggle.setAttribute("aria-label", shouldShow ? "Скрыть пароль" : "Показать пароль");
    passwordToggle.innerHTML = shouldShow ? '<i class="bi bi-eye-slash"></i>' : '<i class="bi bi-eye"></i>';
    input.focus();
    return;
  }

  const tab = event.target.closest('[data-table-tab="true"]');
  if (!tab) return;
  const tabList = tab.closest(".nav-tabs");
  if (!tabList) return;
  tabList.querySelectorAll(".nav-link").forEach((item) => item.classList.remove("active"));
  tab.classList.add("active");
});

document.addEventListener("click", (event) => {
  const organ = event.target.closest(".organ-item[data-organ-id]");
  if (!organ) return;
  if (isMultiOrganMode()) {
    event.preventDefault();
    const checkbox = organ.closest("[data-organ-row]")?.querySelector("[data-organ-checkbox]");
    if (checkbox) {
      checkbox.checked = !checkbox.checked;
      storeCheckedOrganIds();
    }
    const department = preferredDepartmentForOrgan(window.selectedOrgan);
    if (department) loadDepartment(department);
    return;
  }
  setActiveOrgan(organ);

  const departments = document.querySelectorAll(".department-item[data-department-slug]");
  departments.forEach((department) => {
    department.classList.remove("active");
    department.removeAttribute("aria-current");
  });

  const department = preferredDepartmentForOrgan(window.selectedOrgan);
  if (department) {
    setActiveDepartment(department);
    loadDepartment(department);
  }
});

document.addEventListener("change", (event) => {
  if (!event.target.matches("[data-organ-checkbox]")) return;
  storeCheckedOrganIds();
  if (!isMultiOrganMode()) return;
  const department = preferredDepartmentForOrgan(window.selectedOrgan);
  if (department) loadDepartment(department);
});

document.addEventListener("click", (event) => {
  const department = event.target.closest(".department-item[data-department-slug]");
  if (!department) return;
  event.preventDefault();
  setActiveDepartment(department);
  loadDepartment(department);
});

document.addEventListener("DOMContentLoaded", () => {
  syncHeaderHeight();
  resetHtmxLoading();
  initCustomSelects();
  initTooltips();
  startPresenceHeartbeat();
  document.querySelectorAll(".auth-ascii-input").forEach(normalizeAuthInput);
  autoDismissAlerts();
  applyCollapsedPanels();
  const restoredOrganCount = restoreCheckedOrgans();
  const savedOrganId = storedValue(ORGAN_STORAGE_KEY);
  const organ = savedOrganId
    ? findOrganById(savedOrganId)
    : document.querySelector(".organ-item[data-organ-id]");
  if (organ) {
    setActiveOrgan(organ);
    if (isMultiOrganMode()) {
      clearSingleOrganHighlight();
      renderMultiOrganInfo();
    } else {
      loadOrganInfo(window.selectedOrgan);
    }
    syncOrganModeButtons();
    const department = !isMultiOrganMode() || restoredOrganCount ? preferredDepartmentForOrgan(window.selectedOrgan) : null;
    if (department) {
      setActiveDepartment(department);
      loadDepartment(department);
    } else if (isMultiOrganMode()) {
      clearActiveDepartment();
      renderMultiOrganWorkspaceEmpty();
    }
  }
});

window.addEventListener("resize", () => {
  syncHeaderHeight();
});
