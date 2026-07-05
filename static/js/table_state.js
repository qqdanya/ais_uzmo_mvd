// Persistent table-tab and filter state helpers.
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
