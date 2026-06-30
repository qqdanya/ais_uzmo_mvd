window.selectedOrgan = window.selectedOrgan || null;
const ORGAN_STORAGE_KEY = "asu-zmo:selected-organ";
const ORGAN_MODE_KEY = "asu-zmo:organ-mode";
const MULTI_ORGANS_KEY = "asu-zmo:multi-organs";
const DEPARTMENT_STORAGE_PREFIX = "asu-zmo:last-department:";
const DEPARTMENT_TABLE_PREFIX = "asu-zmo:last-table:";
const TABLE_STATE_PREFIX = "asu-zmo:table-state:";
const COLLAPSED_PANELS_KEY = "asu-zmo:collapsed-panels";
const BULK_PHOTO_BATCH_SIZE = 25;
const BULK_PHOTO_MAX_FILES = 300;
let htmxRequests = 0;
let loadingFailsafeTimer = null;
let pendingBulkPhotoFiles = [];
const tmcProductSuggestTimers = new WeakMap();
let photoLightboxState = {
  items: [],
  index: 0,
  scale: 1,
  offsetX: 0,
  offsetY: 0,
  isDragging: false,
  dragStartX: 0,
  dragStartY: 0,
  dragOriginX: 0,
  dragOriginY: 0,
  didDrag: false,
};

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

function saveTableStateFromHtmxEvent(event) {
  if (event.detail?.target?.id !== "table-area") return;
  const url = event.detail?.xhr?.responseURL || event.detail?.requestConfig?.path;
  saveTableStateFromUrl(url, event.detail.target);
}

function clearCurrentTableState() {
  const departmentSlug = activeDepartmentSlug();
  const tableKey = document.querySelector('[data-table-tab="true"].active[data-table-key]')?.dataset.tableKey;
  if (!departmentSlug || !tableKey) return;
  removeStoredValue(tableStateStorageKey(departmentSlug, tableKey));
}

function findDepartmentBySlug(slug) {
  return Array.from(document.querySelectorAll(".department-item[data-department-slug]"))
    .find((item) => item.dataset.departmentSlug === slug);
}

function findOrganById(organId) {
  return Array.from(document.querySelectorAll(".organ-item[data-organ-id]"))
    .find((item) => item.dataset.organId === String(organId));
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

function restoreCheckedOrgans() {
  const saved = new Set((storedValue(MULTI_ORGANS_KEY) || "").split(",").filter(Boolean));
  document.querySelectorAll("[data-organ-checkbox]").forEach((checkbox) => {
    checkbox.checked = saved.has(checkbox.value);
  });
}

function ensureMultiSelection() {
  if (checkedOrganIds().length) return;
  const active = document.querySelector(".organ-item.active[data-organ-id]") || document.querySelector(".organ-item[data-organ-id]");
  const checkbox = active?.closest("[data-organ-row]")?.querySelector("[data-organ-checkbox]");
  if (checkbox) checkbox.checked = true;
  storeCheckedOrganIds();
}

function setOrganMode(mode) {
  storeValue(ORGAN_MODE_KEY, mode === "multi" ? "multi" : "single");
  if (isMultiOrganMode()) {
    ensureMultiSelection();
    renderMultiOrganInfo();
  }
  syncOrganModeButtons();
}

function resetTableStateToSingleOrgan(organId) {
  const organ = findOrganById(organId) || document.querySelector(".organ-item.active[data-organ-id]");
  document.querySelectorAll("[data-organ-checkbox]").forEach((checkbox) => {
    checkbox.checked = false;
  });
  storeCheckedOrganIds();
  setOrganMode("single");
  if (organ) {
    setActiveOrgan(organ);
    loadOrganInfo(organ.dataset.organId);
  }
}

function normalizeAuthInput(input) {
  const value = input.value.replace(/[^\x21-\x7E]/g, "");
  if (input.value !== value) input.value = value;
}

function normalizeSearchText(value) {
  return String(value || "").trim().toLocaleLowerCase("ru-RU");
}

function autoDismissAlerts() {
  document.querySelectorAll("[data-auto-dismiss]").forEach((alert) => {
    if (alert.dataset.dismissScheduled === "true") return;
    alert.dataset.dismissScheduled = "true";
    const delay = Number(alert.dataset.autoDismiss) || 6000;
    window.setTimeout(() => {
      const instance = bootstrap.Alert.getOrCreateInstance(alert);
      instance.close();
    }, delay);
  });
}

function initTooltips() {
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
    const title = el.getAttribute("data-bs-title") || el.getAttribute("title") || el.dataset.cssTooltip;
    if (!title) return;
    el.removeAttribute("title");
    el.removeAttribute("data-ui-tooltip");
    window.bootstrap?.Tooltip?.getInstance(el)?.dispose();
    el.dataset.cssTooltip = title;
  });
}

