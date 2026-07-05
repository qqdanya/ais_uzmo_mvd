// Table search, grouped-row hover, status dates, and modal/search shortcuts.
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
