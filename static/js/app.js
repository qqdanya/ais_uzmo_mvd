window.selectedOrgan = window.selectedOrgan || null;
const ORGAN_STORAGE_KEY = "asu-zmo:selected-organ";
const DEPARTMENT_STORAGE_PREFIX = "asu-zmo:last-department:";
const COLLAPSED_PANELS_KEY = "asu-zmo:collapsed-panels";
let htmxRequests = 0;
let loadingFailsafeTimer = null;
let tooltipTarget = null;
let pendingBulkPhotoFiles = [];

function rememberSelectedOrgan(organId) {
  window.selectedOrgan = Number(organId);
  sessionStorage.setItem(ORGAN_STORAGE_KEY, String(window.selectedOrgan));
}

function departmentStorageKey(organId) {
  return `${DEPARTMENT_STORAGE_PREFIX}${organId}`;
}

function findDepartmentBySlug(slug) {
  return Array.from(document.querySelectorAll(".department-item[data-department-slug]"))
    .find((item) => item.dataset.departmentSlug === slug);
}

function findOrganById(organId) {
  return Array.from(document.querySelectorAll(".organ-item[data-organ-id]"))
    .find((item) => item.dataset.organId === String(organId));
}

function normalizeAuthInput(input) {
  const value = input.value.replace(/[^\x21-\x7E]/g, "");
  if (input.value !== value) input.value = value;
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
    const title = el.getAttribute("data-bs-title") || el.getAttribute("title");
    if (!title) return;
    el.dataset.uiTooltip = title;
    el.removeAttribute("title");
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

function hideTooltip() {
  tooltipTarget = null;
  document.querySelector(".ui-tooltip")?.remove();
}

function showTooltip(target) {
  const text = target.dataset.uiTooltip;
  if (!text) return;
  hideTooltip();
  tooltipTarget = target;
  const tooltip = document.createElement("div");
  tooltip.className = "ui-tooltip";
  tooltip.textContent = text;
  document.body.appendChild(tooltip);
  positionTooltip(target, tooltip);
}

function positionTooltip(target = tooltipTarget, tooltip = document.querySelector(".ui-tooltip")) {
  if (!target || !tooltip || !document.body.contains(target)) {
    hideTooltip();
    return;
  }
  const rect = target.getBoundingClientRect();
  const tipRect = tooltip.getBoundingClientRect();
  const gap = 8;
  const top = rect.top >= tipRect.height + gap + 4
    ? rect.top - tipRect.height - gap
    : rect.bottom + gap;
  const left = Math.min(
    Math.max(rect.left + (rect.width - tipRect.width) / 2, 8),
    window.innerWidth - tipRect.width - 8
  );
  tooltip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
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
  const query = input.value.trim().toLowerCase();
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
    const groupText = groupRows.map((row) => row.textContent).join(" ").toLowerCase();
    const isVisible = !query || groupText.includes(query);
    groupRows.forEach((row) => {
      row.hidden = !isVisible;
    });
    if (isVisible) visibleRows += groupRows.length;
  });

  rows.filter((row) => !row.dataset.rowGroup).forEach((row) => {
    const isVisible = !query || row.textContent.toLowerCase().includes(query);
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
  const images = Array.from(files).filter((file) => file.type.startsWith("image/"));
  const transfer = new DataTransfer();
  images.forEach((file) => transfer.items.add(file));
  input.files = transfer.files;
  list.replaceChildren();
  if (!images.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Изображения не выбраны";
    list.append(empty);
    return;
  }
  images.forEach((file, index) => {
    const item = document.createElement("div");
    item.className = "bulk-photo-item";
    item.dataset.bulkPhotoIndex = String(index);
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
    item.append(meta, label, textarea);
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

function loadDepartment(department) {
  if (!department || !window.htmx) return;
  if (!window.selectedOrgan) {
    const activeOrgan = document.querySelector(".organ-item.active[data-organ-id]") || document.querySelector(".organ-item[data-organ-id]");
    window.selectedOrgan = activeOrgan ? Number(activeOrgan.dataset.organId) : null;
  }
  if (!window.selectedOrgan) return;
  sessionStorage.setItem(departmentStorageKey(window.selectedOrgan), department.dataset.departmentSlug);
  const url = `/organs/${window.selectedOrgan}/departments/${department.dataset.departmentSlug}/`;
  window.htmx.ajax("GET", url, { target: "#workspace", swap: "innerHTML" });
}

function setActiveOrgan(organ) {
  document.querySelectorAll(".organ-item").forEach((item) => {
    item.classList.remove("active");
    item.removeAttribute("aria-current");
  });
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
  const savedSlug = sessionStorage.getItem(departmentStorageKey(organId));
  if (savedSlug) {
    const savedDepartment = findDepartmentBySlug(savedSlug);
    if (savedDepartment) return savedDepartment;
  }
  return document.querySelector(".department-item[data-department-slug]");
}

document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target.id === "modal-content") {
    bootstrap.Modal.getOrCreateInstance(document.getElementById("modal-root")).show();
    const bulkForm = event.detail.target.querySelector("[data-bulk-photo-form]");
    if (bulkForm) {
      renderBulkPhotoFiles(bulkForm, pendingBulkPhotoFiles);
      pendingBulkPhotoFiles = [];
    }
  }
  initCustomSelects(event.detail.target);
  initTooltips();
  autoDismissAlerts();
  applyCollapsedPanels();
});

document.body.addEventListener("htmx:beforeRequest", startHtmxRequest);

document.body.addEventListener("htmx:afterRequest", finishHtmxRequest);

document.body.addEventListener("htmx:responseError", () => {
  resetHtmxLoading();
  showToast("Не удалось выполнить действие.", "danger");
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

document.body.addEventListener("modal:close", () => {
  const modal = bootstrap.Modal.getInstance(document.getElementById("modal-root"));
  if (modal) modal.hide();
});

document.addEventListener("input", (event) => {
  if (event.target.matches(".auth-ascii-input")) {
    normalizeAuthInput(event.target);
    return;
  }
  if (event.target.matches("[data-table-search]")) {
    filterCurrentTable(event.target);
    return;
  }
  if (event.target.id !== "organ-search") return;
  const query = event.target.value.toLowerCase();
  document.querySelectorAll(".organ-item").forEach((item) => {
    item.hidden = !item.dataset.search.includes(query);
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
  hideTooltip();
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

document.addEventListener("keydown", (event) => {
  const trigger = event.target.closest("[data-custom-select-trigger]");
  if (trigger && ["Enter", " ", "ArrowDown"].includes(event.key)) {
    event.preventDefault();
    openCustomSelect(trigger.closest("[data-custom-select]"));
    return;
  }
  if (event.key === "Escape") closeCustomSelects();
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
  const savedOrganId = sessionStorage.getItem(ORGAN_STORAGE_KEY);
  const organ = savedOrganId
    ? findOrganById(savedOrganId)
    : document.querySelector(".organ-item[data-organ-id]");
  if (organ) {
    setActiveOrgan(organ);
    const department = preferredDepartmentForOrgan(window.selectedOrgan);
    if (department) {
      setActiveDepartment(department);
      loadDepartment(department);
    }
  }
});

document.addEventListener("mouseover", (event) => {
  const target = event.target.closest("[data-ui-tooltip]");
  if (target) showTooltip(target);
});
document.addEventListener("focusin", (event) => {
  const target = event.target.closest("[data-ui-tooltip]");
  if (target) showTooltip(target);
});
document.addEventListener("mouseout", (event) => {
  if (tooltipTarget && !event.relatedTarget?.closest?.("[data-ui-tooltip]")) hideTooltip();
});
document.addEventListener("focusout", hideTooltip);
document.addEventListener("scroll", () => positionTooltip(), true);
window.addEventListener("resize", () => {
  syncHeaderHeight();
  positionTooltip();
});