function selectedOption(select) {
  return select.options[select.selectedIndex] || select.querySelector("option");
}

function syncCustomSelect(select) {
  const wrapper = select.nextElementSibling;
  if (!wrapper?.matches?.("[data-custom-select]")) return;
  const current = selectedOption(select);
  wrapper.querySelector("[data-custom-select-value]").textContent = current?.textContent || "";
  wrapper.querySelectorAll("[data-custom-select-option]").forEach((option) => {
    const isSelected = option.dataset.value === select.value;
    option.classList.toggle("is-selected", isSelected);
    option.setAttribute("aria-selected", String(isSelected));
  });
  wrapper.classList.toggle("is-disabled", select.disabled);
  wrapper.querySelector("[data-custom-select-trigger]").disabled = select.disabled;
}

function closeTmcProductSuggestions(field) {
  const box = field?.querySelector("[data-tmc-product-suggestions]");
  if (!box) return;
  box.hidden = true;
  box.innerHTML = "";
}

function closeAllTmcProductSuggestions(exceptField = null) {
  document.querySelectorAll("[data-tmc-product-field]").forEach((field) => {
    if (field !== exceptField) closeTmcProductSuggestions(field);
  });
}

function renderTmcProductSuggestions(input, results) {
  const field = input.closest("[data-tmc-product-field]");
  const box = field?.querySelector("[data-tmc-product-suggestions]");
  if (!field || !box) return;
  box.innerHTML = "";
  if (!results.length) {
    closeTmcProductSuggestions(field);
    return;
  }
  results.forEach((product) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tmc-product-suggestion";
    button.dataset.tmcProductSuggestion = "true";
    button.dataset.productId = product.id;
    button.dataset.productName = product.name;
    button.dataset.productUnit = product.unit || "шт.";
    button.innerHTML = `<span>${product.name}</span><small>${product.unit || "шт."}</small>`;
    box.append(button);
  });
  box.hidden = false;
}

function requestTmcProductSuggestions(input) {
  const field = input.closest("[data-tmc-product-field]");
  if (!field) return;
  field.querySelector("[data-tmc-product-id]").value = "";
  const query = input.value.trim();
  window.clearTimeout(tmcProductSuggestTimers.get(input));
  if (query.length < 2) {
    closeTmcProductSuggestions(field);
    return;
  }
  const timer = window.setTimeout(async () => {
    try {
      const url = `${input.dataset.suggestUrl}?q=${encodeURIComponent(query)}`;
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok || input.value.trim() !== query) return;
      const data = await response.json();
      renderTmcProductSuggestions(input, data.results || []);
    } catch {
      closeTmcProductSuggestions(field);
    }
  }, 250);
  tmcProductSuggestTimers.set(input, timer);
}

function chooseTmcProductSuggestion(button) {
  const field = button.closest("[data-tmc-product-field]");
  const row = button.closest("[data-tmc-item-row]");
  if (!field || !row) return;
  field.querySelector("[data-tmc-product-id]").value = button.dataset.productId || "";
  field.querySelector("[data-tmc-product-input]").value = button.dataset.productName || "";
  const unitInput = row.querySelector('[name="item_unit"]');
  if (unitInput && button.dataset.productUnit) unitInput.value = button.dataset.productUnit;
  closeTmcProductSuggestions(field);
}

function closeCustomSelects(except = null) {
  document.querySelectorAll("[data-custom-select].is-open").forEach((wrapper) => {
    if (wrapper === except) return;
    wrapper.classList.remove("is-open");
    wrapper.querySelector("[data-custom-select-trigger]")?.setAttribute("aria-expanded", "false");
  });
}

function openCustomSelect(wrapper) {
  if (wrapper.classList.contains("is-disabled")) return;
  closeCustomSelects(wrapper);
  wrapper.classList.add("is-open");
  wrapper.querySelector("[data-custom-select-trigger]")?.setAttribute("aria-expanded", "true");
}

