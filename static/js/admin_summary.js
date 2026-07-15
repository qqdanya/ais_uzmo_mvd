(() => {
  const root = document.querySelector("[data-admin-summary-root]");
  const shell = document.getElementById("admin-panel-refresh");
  const dataScript = document.getElementById("admin-summary-data");
  if (!root || !shell || !dataScript) return;

  const STORAGE_ORGANS_KEY = "asu-zmo:admin-summary-organs";
  const STORAGE_ALL_ORGANS_KEY = "asu-zmo:admin-summary-all-organs";
  const DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
  const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];

  let state = JSON.parse(dataScript.textContent || "{}");
  let selectedStart = state.period?.date_from ? parseIsoDate(state.period.date_from) : firstDayOfMonth(new Date());
  let selectedEnd = state.period?.date_to ? parseIsoDate(state.period.date_to) : lastDayOfMonth(new Date());
  let selectedPeriod = state.period?.code || "current_month";
  let calendarCenter = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
  let calendarPickerYear = calendarCenter.getFullYear();
  let pendingRangeStart = null;
  let dynamicsChart = null;
  let dynamicsMode = "all";
  let dynamicsGranularity = "day";
  let dynamicsPeriodKey = "";

  const periodLabel = root.querySelector("[data-admin-period-label]");
  const calendar = root.querySelector("[data-admin-calendar]");
  const calendarCaption = root.querySelector("[data-admin-calendar-caption]");
  const calendarJumpToggle = root.querySelector("[data-admin-calendar-jump-toggle]");
  const calendarJumpPanel = root.querySelector("[data-admin-calendar-jump-panel]");
  const calendarYear = root.querySelector("[data-admin-calendar-year]");
  const calendarMonthPicker = root.querySelector("[data-admin-calendar-month-picker]");
  const reportComparison = root.querySelector("#admin-report-comparison");
  const reportCustomPeriod = root.querySelector("[data-admin-report-custom-period]");
  const reportCustomPicker = reportCustomPeriod?.querySelector("[data-date-range-picker]");
  const reportComparisonFrom = reportCustomPicker?.querySelector("[data-date-range-from]");
  const reportComparisonTo = reportCustomPicker?.querySelector("[data-date-range-to]");
  const reportMetrics = root.querySelector(".admin-report-metrics");
  const reportChartLayout = root.querySelector("#admin-report-chart-layout");
  const reportChartLayoutField = root.querySelector("[data-admin-report-layout-field]");
  const summaryUrl = shell.dataset.summaryUrl;

  function parseIsoDate(value) {
    if (!value) return null;
    const [year, month, day] = value.split("-").map(Number);
    return new Date(year, month - 1, day);
  }

  function isoDate(date) {
    if (!date) return "";
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function displayDate(date) {
    if (!date) return "";
    return `${String(date.getDate()).padStart(2, "0")}.${String(date.getMonth() + 1).padStart(2, "0")}.${date.getFullYear()}`;
  }

  function firstDayOfMonth(date) {
    return new Date(date.getFullYear(), date.getMonth(), 1);
  }

  function lastDayOfMonth(date) {
    return new Date(date.getFullYear(), date.getMonth() + 1, 0);
  }

  function addMonths(date, value) {
    return new Date(date.getFullYear(), date.getMonth() + value, 1);
  }

  function mondayOfWeek(date) {
    const result = new Date(date);
    const day = result.getDay() || 7;
    result.setDate(result.getDate() - day + 1);
    return result;
  }

  function syncReportComparisonInputs(fillDefaults = false) {
    const isCustom = reportComparison?.value === "custom";
    const hasComparison = reportComparison?.value !== "none";
    if (reportCustomPeriod) reportCustomPeriod.hidden = !isCustom;
    if (reportChartLayoutField) reportChartLayoutField.hidden = !hasComparison;
    if (!isCustom || !fillDefaults || !selectedStart || !selectedEnd) return;
    if (reportComparisonFrom?.value && reportComparisonTo?.value) return;
    const duration = Math.round((selectedEnd - selectedStart) / 86400000) + 1;
    const comparisonEnd = new Date(selectedStart);
    comparisonEnd.setDate(comparisonEnd.getDate() - 1);
    const comparisonStart = new Date(comparisonEnd);
    comparisonStart.setDate(comparisonStart.getDate() - duration + 1);
    reportCustomPicker?.setDateRangePickerValues?.(
      isoDate(comparisonStart),
      isoDate(comparisonEnd),
    );
  }

  function sameDay(left, right) {
    return left && right && left.getFullYear() === right.getFullYear() && left.getMonth() === right.getMonth() && left.getDate() === right.getDate();
  }

  function betweenDates(date, start, end) {
    if (!date || !start || !end) return false;
    return date >= start && date <= end;
  }

  function adminOrganCheckboxes() {
    return Array.from(root.querySelectorAll("[data-admin-organ-checkbox]"));
  }

  function allOrgansCheckbox() {
    return root.querySelector("[data-admin-all-organs]");
  }

  function storedValue(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function storeValue(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      // ignore unavailable storage
    }
  }

  function restoreAdminOrgSelection() {
    const all = storedValue(STORAGE_ALL_ORGANS_KEY);
    const saved = new Set((storedValue(STORAGE_ORGANS_KEY) || "").split(",").filter(Boolean));
    const useAll = all !== "false" || saved.size === 0;
    const allInput = allOrgansCheckbox();
    if (allInput) allInput.checked = useAll;
    adminOrganCheckboxes().forEach((checkbox) => {
      checkbox.checked = useAll || saved.has(checkbox.value);
    });
    syncAdminOrgAllState(false);
  }

  function selectedOrganIds() {
    const allInput = allOrgansCheckbox();
    if (allInput?.checked) return [];
    return adminOrganCheckboxes().filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.value);
  }

  function saveAdminOrgSelection() {
    const allInput = allOrgansCheckbox();
    storeValue(STORAGE_ALL_ORGANS_KEY, allInput?.checked ? "true" : "false");
    storeValue(STORAGE_ORGANS_KEY, adminOrganCheckboxes().filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.value).join(","));
  }

  function adminOrganNameFromCheckbox(checkbox) {
    const text = checkbox.closest("[data-admin-organ-row]")?.querySelector("[data-admin-organ-toggle] span")?.textContent || "";
    return text.replace(/^\s*\d+(?:[.,]\d+)?\.?\s*/, "").trim();
  }

  function updateAdminOrgVisualState() {
    const selector = root.querySelector("[data-admin-organ-selector]");
    const checkboxes = adminOrganCheckboxes();
    const checked = checkboxes.filter((checkbox) => checkbox.checked);
    const total = checkboxes.length;
    const allInput = allOrgansCheckbox();
    const isAllSelected = total > 0 && checked.length === total;
    const summary = root.querySelector("[data-admin-organ-summary]");
    const badge = root.querySelector("[data-admin-organ-filter-badge]");

    checkboxes.forEach((checkbox) => {
      checkbox.closest("[data-admin-organ-row]")?.classList.toggle("is-selected", checkbox.checked);
    });

    root.querySelector(".admin-organ-all-row")?.classList.toggle("is-selected", Boolean(allInput?.checked));
    selector?.classList.toggle("has-custom-organ-filter", !isAllSelected);

    if (summary) {
      if (!total) {
        summary.textContent = "Территориальные органы не загружены";
      } else if (isAllSelected) {
        summary.textContent = `Выбрано: все ${formatNumber(total)} территориальных органов`;
      } else if (!checked.length) {
        summary.textContent = "Не выбран ни один территориальный орган";
      } else if (checked.length === 1) {
        summary.textContent = `Выбран: ${adminOrganNameFromCheckbox(checked[0])}`;
      } else {
        summary.textContent = `Выбрано: ${formatNumber(checked.length)} из ${formatNumber(total)}`;
      }
    }

    if (badge) {
      badge.hidden = isAllSelected;
      badge.textContent = checked.length ? `Фильтр: ${formatNumber(checked.length)}` : "Фильтр: 0";
    }
  }

  function syncAdminOrgAllState(save = true) {
    const checkboxes = adminOrganCheckboxes();
    const allInput = allOrgansCheckbox();
    if (!allInput) return;
    const checkedCount = checkboxes.filter((checkbox) => checkbox.checked).length;
    allInput.checked = checkedCount === checkboxes.length;
    allInput.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
    updateAdminOrgVisualState();
    if (save) saveAdminOrgSelection();
  }

  function formatNumber(value) {
    return new Intl.NumberFormat("ru-RU").format(Number(value || 0));
  }

  function metricLabel(value) {
    return {
      total: "Поступило заявок",
      in_work: "В работе",
      done: "Исполнено",
      rejected: "Отклонено",
      stale: "Просроченные",
    }[value] || "В работе";
  }

  function setPresetActive(code) {
    root.querySelectorAll("[data-admin-period-preset]").forEach((button) => {
      button.classList.toggle("active", button.dataset.adminPeriodPreset === code);
    });
  }

  function updatePeriodLabel() {
    if (!periodLabel) return;
    periodLabel.textContent = selectedPeriod === "all" ? "Период: за всё время" : `Период: ${displayDate(selectedStart)} – ${displayDate(selectedEnd)}`;
  }

  function renderCalendar() {
    if (!calendar) return;
    calendar.replaceChildren();
    const today = new Date();
    const months = [addMonths(calendarCenter, -1), calendarCenter, addMonths(calendarCenter, 1)];
    if (calendarCaption) {
      calendarCaption.textContent = `${MONTHS[months[0].getMonth()]} ${months[0].getFullYear()} – ${MONTHS[months[2].getMonth()]} ${months[2].getFullYear()}`;
    }
    months.forEach((monthDate, index) => {
      const month = document.createElement("div");
      month.className = `admin-calendar-month${index === 1 ? " is-current-month" : ""}`;
      const title = document.createElement("div");
      title.className = "admin-calendar-month-title";
      title.textContent = `${MONTHS[monthDate.getMonth()]} ${monthDate.getFullYear()}`;
      const week = document.createElement("div");
      week.className = "admin-calendar-weekdays";
      DAYS.forEach((label) => {
        const day = document.createElement("span");
        day.textContent = label;
        week.append(day);
      });
      const grid = document.createElement("div");
      grid.className = "admin-calendar-days";
      const first = firstDayOfMonth(monthDate);
      const last = lastDayOfMonth(monthDate);
      const firstWeekday = first.getDay() || 7;
      for (let i = 1; i < firstWeekday; i += 1) {
        const empty = document.createElement("span");
        empty.className = "admin-calendar-empty";
        grid.append(empty);
      }
      for (let day = 1; day <= last.getDate(); day += 1) {
        const date = new Date(monthDate.getFullYear(), monthDate.getMonth(), day);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "admin-calendar-day";
        button.textContent = String(day);
        button.dataset.adminCalendarDay = isoDate(date);
        if (sameDay(date, today)) button.classList.add("is-today");
        if (sameDay(date, selectedStart)) button.classList.add("is-range-start");
        if (sameDay(date, selectedEnd)) button.classList.add("is-range-end");
        if (selectedPeriod !== "all" && betweenDates(date, selectedStart, selectedEnd)) button.classList.add("is-in-range");
        if (pendingRangeStart && sameDay(date, pendingRangeStart)) button.classList.add("is-pending");
        grid.append(button);
      }
      month.append(title, week, grid);
      calendar.append(month);
    });
  }

  function renderCalendarJump() {
    if (!calendarMonthPicker) return;
    if (calendarYear) calendarYear.textContent = String(calendarPickerYear);
    calendarMonthPicker.replaceChildren();
    MONTHS.forEach((label, monthIndex) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label.slice(0, 3);
      button.dataset.adminCalendarMonth = String(monthIndex);
      button.classList.toggle("active", calendarPickerYear === calendarCenter.getFullYear() && monthIndex === calendarCenter.getMonth());
      calendarMonthPicker.append(button);
    });
  }

  function setCalendarJumpOpen(open) {
    if (!calendarJumpPanel || !calendarJumpToggle) return;
    calendarJumpPanel.hidden = !open;
    calendarJumpToggle.setAttribute("aria-expanded", String(open));
    if (open) {
      calendarPickerYear = calendarCenter.getFullYear();
      renderCalendarJump();
    }
  }

  function paramsForRequest() {
    const params = new URLSearchParams();
    params.set("org_metric", root.querySelector("[data-admin-org-metric]")?.value || "in_work");
    if (selectedPeriod === "all") {
      params.set("period", "all");
    } else {
      params.set("period", selectedPeriod || "custom");
      params.set("date_from", isoDate(selectedStart));
      params.set("date_to", isoDate(selectedEnd));
    }
    const ids = selectedOrganIds();
    ids.forEach((id) => params.append("organ_ids", id));
    const allInput = allOrgansCheckbox();
    if (allInput && !allInput.checked && ids.length === 0) {
      params.set("organ_filter_empty", "1");
    }
    return params;
  }

  async function refreshSummary() {
    if (!summaryUrl) return;
    const url = `${summaryUrl}?${paramsForRequest().toString()}`;
    try {
      shell.classList.add("is-loading-summary");
      const response = await fetch(url, { headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state = await response.json();
      renderSummary();
    } catch (error) {
      console.error(error);
      document.body.dispatchEvent(new CustomEvent("toast", { detail: { message: "Не удалось обновить оперативную сводку.", level: "danger" } }));
    } finally {
      shell.classList.remove("is-loading-summary");
    }
  }

  function renderKpi() {
    const kpi = state.kpi || {};
    Object.entries(kpi).forEach(([key, value]) => {
      const node = root.querySelector(`[data-kpi="${CSS.escape(key)}"]`);
      if (node) node.textContent = formatNumber(value);
    });
  }

  function activeDynamicsSeries() {
    const dynamics = state.dynamics || {};
    return dynamics[dynamicsGranularity] || dynamics.day || dynamics;
  }

  function syncDynamicsControls() {
    root.querySelectorAll("[data-dynamics-mode]").forEach((button) => {
      const isActive = button.dataset.dynamicsMode === dynamicsMode;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });
    root.querySelectorAll("[data-dynamics-granularity]").forEach((button) => {
      const isActive = button.dataset.dynamicsGranularity === dynamicsGranularity;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });
    const subtitle = root.querySelector("[data-dynamics-subtitle]");
    const labels = { day: "дням", week: "неделям", month: "месяцам" };
    if (subtitle) subtitle.textContent = `Поступление, исполнение и отклонение заявок по ${labels[dynamicsGranularity] || labels.day}`;
  }

  function chartDatasets(dynamics) {
    const datasets = {
      incoming: {
        label: "Поступило",
        data: dynamics.incoming || [],
        borderColor: "#1769aa",
        backgroundColor: "rgba(23, 105, 170, .12)",
        tension: .32,
        pointRadius: 2,
        borderWidth: 2,
      },
      done: {
        label: "Исполнено",
        data: dynamics.done || [],
        borderColor: "#1f8a4c",
        backgroundColor: "rgba(31, 138, 76, .12)",
        tension: .32,
        pointRadius: 2,
        borderWidth: 2,
      },
      rejected: {
        label: "Отклонено",
        data: dynamics.rejected || [],
        borderColor: "#b85252",
        backgroundColor: "rgba(184, 82, 82, .12)",
        tension: .32,
        pointRadius: 2,
        borderWidth: 2,
      },
    };
    return dynamicsMode === "all" ? [datasets.incoming, datasets.done, datasets.rejected] : [datasets[dynamicsMode] || datasets.incoming];
  }

  function renderDynamicsChart() {
    const canvas = document.getElementById("admin-dynamics-chart");
    if (!canvas || !window.Chart) return;
    const dynamics = activeDynamicsSeries();
    const data = {
      labels: dynamics.labels || [],
      datasets: chartDatasets(dynamics),
    };
    if (dynamicsChart) {
      dynamicsChart.data = data;
      dynamicsChart.update();
      return;
    }
    dynamicsChart = new Chart(canvas, {
      type: "line",
      data,
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: true, labels: { usePointStyle: true, boxWidth: 8 } },
          tooltip: { mode: "index", intersect: false },
        },
        interaction: { mode: "nearest", axis: "x", intersect: false },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 14 } },
          y: { beginAtZero: true, ticks: { precision: 0 } },
        },
      },
    });
  }

  function renderBarList(selector, rows, emptyText, limit = null) {
    const target = root.querySelector(selector);
    if (!target) return;
    target.replaceChildren();
    const sourceRows = Array.isArray(rows) ? rows : [];
    const visibleRows = limit ? sourceRows.slice(0, limit) : sourceRows;
    if (!visibleRows.length) {
      target.innerHTML = `<div class="admin-empty admin-empty-compact"><i class="bi bi-bar-chart"></i><strong>${emptyText}</strong></div>`;
      return;
    }
    visibleRows.forEach((row) => {
      const item = document.createElement("div");
      item.className = "admin-bar-row";
      item.innerHTML = `
        <div class="admin-bar-label"><span title="${escapeHtml(row.name)}">${escapeHtml(row.name)}</span><strong>${formatNumber(row.value)}</strong></div>
        <div class="admin-bar-track"><span style="width: ${Math.max(2, Number(row.percent || 0))}%"></span></div>
      `;
      target.append(item);
    });
    if (limit && sourceRows.length > limit) {
      const note = document.createElement("div");
      note.className = "admin-bar-note";
      note.textContent = `Показан ТОП-${limit}. Всего в выборке: ${sourceRows.length}.`;
      target.append(note);
    }
  }

  function renderAttention() {
    const target = root.querySelector("[data-attention-list]");
    if (!target) return;
    target.replaceChildren();
    const items = state.attention_requests || [];
    if (!items.length) {
      target.innerHTML = `<div class="admin-empty"><i class="bi bi-check2-circle"></i><strong>Нет заявок, требующих внимания</strong><span>По выбранным органам нет заявок в работе более ${formatNumber(state.request_stale_workdays || 14)} рабочих дней.</span></div>`;
      return;
    }
    items.forEach((item) => {
      const row = document.createElement("article");
      row.className = "admin-attention-row";
      const detailUrl = item.detail_url
        ? `<a class="btn btn-sm btn-outline-primary admin-attention-link" href="${escapeHtml(item.detail_url)}"><i class="bi bi-box-arrow-up-right"></i> Открыть</a>`
        : "";
      row.innerHTML = `
        <div class="admin-attention-main">
          <strong>${escapeHtml(item.title || `Заявка № ${item.number}`)}</strong>
          <span>${escapeHtml(item.organ)} · ${escapeHtml(item.department)} · ${escapeHtml(item.table)}</span>
        </div>
        <div class="admin-attention-date">
          <span>${escapeHtml(item.request_date)}</span>
          <strong>${formatNumber(item.days)} дн.</strong>
        </div>
        ${detailUrl}
      `;
      target.append(row);
    });
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function renderSummary() {
    if (state.period) {
      selectedPeriod = state.period.code || selectedPeriod;
      if (state.period.date_from) selectedStart = parseIsoDate(state.period.date_from);
      if (state.period.date_to) selectedEnd = parseIsoDate(state.period.date_to);
    }
    const nextDynamicsPeriodKey = `${state.period?.code || ""}:${state.period?.date_from || ""}:${state.period?.date_to || ""}`;
    if (nextDynamicsPeriodKey !== dynamicsPeriodKey) {
      dynamicsPeriodKey = nextDynamicsPeriodKey;
      dynamicsGranularity = state.dynamics?.default_granularity || "day";
    }
    updatePeriodLabel();
    renderKpi();
    syncDynamicsControls();
    renderDynamicsChart();
    renderBarList("[data-org-chart]", state.org_chart, "Нет данных по территориальным органам");
    const metric = root.querySelector("[data-admin-org-metric]")?.value || "in_work";
    const orgSubtitle = root.querySelector("[data-org-chart]")?.closest(".admin-section")?.querySelector(".admin-section-head span");
    if (orgSubtitle) orgSubtitle.textContent = `Сравнение органов по показателю: ${metricLabel(metric).toLowerCase()}`;
    renderBarList("[data-department-load]", state.department_load, "Нет данных по отделам");
    renderAttention();
    setPresetActive(selectedPeriod);
    renderCalendar();
  }

  function setPeriod(code) {
    const today = new Date();
    selectedPeriod = code;
    if (code === "all") {
      selectedStart = null;
      selectedEnd = null;
    } else if (code === "today") {
      selectedStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
      selectedEnd = new Date(selectedStart);
    } else if (code === "current_week") {
      selectedStart = mondayOfWeek(today);
      selectedEnd = new Date(selectedStart);
      selectedEnd.setDate(selectedStart.getDate() + 6);
    } else if (code === "previous_week") {
      selectedEnd = mondayOfWeek(today);
      selectedEnd.setDate(selectedEnd.getDate() - 1);
      selectedStart = new Date(selectedEnd);
      selectedStart.setDate(selectedEnd.getDate() - 6);
    } else if (code === "last_14_days") {
      selectedEnd = new Date(today.getFullYear(), today.getMonth(), today.getDate());
      selectedStart = new Date(selectedEnd);
      selectedStart.setDate(selectedEnd.getDate() - 13);
    } else if (code === "previous_month") {
      const previous = addMonths(today, -1);
      selectedStart = firstDayOfMonth(previous);
      selectedEnd = lastDayOfMonth(previous);
    } else {
      selectedPeriod = "current_month";
      selectedStart = firstDayOfMonth(today);
      selectedEnd = lastDayOfMonth(today);
    }
    if (selectedStart) calendarCenter = firstDayOfMonth(selectedStart);
    pendingRangeStart = null;
    setPresetActive(selectedPeriod);
    updatePeriodLabel();
    renderCalendar();
    refreshSummary();
  }

  function selectCalendarDay(value) {
    const date = parseIsoDate(value);
    if (!date) return;
    if (!pendingRangeStart || selectedPeriod === "all") {
      pendingRangeStart = date;
      selectedStart = date;
      selectedEnd = date;
      selectedPeriod = "custom";
      setPresetActive("custom");
      updatePeriodLabel();
      renderCalendar();
      return;
    }
    selectedStart = pendingRangeStart <= date ? pendingRangeStart : date;
    selectedEnd = pendingRangeStart <= date ? date : pendingRangeStart;
    pendingRangeStart = null;
    selectedPeriod = "custom";
    setPresetActive("custom");
    updatePeriodLabel();
    renderCalendar();
    refreshSummary();
  }

  root.addEventListener("click", (event) => {
    const reportButton = event.target.closest("[data-admin-summary-report]");
    if (reportButton) {
      const reportForm = reportButton.closest("[data-admin-summary-report-form]");
      if (!reportForm) return;
      const params = paramsForRequest();
      params.delete("org_metric");
      const comparison = reportComparison?.value || "previous";
      params.set("comparison", comparison);
      if (comparison === "custom") {
        syncReportComparisonInputs(true);
        if (!reportComparisonFrom?.value || !reportComparisonTo?.value) {
          event.preventDefault();
          const visibleDateInput = reportCustomPicker?.querySelector("[data-date-range-text]");
          visibleDateInput?.classList.add("is-invalid");
          visibleDateInput?.focus();
          return;
        }
        params.set("comparison_date_from", reportComparisonFrom.value);
        params.set("comparison_date_to", reportComparisonTo.value);
      }
      const selectedMetrics = reportMetrics
        ? [...reportMetrics.querySelectorAll("[data-admin-multiselect-input]:checked")]
        : [];
      if (!selectedMetrics.length) {
        event.preventDefault();
        reportMetrics?.classList.add("has-error");
        reportMetrics?.querySelector(".admin-multiselect-trigger")?.focus();
        return;
      }
      params.delete("metrics");
      selectedMetrics.forEach((input) => params.append("metrics", input.value));
      params.set(
        "chart_layout",
        comparison === "none" ? "combined" : (reportChartLayout?.value || "combined"),
      );
      params.set("granularity", dynamicsGranularity);
      reportForm.querySelectorAll("[data-admin-report-param]").forEach((input) => input.remove());
      params.forEach((value, name) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = name;
        input.value = value;
        input.dataset.adminReportParam = "";
        reportForm.append(input);
      });
      return;
    }
    const preset = event.target.closest("[data-admin-period-preset]");
    if (preset) {
      event.preventDefault();
      setPeriod(preset.dataset.adminPeriodPreset);
      return;
    }
    if (event.target.closest("[data-admin-calendar-prev]")) {
      event.preventDefault();
      calendarCenter = addMonths(calendarCenter, -1);
      renderCalendar();
      return;
    }
    if (event.target.closest("[data-admin-calendar-next]")) {
      event.preventDefault();
      calendarCenter = addMonths(calendarCenter, 1);
      renderCalendar();
      return;
    }
    if (event.target.closest("[data-admin-calendar-jump-toggle]")) {
      event.preventDefault();
      setCalendarJumpOpen(Boolean(calendarJumpPanel?.hidden));
      return;
    }
    if (event.target.closest("[data-admin-calendar-year-prev]")) {
      event.preventDefault();
      calendarPickerYear -= 1;
      renderCalendarJump();
      return;
    }
    if (event.target.closest("[data-admin-calendar-year-next]")) {
      event.preventDefault();
      calendarPickerYear += 1;
      renderCalendarJump();
      return;
    }
    const calendarMonth = event.target.closest("[data-admin-calendar-month]");
    if (calendarMonth) {
      event.preventDefault();
      calendarCenter = new Date(calendarPickerYear, Number(calendarMonth.dataset.adminCalendarMonth), 1);
      setCalendarJumpOpen(false);
      renderCalendar();
      return;
    }
    if (event.target.closest("[data-admin-calendar-today]")) {
      event.preventDefault();
      const today = new Date();
      calendarCenter = new Date(today.getFullYear(), today.getMonth(), 1);
      setCalendarJumpOpen(false);
      renderCalendar();
      return;
    }
    const day = event.target.closest("[data-admin-calendar-day]");
    if (day) {
      event.preventDefault();
      selectCalendarDay(day.dataset.adminCalendarDay);
      return;
    }
    const organToggle = event.target.closest("[data-admin-organ-toggle]");
    if (organToggle) {
      event.preventDefault();
      const checkbox = organToggle.closest("[data-admin-organ-row]")?.querySelector("[data-admin-organ-checkbox]");
      if (checkbox) {
        checkbox.checked = !checkbox.checked;
        syncAdminOrgAllState();
        refreshSummary();
      }
      return;
    }
    if (event.target.closest("[data-admin-organ-select-all]")) {
      event.preventDefault();
      adminOrganCheckboxes().forEach((checkbox) => { if (!checkbox.closest("[data-admin-organ-row]")?.hidden) checkbox.checked = true; });
      syncAdminOrgAllState();
      refreshSummary();
      return;
    }
    if (event.target.closest("[data-admin-organ-clear-all]")) {
      event.preventDefault();
      adminOrganCheckboxes().forEach((checkbox) => { checkbox.checked = false; });
      syncAdminOrgAllState();
      refreshSummary();
      return;
    }
    const mode = event.target.closest("[data-dynamics-mode]");
    if (mode) {
      event.preventDefault();
      dynamicsMode = mode.dataset.dynamicsMode;
      syncDynamicsControls();
      renderDynamicsChart();
      return;
    }
    const granularity = event.target.closest("[data-dynamics-granularity]");
    if (granularity) {
      event.preventDefault();
      dynamicsGranularity = granularity.dataset.dynamicsGranularity;
      syncDynamicsControls();
      renderDynamicsChart();
    }
  });

  root.addEventListener("input", (event) => {
    if (!event.target.matches("[data-admin-organ-search]")) return;
    const query = event.target.value.trim().toLocaleLowerCase("ru-RU");
    root.querySelectorAll("[data-admin-organ-row]").forEach((row) => {
      if (!query) {
        row.hidden = false;
        row.style.order = "";
        return;
      }
      const organMatch = String(row.dataset.adminOrganSearch || "").toLocaleLowerCase("ru-RU").includes(query);
      const childMatch = String(row.dataset.adminChildSearch || "").toLocaleLowerCase("ru-RU").includes(query);
      row.hidden = !organMatch && !childMatch;
      row.style.order = organMatch ? "0" : "1";
    });
  });

  root.addEventListener("change", (event) => {
    if (event.target.closest(".admin-report-metrics")?.matches(".admin-report-metrics")) {
      reportMetrics?.classList.remove("has-error");
      return;
    }
    if (event.target.matches("#admin-report-comparison")) {
      syncReportComparisonInputs(true);
      return;
    }
    if (event.target.matches("[data-admin-all-organs]")) {
      adminOrganCheckboxes().forEach((checkbox) => { checkbox.checked = event.target.checked; });
      event.target.indeterminate = false;
      updateAdminOrgVisualState();
      saveAdminOrgSelection();
      refreshSummary();
      return;
    }
    if (event.target.matches("[data-admin-organ-checkbox]")) {
      syncAdminOrgAllState();
      refreshSummary();
      return;
    }
    if (event.target.matches("[data-admin-org-metric]")) {
      refreshSummary();
    }
  });

  document.addEventListener("click", (event) => {
    if (calendarJumpPanel?.hidden || event.target.closest(".admin-calendar-jump")) return;
    setCalendarJumpOpen(false);
  });

  restoreAdminOrgSelection();
  syncReportComparisonInputs(false);
  updatePeriodLabel();
  renderCalendar();
  // The server now renders the shell with an empty payload (see
  // build_summary_context) so first paint doesn't wait on the KPI/dynamics/
  // org-chart aggregates. Fetch the real data the same way any other
  // period/organ change does, instead of rendering from SSR state.
  refreshSummary();
})();
