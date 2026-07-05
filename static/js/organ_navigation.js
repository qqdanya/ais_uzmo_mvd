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