function toggleCustomSelect(wrapper) {
  if (wrapper.classList.contains("is-open")) {
    closeCustomSelects();
  } else {
    openCustomSelect(wrapper);
  }
}

function chooseCustomSelectOption(option) {
  if (option.disabled || option.getAttribute("aria-disabled") === "true") return;
  const wrapper = option.closest("[data-custom-select]");
  const select = wrapper?.previousElementSibling;
  if (!select?.matches?.("select")) return;
  select.value = option.dataset.value;
  syncCustomSelect(select);
  closeCustomSelects();
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function initCustomSelects(scope = document) {
  const selects = scope.matches?.("select.form-select:not([data-native-select])")
    ? [scope]
    : Array.from(scope.querySelectorAll("select.form-select:not([data-native-select])"));
  selects.forEach((select) => {
    if (select.nextElementSibling?.matches?.("[data-custom-select]")) {
      select.dataset.nativeSelect = "true";
      select.classList.add("custom-select-native");
      syncCustomSelect(select);
      return;
    }
    select.dataset.nativeSelect = "true";
    select.classList.add("custom-select-native");
    const wrapper = document.createElement("div");
    wrapper.className = `custom-select${select.classList.contains("form-select-sm") ? " custom-select-sm" : ""}`;
    wrapper.dataset.customSelect = "true";
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "custom-select-trigger";
    trigger.dataset.customSelectTrigger = "true";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    if (select.getAttribute("aria-label")) {
      trigger.setAttribute("aria-label", select.getAttribute("aria-label"));
    }
    const value = document.createElement("span");
    value.className = "custom-select-value";
    value.dataset.customSelectValue = "true";
    const icon = document.createElement("i");
    icon.className = "bi bi-chevron-down";
    trigger.append(value, icon);

    const menu = document.createElement("div");
    menu.className = "custom-select-menu";
    menu.setAttribute("role", "listbox");
    Array.from(select.options).forEach((selectOption) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "custom-select-option";
      option.dataset.customSelectOption = "true";
      option.dataset.value = selectOption.value;
      option.textContent = selectOption.textContent;
      option.setAttribute("role", "option");
      if (selectOption.disabled) {
        option.disabled = true;
        option.setAttribute("aria-disabled", "true");
      }
      menu.append(option);
    });
    wrapper.append(trigger, menu);
    select.after(wrapper);
    select.addEventListener("change", () => syncCustomSelect(select));
    syncCustomSelect(select);
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

function renderBulkPhotoFiles(form, files, descriptions = null) {
  const input = form.querySelector("[data-bulk-photo-input]");
  const list = form.querySelector("[data-bulk-photo-list]");
  if (!input || !list) return;
  const previousDescriptions = descriptions || Array.from(list.querySelectorAll("[data-bulk-description]")).map((textarea) => textarea.value);
  list.querySelectorAll("[data-bulk-preview-url]").forEach((preview) => {
    URL.revokeObjectURL(preview.dataset.bulkPreviewUrl);
  });
  const images = Array.from(files).filter((file) => file.type.startsWith("image/"));
  if (images.length > BULK_PHOTO_MAX_FILES) {
    showToast(`За один раз можно загрузить не более ${BULK_PHOTO_MAX_FILES} фотографий.`, "warning");
  }
  const selectedImages = images.slice(0, BULK_PHOTO_MAX_FILES);
  const transfer = new DataTransfer();
  selectedImages.forEach((file) => transfer.items.add(file));
  input.files = transfer.files;
  list.replaceChildren();
  if (!selectedImages.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Изображения не выбраны";
    list.append(empty);
    return;
  }
  if (images.length > BULK_PHOTO_MAX_FILES) {
    const warning = document.createElement("div");
    warning.className = "empty-state";
    warning.textContent = `Выбрано ${images.length} файлов. К загрузке взяты первые ${BULK_PHOTO_MAX_FILES}.`;
    list.append(warning);
  }
  selectedImages.forEach((file, index) => {
    const item = document.createElement("div");
    item.className = "bulk-photo-item";
    item.dataset.bulkPhotoIndex = String(index);
    const previewUrl = URL.createObjectURL(file);
    const preview = document.createElement("div");
    preview.className = "bulk-photo-preview";
    preview.dataset.bulkPreviewUrl = previewUrl;
    const image = document.createElement("img");
    image.src = previewUrl;
    image.alt = file.name;
    image.loading = "lazy";
    preview.append(image);
    const body = document.createElement("div");
    body.className = "bulk-photo-body";
    const meta = document.createElement("div");
    meta.className = "bulk-photo-meta";
    const metaInfo = document.createElement("div");
    metaInfo.className = "bulk-photo-meta-info";
    const icon = document.createElement("i");
    icon.className = "bi bi-file-image";
    const filename = document.createElement("span");
    filename.textContent = file.name;
    metaInfo.append(icon, filename);
    const remove = document.createElement("button");
    remove.className = "btn btn-icon danger bulk-photo-remove";
    remove.type = "button";
    remove.dataset.removeBulkPhoto = String(index);
    remove.setAttribute("aria-label", "Убрать изображение из загрузки");
    remove.innerHTML = '<i class="bi bi-x-lg"></i>';
    meta.append(metaInfo, remove);
    const label = document.createElement("label");
    label.className = "form-label";
    label.setAttribute("for", `bulk-description-${index}`);
    label.textContent = "Описание";
    const textarea = document.createElement("textarea");
    textarea.className = "form-control";
    textarea.id = `bulk-description-${index}`;
    textarea.name = "descriptions";
    textarea.dataset.bulkDescription = String(index);
    textarea.rows = 2;
    textarea.placeholder = "Описание фотографии";
    textarea.value = previousDescriptions[index] || "";
    body.append(meta, label, textarea);
    item.append(preview, body);
    list.append(item);
  });
}

function removeBulkPhotoFile(form, index) {
  const input = form.querySelector("[data-bulk-photo-input]");
  const list = form.querySelector("[data-bulk-photo-list]");
  if (!input) return;
  const files = Array.from(input.files).filter((_, fileIndex) => fileIndex !== index);
  const descriptions = Array.from(list?.querySelectorAll("[data-bulk-description]") || [])
    .filter((_, descriptionIndex) => descriptionIndex !== index)
    .map((textarea) => textarea.value);
  renderBulkPhotoFiles(form, files, descriptions);
}

function csrfToken(form) {
  return form.querySelector('[name="csrfmiddlewaretoken"]')?.value || "";
}

function setBulkUploadProgress(form, uploaded, total, note = "") {
  const progress = form.querySelector("[data-bulk-upload-progress]");
  const counter = form.querySelector("[data-bulk-upload-counter]");
  const bar = form.querySelector("[data-bulk-upload-bar]");
  const noteNode = form.querySelector("[data-bulk-upload-note]");
  if (!progress) return;
  progress.hidden = false;
  if (counter) counter.textContent = `${uploaded} / ${total}`;
  if (bar) bar.style.width = `${total ? Math.round((uploaded / total) * 100) : 0}%`;
  if (noteNode && note) noteNode.textContent = note;
}

function setBulkPhotoFormBusy(form, isBusy) {
  form.classList.toggle("is-uploading", isBusy);
  form.querySelectorAll("button, input, textarea").forEach((control) => {
    control.disabled = isBusy;
  });
  const submit = form.querySelector("[data-bulk-upload-submit]");
  if (submit) {
    submit.innerHTML = isBusy
      ? '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Загрузка...'
      : '<i class="bi bi-cloud-arrow-up"></i> Загрузить';
  }
}

async function postBulkPhotoBatch(form, files, descriptions, startIndex) {
  const formData = new FormData();
  formData.append("csrfmiddlewaretoken", csrfToken(form));
  const folder = form.querySelector('[name="folder"]')?.value;
  const newFolder = form.querySelector('[name="new_folder"]')?.value?.trim();
  if (folder) formData.append("folder", folder);
  if (newFolder) formData.append("new_folder", newFolder);
  files.forEach((file, offset) => {
    formData.append("images", file, file.name);
    formData.append("descriptions", descriptions[startIndex + offset] || "");
  });
  const response = await fetch(form.getAttribute("hx-post") || form.action || window.location.href, {
    method: "POST",
    body: formData,
    headers: {
      "X-Bulk-Photo-Batch": "true",
      "X-CSRFToken": csrfToken(form),
      "X-Requested-With": "XMLHttpRequest",
    },
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

async function uploadBulkPhotos(form) {
  const input = form.querySelector("[data-bulk-photo-input]");
  const files = Array.from(input?.files || []);
  if (!files.length) {
    showToast("Выберите хотя бы одно изображение.", "warning");
    return;
  }
  if (files.length > BULK_PHOTO_MAX_FILES) {
    showToast(`За один раз можно загрузить не более ${BULK_PHOTO_MAX_FILES} фотографий.`, "warning");
    return;
  }
  const descriptions = Array.from(form.querySelectorAll("[data-bulk-description]")).map((textarea) => textarea.value);
  let uploaded = 0;
  let created = 0;
  let failed = 0;
  const errors = [];
  setBulkPhotoFormBusy(form, true);
  setLoading(true);
  try {
    for (let start = 0; start < files.length; start += BULK_PHOTO_BATCH_SIZE) {
      const batch = files.slice(start, start + BULK_PHOTO_BATCH_SIZE);
      setBulkUploadProgress(form, uploaded, files.length, `Отправка ${start + 1}-${Math.min(start + batch.length, files.length)} из ${files.length}`);
      const result = await postBulkPhotoBatch(form, batch, descriptions, start);
      uploaded += batch.length;
      created += Number(result.created || 0);
      failed += Number(result.failed || 0);
      if (Array.isArray(result.errors)) errors.push(...result.errors);
      setBulkUploadProgress(form, uploaded, files.length, `Загружено: ${created}. Ошибок: ${failed}.`);
    }
    const modal = bootstrap.Modal.getInstance(document.getElementById("modal-root"));
    if (modal) modal.hide();
    showToast(failed ? `Загружено: ${created}. Не загружено: ${failed}.` : `Фотографий загружено: ${created}.`, failed ? "warning" : "success");
    if (errors.length) console.warn("Bulk photo upload errors:", errors);
    const refreshUrl = form.dataset.bulkRefreshUrl;
    if (refreshUrl && window.htmx) {
      window.htmx.ajax("GET", refreshUrl, { target: "#workspace", swap: "innerHTML" });
    }
  } catch (error) {
    setBulkUploadProgress(form, uploaded, files.length, "Загрузка остановлена из-за ошибки.");
    showToast("Загрузка прервана. Попробуйте повторить или выбрать меньше файлов.", "danger");
    console.error(error);
  } finally {
    setBulkPhotoFormBusy(form, false);
    setLoading(false);
  }
}

function openBulkPhotoModal(dropzone, files) {
  pendingBulkPhotoFiles = Array.from(files).filter((file) => file.type.startsWith("image/"));
  if (!pendingBulkPhotoFiles.length || !window.htmx) return;
  const uploadUrl = dropzone.dataset.photoUploadUrl || dropzone.getAttribute("hx-get");
  if (!uploadUrl) return;
  window.htmx.ajax("GET", uploadUrl, { target: "#modal-content", swap: "innerHTML" });
}

function photoDropTarget(event) {
  const folder = event.target.closest(".folder-card[data-photo-upload-url]");
  return folder || event.target.closest("[data-photo-dropzone]");
}

function clearPhotoDragState() {
  document.querySelectorAll(".photo-browser.is-dragover, .folder-card.is-dragover").forEach((item) => item.classList.remove("is-dragover"));
}

function ensurePhotoLightbox() {
  let lightbox = document.querySelector("[data-photo-lightbox]");
  if (lightbox) return lightbox;
  lightbox = document.createElement("div");
  lightbox.className = "photo-lightbox";
  lightbox.dataset.photoLightbox = "true";
  lightbox.setAttribute("aria-hidden", "true");
  lightbox.innerHTML = `
    <div class="photo-lightbox-backdrop" data-lightbox-action="close"></div>
    <section class="photo-lightbox-dialog" role="dialog" aria-modal="true" aria-label="Просмотр фотографии">
      <div class="photo-lightbox-toolbar">
        <button class="btn btn-icon" type="button" data-lightbox-action="previous" data-bs-toggle="tooltip" data-bs-title="Предыдущая" aria-label="Предыдущая фотография"><i class="bi bi-chevron-left"></i></button>
        <button class="btn btn-icon" type="button" data-lightbox-action="next" data-bs-toggle="tooltip" data-bs-title="Следующая" aria-label="Следующая фотография"><i class="bi bi-chevron-right"></i></button>
        <span class="photo-lightbox-counter" data-lightbox-counter></span>
        <button class="btn btn-icon" type="button" data-lightbox-action="zoom-out" data-bs-toggle="tooltip" data-bs-title="Уменьшить" aria-label="Уменьшить"><i class="bi bi-zoom-out"></i></button>
        <button class="btn btn-icon" type="button" data-lightbox-action="reset" data-bs-toggle="tooltip" data-bs-title="Масштаб 100%" aria-label="Сбросить масштаб"><span data-lightbox-scale>100%</span></button>
        <button class="btn btn-icon" type="button" data-lightbox-action="zoom-in" data-bs-toggle="tooltip" data-bs-title="Увеличить" aria-label="Увеличить"><i class="bi bi-zoom-in"></i></button>
        <a class="btn btn-icon" data-lightbox-download data-bs-toggle="tooltip" data-bs-title="Скачать" aria-label="Скачать фотографию"><i class="bi bi-download"></i></a>
        <button class="btn btn-icon danger" type="button" data-lightbox-action="close" data-bs-toggle="tooltip" data-bs-title="Закрыть" aria-label="Закрыть"><i class="bi bi-x-lg"></i></button>
      </div>
      <div class="photo-lightbox-viewport" data-lightbox-viewport>
        <img alt="" data-lightbox-image>
      </div>
      <div class="photo-lightbox-caption">
        <strong data-lightbox-description></strong>
        <span data-lightbox-meta></span>
      </div>
    </section>
  `;
  document.body.append(lightbox);
  initTooltips();
  return lightbox;
}

function collectLightboxPhotos(trigger) {
  const browser = trigger.closest("#photo-results") || document;
  return Array.from(browser.querySelectorAll("[data-lightbox-photo]")).map((button) => ({
    trigger: button,
    src: button.dataset.src,
    downloadUrl: button.dataset.downloadUrl,
    description: button.dataset.description || "Описание не добавлено",
    meta: button.dataset.meta || "",
  }));
}

function applyLightboxTransform() {
  const image = document.querySelector("[data-lightbox-image]");
  if (!image) return;
  const { scale, offsetX, offsetY } = photoLightboxState;
  image.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
  image.classList.toggle("is-zoomed", scale > 1);
  const scaleText = document.querySelector("[data-lightbox-scale]");
  if (scaleText) scaleText.textContent = `${Math.round(scale * 100)}%`;
}

function resetLightboxView() {
  photoLightboxState.scale = 1;
  photoLightboxState.offsetX = 0;
  photoLightboxState.offsetY = 0;
  applyLightboxTransform();
}

function renderPhotoLightbox() {
  const lightbox = ensurePhotoLightbox();
  const item = photoLightboxState.items[photoLightboxState.index];
  if (!item) return;
  const image = lightbox.querySelector("[data-lightbox-image]");
  image.src = item.src;
  image.alt = item.description;
  lightbox.querySelector("[data-lightbox-description]").textContent = item.description;
  lightbox.querySelector("[data-lightbox-meta]").textContent = item.meta;
  lightbox.querySelector("[data-lightbox-counter]").textContent = `${photoLightboxState.index + 1} / ${photoLightboxState.items.length}`;
  const download = lightbox.querySelector("[data-lightbox-download]");
  download.href = item.downloadUrl;
  resetLightboxView();
}

function openPhotoLightbox(trigger) {
  photoLightboxState.items = collectLightboxPhotos(trigger);
  photoLightboxState.index = Math.max(0, photoLightboxState.items.findIndex((item) => item.trigger === trigger));
  const lightbox = ensurePhotoLightbox();
  renderPhotoLightbox();
  lightbox.classList.add("is-open");
  lightbox.setAttribute("aria-hidden", "false");
  document.body.classList.add("has-photo-lightbox");
}

function closePhotoLightbox() {
  const lightbox = document.querySelector("[data-photo-lightbox]");
  if (!lightbox) return;
  lightbox.classList.remove("is-open");
  lightbox.setAttribute("aria-hidden", "true");
  document.body.classList.remove("has-photo-lightbox");
  photoLightboxState.isDragging = false;
}

function navigatePhotoLightbox(direction) {
  if (!photoLightboxState.items.length) return;
  photoLightboxState.index = (photoLightboxState.index + direction + photoLightboxState.items.length) % photoLightboxState.items.length;
  renderPhotoLightbox();
}

function zoomPhotoLightbox(delta) {
  const nextScale = Math.min(4, Math.max(1, photoLightboxState.scale + delta));
  photoLightboxState.scale = Number(nextScale.toFixed(2));
  if (photoLightboxState.scale === 1) {
    photoLightboxState.offsetX = 0;
    photoLightboxState.offsetY = 0;
  }
  applyLightboxTransform();
}

function togglePhotoLightboxZoom() {
  if (photoLightboxState.scale <= 1) {
    photoLightboxState.scale = 2;
  } else {
    photoLightboxState.scale = 1;
    photoLightboxState.offsetX = 0;
    photoLightboxState.offsetY = 0;
  }
  applyLightboxTransform();
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

document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target.id === "modal-content") {
    initCustomSelects(event.detail.target);
    initTooltips();
    autoDismissAlerts();
    bootstrap.Modal.getOrCreateInstance(document.getElementById("modal-root")).show();
    const bulkForm = event.detail.target.querySelector("[data-bulk-photo-form]");
    if (bulkForm) {
      renderBulkPhotoFiles(bulkForm, pendingBulkPhotoFiles);
      pendingBulkPhotoFiles = [];
    }
    event.detail.target.querySelectorAll("[data-request-photo-box]").forEach(syncRequestPhotoPicker);
    return;
  }
  saveTableStateFromHtmxEvent(event);
  initCustomSelects(event.detail.target);
  initTooltips();
  autoDismissAlerts();
  event.detail.target.querySelectorAll?.("[data-request-photo-box]").forEach(syncRequestPhotoPicker);
  event.detail.target.closest?.("[data-request-photo-box]") && syncRequestPhotoPicker(event.detail.target.closest("[data-request-photo-box]"));
  applyCollapsedPanels();
  scrollAfterPaginationSwap(event);
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
  uploadBulkPhotos(bulkForm);
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
    const picker = event.target.closest("[data-single-file-picker]");
    const name = picker?.querySelector("[data-single-file-name]");
    if (name) name.textContent = event.target.files?.[0]?.name || "Изображение не выбрано";
    return;
  }
  if (!event.target.matches("[data-bulk-photo-input]")) return;
  const form = event.target.closest("[data-bulk-photo-form]");
  if (form) renderBulkPhotoFiles(form, event.target.files);
});

document.addEventListener("dragover", (event) => {
  const dropzone = photoDropTarget(event);
  if (!dropzone) return;
  event.preventDefault();
  clearPhotoDragState();
  dropzone.classList.add("is-dragover");
});

document.addEventListener("dragleave", (event) => {
  const dropzone = photoDropTarget(event);
  if (!dropzone || dropzone.contains(event.relatedTarget)) return;
  dropzone.classList.remove("is-dragover");
});

document.addEventListener("drop", (event) => {
  const dropzone = photoDropTarget(event);
  if (!dropzone) return;
  event.preventDefault();
  clearPhotoDragState();
  openBulkPhotoModal(dropzone, event.dataTransfer.files);
});

document.addEventListener("beforeinput", (event) => {
  if (!event.target.matches(".auth-ascii-input") || !event.data) return;
  if (/[^\x21-\x7E]/.test(event.data)) event.preventDefault();
});

document.addEventListener("click", (event) => {
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
    resetTableStateToSingleOrgan(resetTableState.dataset.resetOrganId);
  }

  const organMode = event.target.closest("[data-organ-mode]");
  if (organMode) {
    event.preventDefault();
    setOrganMode(organMode.dataset.organMode);
    if (!isMultiOrganMode()) {
      const firstChecked = checkedOrganIds()[0];
      const organ = firstChecked ? findOrganById(firstChecked) : document.querySelector(".organ-item.active[data-organ-id]");
      if (organ) {
        setActiveOrgan(organ);
        loadOrganInfo(organ.dataset.organId);
      }
    }
    const department = preferredDepartmentForOrgan(window.selectedOrgan);
    if (department) {
      setActiveDepartment(department);
      loadDepartment(department);
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
    document.getElementById("workspace").innerHTML = '<div class="empty-state">Выберите хотя бы один территориальный орган</div>';
    return;
  }

  const productSuggestion = event.target.closest("[data-tmc-product-suggestion]");
  if (productSuggestion) {
    chooseTmcProductSuggestion(productSuggestion);
    return;
  }

  const lightboxPhoto = event.target.closest("[data-lightbox-photo]");
  if (lightboxPhoto) {
    event.preventDefault();
    openPhotoLightbox(lightboxPhoto);
    return;
  }

  if (event.target.matches("[data-lightbox-image]")) {
    event.preventDefault();
    if (photoLightboxState.didDrag) {
      photoLightboxState.didDrag = false;
      return;
    }
    togglePhotoLightboxZoom();
    return;
  }

  const lightboxAction = event.target.closest("[data-lightbox-action]");
  if (lightboxAction) {
    event.preventDefault();
    const action = lightboxAction.dataset.lightboxAction;
    if (action === "close") closePhotoLightbox();
    if (action === "previous") navigatePhotoLightbox(-1);
    if (action === "next") navigatePhotoLightbox(1);
    if (action === "zoom-in") zoomPhotoLightbox(.25);
    if (action === "zoom-out") zoomPhotoLightbox(-.25);
    if (action === "reset") resetLightboxView();
    return;
  }

  const customSelectTrigger = event.target.closest("[data-custom-select-trigger]");
  if (customSelectTrigger) {
    toggleCustomSelect(customSelectTrigger.closest("[data-custom-select]"));
    return;
  }

  const customSelectOption = event.target.closest("[data-custom-select-option]");
  if (customSelectOption) {
    chooseCustomSelectOption(customSelectOption);
    return;
  }

  if (!event.target.closest("[data-custom-select]")) closeCustomSelects();
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
    if (form) removeBulkPhotoFile(form, Number(bulkRemove.dataset.removeBulkPhoto));
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

document.addEventListener("keydown", (event) => {
  if (document.querySelector("[data-photo-lightbox].is-open")) {
    if (event.key === "Escape") closePhotoLightbox();
    if (event.key === "ArrowLeft") navigatePhotoLightbox(-1);
    if (event.key === "ArrowRight") navigatePhotoLightbox(1);
    if (event.key === "+" || event.key === "=") zoomPhotoLightbox(.25);
    if (event.key === "-") zoomPhotoLightbox(-.25);
    if (event.key === "0") resetLightboxView();
  }

  const trigger = event.target.closest("[data-custom-select-trigger]");
  if (trigger && ["Enter", " ", "ArrowDown"].includes(event.key)) {
    event.preventDefault();
    openCustomSelect(trigger.closest("[data-custom-select]"));
    return;
  }
  if (event.key === "Escape") {
    closeCustomSelects();
    closeAllTmcProductSuggestions();
  }
});

document.addEventListener("wheel", (event) => {
  if (!event.target.closest("[data-lightbox-viewport]")) return;
  event.preventDefault();
  zoomPhotoLightbox(event.deltaY < 0 ? .18 : -.18);
}, { passive: false });

document.addEventListener("pointerdown", (event) => {
  if (!event.target.matches("[data-lightbox-image]") || photoLightboxState.scale <= 1) return;
  event.preventDefault();
  photoLightboxState.isDragging = true;
  photoLightboxState.dragStartX = event.clientX;
  photoLightboxState.dragStartY = event.clientY;
  photoLightboxState.dragOriginX = photoLightboxState.offsetX;
  photoLightboxState.dragOriginY = photoLightboxState.offsetY;
  photoLightboxState.didDrag = false;
  event.target.setPointerCapture?.(event.pointerId);
});

document.addEventListener("pointermove", (event) => {
  if (!photoLightboxState.isDragging) return;
  if (Math.abs(event.clientX - photoLightboxState.dragStartX) > 3 || Math.abs(event.clientY - photoLightboxState.dragStartY) > 3) {
    photoLightboxState.didDrag = true;
  }
  photoLightboxState.offsetX = photoLightboxState.dragOriginX + event.clientX - photoLightboxState.dragStartX;
  photoLightboxState.offsetY = photoLightboxState.dragOriginY + event.clientY - photoLightboxState.dragStartY;
  applyLightboxTransform();
});

document.addEventListener("pointerup", () => {
  photoLightboxState.isDragging = false;
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
  document.querySelectorAll(".auth-ascii-input").forEach(normalizeAuthInput);
  autoDismissAlerts();
  applyCollapsedPanels();
  restoreCheckedOrgans();
  const savedOrganId = storedValue(ORGAN_STORAGE_KEY);
  const organ = savedOrganId
    ? findOrganById(savedOrganId)
    : document.querySelector(".organ-item[data-organ-id]");
  if (organ) {
    setActiveOrgan(organ);
    if (isMultiOrganMode()) {
      ensureMultiSelection();
      renderMultiOrganInfo();
    }
    syncOrganModeButtons();
    const department = preferredDepartmentForOrgan(window.selectedOrgan);
    if (department) {
      setActiveDepartment(department);
      loadDepartment(department);
    }
  }
});

window.addEventListener("resize", () => {
  syncHeaderHeight();
});
