// Dashboard table search, grouped-row hover, and status dates.
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

function syncCompletedDate(form) {
  const status = form.querySelector('[name="status"]');
  const completedDate = form.querySelector('[name="completed_at"]') || form.querySelector('[name="due_date"]');
  if (!status || !completedDate) return;
  const picker = completedDate.closest("[data-date-range-picker]");
  const isTerminal = ["done", "rejected"].includes(status.value);

  if (!isTerminal) {
    if (picker?.setDateRangePickerValues) picker.setDateRangePickerValues("");
    else completedDate.value = "";
    if (picker?.setDateRangePickerDisabled) picker.setDateRangePickerDisabled(true);
    else completedDate.disabled = true;
    return;
  }

  if (picker?.setDateRangePickerDisabled) picker.setDateRangePickerDisabled(false);
  else completedDate.disabled = false;
  if (!completedDate.value) {
    const today = todayInputValue();
    if (picker?.setDateRangePickerValues) picker.setDateRangePickerValues(today);
    else completedDate.value = today;
  }
}

function syncCompletedDateForms(scope = document) {
  const selector = "[data-tmc-request-form], [data-status-form]";
  const forms = scope.matches?.(selector) ? [scope] : Array.from(scope.querySelectorAll?.(selector) || []);
  forms.forEach(syncCompletedDate);
}
