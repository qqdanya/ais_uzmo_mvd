(() => {
  const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
  const DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

  function parseIso(value) {
    if (!value) return null;
    const [year, month, day] = value.split("-").map(Number);
    return year && month && day ? new Date(year, month - 1, day) : null;
  }

  function parseDisplayDate(value) {
    const match = String(value || "").trim().match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
    if (!match) return parseIso(value);
    const date = new Date(Number(match[3]), Number(match[2]) - 1, Number(match[1]));
    return date.getFullYear() === Number(match[3]) && date.getMonth() === Number(match[2]) - 1 && date.getDate() === Number(match[1]) ? date : null;
  }

  function iso(date) {
    if (!date) return "";
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }

  function display(date) {
    if (!date) return "";
    return `${String(date.getDate()).padStart(2, "0")}.${String(date.getMonth() + 1).padStart(2, "0")}.${date.getFullYear()}`;
  }

  function monthStart(date) { return new Date(date.getFullYear(), date.getMonth(), 1); }
  function monthEnd(date) { return new Date(date.getFullYear(), date.getMonth() + 1, 0); }
  function addMonths(date, amount) { return new Date(date.getFullYear(), date.getMonth() + amount, 1); }
  function sameDay(a, b) { return a && b && iso(a) === iso(b); }

  // Reformats raw keystrokes into the DD.MM.YYYY mask (or two of those
  // joined by " – " for a range) as the user types, so they only ever type
  // digits - the dots (and, for a range, the dash) appear on their own.
  function formatDateDigits(digits) {
    let out = digits.slice(0, 2);
    if (digits.length > 2) out += "." + digits.slice(2, 4);
    if (digits.length > 4) out += "." + digits.slice(4, 8);
    return out;
  }

  function applyDateMask(value, single) {
    const digits = String(value || "").replace(/\D/g, "").slice(0, single ? 8 : 16);
    if (single) return formatDateDigits(digits);
    const second = digits.slice(8);
    return second ? `${formatDateDigits(digits.slice(0, 8))} – ${formatDateDigits(second)}` : formatDateDigits(digits);
  }

  // Mirrors native date inputs: clicking anywhere in a date selects the whole
  // day, month or year segment, ready to be replaced with the next keystroke.
  function dateSegments(value) {
    const segments = [];
    const matcher = /\d{1,2}\.\d{1,2}\.\d{4}/g;
    let match;
    while ((match = matcher.exec(value)) !== null) {
      const offset = match.index;
      segments.push([offset, offset + 2], [offset + 3, offset + 5], [offset + 6, offset + 10]);
    }
    return segments;
  }

  function selectDateSegment(input, position = input.selectionStart || 0, direction = 0) {
    const segments = dateSegments(input.value);
    if (!segments.length) return;
    let index = segments.findIndex(([start, end]) => position >= start && position <= end);
    if (index < 0) index = segments.findIndex(([start]) => position < start);
    if (index < 0) index = segments.length - 1;
    index = Math.max(0, Math.min(segments.length - 1, index + direction));
    input.setSelectionRange(segments[index][0], segments[index][1]);
  }

  function initPicker(root) {
    if (root.dataset.dateRangeReady === "true") return;
    root.dataset.dateRangeReady = "true";
    const fromInput = root.querySelector("[data-date-range-from]");
    const toInput = root.querySelector("[data-date-range-to]");
    const textInput = root.querySelector("[data-date-range-text]");
    const toggle = root.querySelector("[data-date-range-toggle]");
    const popover = root.querySelector("[data-date-range-popover]");
    const caption = root.querySelector("[data-date-range-caption]");
    const captionButton = root.querySelector("[data-date-range-caption-button]");
    const calendar = root.querySelector("[data-date-range-calendar]");
    const jump = root.querySelector("[data-date-range-jump]");
    const yearLabel = root.querySelector("[data-date-range-year]");
    const monthPicker = root.querySelector("[data-date-range-months]");
    const single = root.dataset.dateRangeMode === "single";
    if (!fromInput || (!single && !toInput) || !textInput || !toggle || !popover || !calendar) return;

    let start = parseIso(fromInput.value);
    let end = single ? start : parseIso(toInput.value);
    let pending = null;
    let center = monthStart(start || new Date());
    let pickerYear = center.getFullYear();
    let segmentEdit = null;

    function syncLabel() {
      textInput.value = single ? display(start) : (start && end ? `${display(start)} – ${display(end)}` : "");
      textInput.classList.remove("is-invalid");
    }

    function renderJump() {
      if (!monthPicker) return;
      yearLabel.textContent = String(pickerYear);
      monthPicker.replaceChildren();
      MONTHS.forEach((name, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = name.slice(0, 3);
        button.dataset.dateRangeMonth = String(index);
        button.classList.toggle("active", pickerYear === center.getFullYear() && index === center.getMonth());
        monthPicker.append(button);
      });
    }

    function render() {
      caption.textContent = `${MONTHS[center.getMonth()]} ${center.getFullYear()}`;
      calendar.replaceChildren();
      const weekdays = document.createElement("div");
      weekdays.className = "compact-date-weekdays";
      DAYS.forEach((name) => { const item = document.createElement("span"); item.textContent = name; weekdays.append(item); });
      const days = document.createElement("div");
      days.className = "compact-date-days";
      const firstWeekday = center.getDay() || 7;
      for (let index = 1; index < firstWeekday; index += 1) days.append(document.createElement("span"));
      const last = monthEnd(center).getDate();
      for (let day = 1; day <= last; day += 1) {
        const date = new Date(center.getFullYear(), center.getMonth(), day);
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = String(day);
        button.dataset.dateRangeDay = iso(date);
        if (sameDay(date, new Date())) button.classList.add("is-today");
        if (start && end && date >= start && date <= end) button.classList.add("is-in-range");
        if (sameDay(date, start)) button.classList.add("is-range-start");
        if (sameDay(date, end)) button.classList.add("is-range-end");
        if (sameDay(date, pending)) button.classList.add("is-pending");
        days.append(button);
      }
      calendar.append(weekdays, days);
      syncLabel();
    }

    function open(value) {
      popover.hidden = !value;
      toggle.setAttribute("aria-expanded", String(value));
      if (value) render();
      else {
        jump.hidden = true;
        captionButton?.setAttribute("aria-expanded", "false");
        pending = null;
      }
    }
    root.closeDateRangePicker = () => open(false);

    function commit(newStart, newEnd) {
      start = newStart;
      end = newEnd;
      pending = null;
      fromInput.value = iso(start);
      if (toInput) toInput.value = iso(end);
      syncLabel();
      open(false);
      (toInput || fromInput).dispatchEvent(new Event("change", { bubbles: true }));
    }

    root.setDateRangePickerValues = (fromValue, toValue = fromValue) => {
      start = parseIso(fromValue);
      end = single ? start : parseIso(toValue);
      pending = null;
      fromInput.value = iso(start);
      if (toInput) toInput.value = iso(end);
      center = monthStart(start || new Date());
      syncLabel();
      if (!popover.hidden) render();
    };

    function commitManualValue() {
      const value = textInput.value.trim();
      if (!value) { commit(null, null); return true; }
      if (single) {
        const date = parseDisplayDate(value);
        if (date) { commit(date, date); return true; }
      } else {
        const match = value.match(/^(\d{1,2}\.\d{1,2}\.\d{4})\s*[—–-]\s*(\d{1,2}\.\d{1,2}\.\d{4})$/);
        const manualStart = parseDisplayDate(match?.[1]);
        const manualEnd = parseDisplayDate(match?.[2]);
        if (match && manualStart && manualEnd) {
          commit(manualStart <= manualEnd ? manualStart : manualEnd, manualStart <= manualEnd ? manualEnd : manualStart);
          return true;
        }
      }
      textInput.classList.add("is-invalid");
      return false;
    }

    root.addEventListener("click", (event) => {
      if (event.target.closest("[data-date-range-toggle]")) { open(popover.hidden); return; }
      if (event.target.closest("[data-date-range-prev]")) { center = addMonths(center, -1); render(); return; }
      if (event.target.closest("[data-date-range-next]")) { center = addMonths(center, 1); render(); return; }
      if (event.target.closest("[data-date-range-caption-button]")) {
        jump.hidden = !jump.hidden;
        captionButton?.setAttribute("aria-expanded", String(!jump.hidden));
        pickerYear = center.getFullYear();
        renderJump();
        return;
      }
      if (event.target.closest("[data-date-range-year-prev]")) { pickerYear -= 1; renderJump(); return; }
      if (event.target.closest("[data-date-range-year-next]")) { pickerYear += 1; renderJump(); return; }
      const month = event.target.closest("[data-date-range-month]");
      if (month) {
        center = new Date(pickerYear, Number(month.dataset.dateRangeMonth), 1);
        jump.hidden = true;
        captionButton?.setAttribute("aria-expanded", "false");
        render();
        return;
      }
      const dayButton = event.target.closest("[data-date-range-day]");
      if (dayButton) {
        const date = parseIso(dayButton.dataset.dateRangeDay);
        if (single) { commit(date, date); return; }
        if (!pending) { pending = date; start = date; end = date; render(); }
        else commit(pending <= date ? pending : date, pending <= date ? date : pending);
        return;
      }
      const preset = event.target.closest("[data-date-range-preset]")?.dataset.dateRangePreset;
      if (!preset) return;
      const today = new Date();
      if (preset === "clear") { commit(null, null); return; }
      if (preset === "today") { commit(today, today); return; }
      if (preset === "week") {
        const monday = new Date(today); monday.setDate(today.getDate() - ((today.getDay() || 7) - 1));
        const sunday = new Date(monday); sunday.setDate(monday.getDate() + 6);
        commit(monday, sunday); return;
      }
      commit(monthStart(today), monthEnd(today));
    });

    textInput.addEventListener("input", () => {
      textInput.value = applyDateMask(textInput.value, single);
    });

    textInput.addEventListener("beforeinput", (event) => {
      if (event.inputType !== "insertText" || !/^\d+$/.test(event.data || "")) return;
      const segments = dateSegments(textInput.value);
      const index = segments.findIndex(([start, end]) => textInput.selectionStart === start && textInput.selectionEnd === end);
      if (index < 0) return;
      event.preventDefault();
      const [startAt, endAt] = segments[index];
      const length = endAt - startAt;
      const previous = segmentEdit?.index === index ? segmentEdit.digits : "";
      const digits = (previous + event.data).slice(-length);
      const replacement = digits.padStart(length, "0");
      textInput.value = textInput.value.slice(0, startAt) + replacement + textInput.value.slice(endAt);
      textInput.classList.remove("is-invalid");
      segmentEdit = digits.length < length ? { index, digits } : null;
      if (segmentEdit) textInput.setSelectionRange(startAt, endAt);
      else selectDateSegment(textInput, startAt, 1);
    });

    textInput.addEventListener("click", () => {
      segmentEdit = null;
      selectDateSegment(textInput);
    });

    textInput.addEventListener("focus", () => {
      if (textInput.selectionStart === textInput.selectionEnd) selectDateSegment(textInput);
    });

    textInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        commitManualValue();
      } else if (event.key === "Escape") {
        open(false);
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        const segments = dateSegments(textInput.value);
        const selectedSegment = segments.some(([start, end]) => textInput.selectionStart === start && textInput.selectionEnd === end);
        if (selectedSegment) {
          event.preventDefault();
          segmentEdit = null;
          selectDateSegment(textInput, textInput.selectionStart, event.key === "ArrowLeft" ? -1 : 1);
        }
      }
    });
    textInput.addEventListener("change", commitManualValue);

    syncLabel();
  }

  function initAll(scope = document) {
    scope.querySelectorAll?.("input[data-app-date-input]").forEach(initSingleDateInput);
    scope.querySelectorAll?.("[data-date-range-picker]").forEach(initPicker);
  }

  function initSingleDateInput(input) {
    if (input.dataset.appDateReady === "true") return;
    input.dataset.appDateReady = "true";
    input.type = "hidden";
    input.dataset.dateRangeFrom = "";
    const root = document.createElement("div");
    root.className = "compact-date-range custom-date-single";
    root.dataset.dateRangePicker = "";
    root.dataset.dateRangeMode = "single";
    input.before(root);
    root.append(input);
    root.insertAdjacentHTML("beforeend", `
      <div class="custom-date-control">
        <input class="custom-date-text" type="text" data-date-range-text placeholder="ДД.ММ.ГГГГ" inputmode="numeric" autocomplete="off">
        <button class="custom-date-arrow" type="button" data-date-range-toggle aria-expanded="false" aria-label="Открыть календарь"><i class="bi bi-chevron-down"></i></button>
      </div>
      <div class="compact-date-popover" data-date-range-popover hidden>
        <div class="compact-date-toolbar">
          <button type="button" data-date-range-prev aria-label="Предыдущий месяц"><i class="bi bi-chevron-left"></i></button>
          <button type="button" data-date-range-caption-button><strong data-date-range-caption></strong><i class="bi bi-chevron-down"></i></button>
          <button type="button" data-date-range-next aria-label="Следующий месяц"><i class="bi bi-chevron-right"></i></button>
        </div>
        <div class="compact-date-jump" data-date-range-jump hidden>
          <div class="compact-date-year-row">
            <button type="button" data-date-range-year-prev aria-label="Предыдущий год"><i class="bi bi-chevron-left"></i></button>
            <strong data-date-range-year></strong>
            <button type="button" data-date-range-year-next aria-label="Следующий год"><i class="bi bi-chevron-right"></i></button>
          </div>
          <div class="compact-date-months" data-date-range-months></div>
        </div>
        <div data-date-range-calendar></div>
        <div class="compact-date-presets compact-date-presets-single">
          <button type="button" data-date-range-preset="today">Сегодня</button>
          <button type="button" data-date-range-preset="clear">Очистить</button>
        </div>
      </div>`);
    const label = input.closest(".form-field")?.querySelector(".form-label")?.textContent?.trim();
    const visibleInput = root.querySelector("[data-date-range-text]");
    if (label) visibleInput.setAttribute("aria-label", label);
  }

  document.addEventListener("DOMContentLoaded", () => initAll());
  document.addEventListener("click", (event) => {
    document.querySelectorAll("[data-date-range-picker]").forEach((root) => {
      const popover = root.querySelector("[data-date-range-popover]");
      if (!popover?.hidden && !event.composedPath().includes(root)) root.closeDateRangePicker?.();
    });
  });
  document.body?.addEventListener("htmx:afterSwap", (event) => initAll(event.detail.target));
  window.initDateRangePickers = initAll;
})();
