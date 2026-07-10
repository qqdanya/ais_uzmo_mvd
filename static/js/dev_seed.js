// Dev-only demo data generator: organ checkboxes, search filter and a
// polling progress bar while seed_demo_data runs in a background thread.
(function () {
  function organCheckboxes() {
    return Array.from(document.querySelectorAll('input[name="organ_ids"]'));
  }

  function updateOrganCount() {
    const counter = document.querySelector("[data-seed-organ-count]");
    if (!counter) return;
    const all = organCheckboxes();
    const checked = all.filter((box) => box.checked).length;
    counter.textContent = `Выбрано: ${checked} из ${all.length}`;
  }

  function initOrganList() {
    const selectAll = document.querySelector("[data-seed-select-all]");
    const clearAll = document.querySelector("[data-seed-clear-all]");
    const search = document.querySelector("[data-seed-organ-search]");

    selectAll?.addEventListener("click", () => {
      organCheckboxes().forEach((box) => {
        if (!box.closest("[data-seed-organ-row]").hidden) box.checked = true;
      });
      updateOrganCount();
    });
    clearAll?.addEventListener("click", () => {
      organCheckboxes().forEach((box) => {
        box.checked = false;
      });
      updateOrganCount();
    });
    search?.addEventListener("input", () => {
      const query = search.value.trim().toLowerCase();
      document.querySelectorAll("[data-seed-organ-row]").forEach((row) => {
        row.hidden = query.length > 0 && !row.dataset.seedOrganName.includes(query);
      });
    });
    document.querySelectorAll("[data-seed-organ-row] input").forEach((box) => {
      box.addEventListener("change", updateOrganCount);
    });
    updateOrganCount();
  }

  function cookieValue(name) {
    return document.cookie
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith(`${name}=`))
      ?.slice(name.length + 1) || "";
  }

  function setProgress(done, total) {
    const wrap = document.querySelector("[data-seed-progress-wrap]");
    const bar = document.querySelector("[data-seed-progress-bar]");
    const label = document.querySelector("[data-seed-progress-label]");
    if (!wrap || !bar) return;
    wrap.hidden = false;
    const percent = total > 0 ? Math.round((done / total) * 100) : 0;
    bar.style.width = `${percent}%`;
    bar.textContent = `${percent}%`;
    if (label) label.textContent = `Обработано территориальных органов: ${done} из ${total}`;
  }

  function showResult(text) {
    const wrap = document.querySelector("[data-seed-result-wrap]");
    const output = document.querySelector("[data-seed-output]");
    if (!wrap || !output) return;
    output.textContent = text || "";
    wrap.hidden = false;
  }

  function setSubmitting(isSubmitting) {
    const button = document.querySelector("[data-seed-submit]");
    const stopButton = document.querySelector("[data-seed-stop]");
    if (button) {
      button.disabled = isSubmitting;
      button.innerHTML = isSubmitting
        ? '<i class="bi bi-hourglass-split"></i> Генерация...'
        : '<i class="bi bi-play-fill"></i> Сгенерировать';
    }
    if (stopButton) {
      stopButton.hidden = !isSubmitting;
      stopButton.disabled = false;
      stopButton.innerHTML = '<i class="bi bi-stop-fill"></i> Стоп';
    }
  }

  function pollProgress(onDone) {
    const timer = setInterval(async () => {
      // Every request re-saves the session (SESSION_SAVE_EVERY_REQUEST), so
      // a poll can occasionally collide with the generator's own writes and
      // come back as a transient error instead of the expected JSON - skip
      // this tick and let the next one (1.5s later) pick progress back up.
      let state;
      try {
        const response = await fetch("/dev/seed/progress/");
        if (!response.ok) return;
        state = await response.json();
      } catch (error) {
        return;
      }
      setProgress(state.done, state.total || 1);
      if (state.finished) {
        clearInterval(timer);
        setSubmitting(false);
        if (state.error) {
          showResult(`Ошибка: ${state.error}`);
        } else {
          showResult(state.output);
        }
        onDone?.();
      }
    }, 1500);
  }

  function initForm() {
    const form = document.getElementById("seed-form");
    if (!form) return;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      setSubmitting(true);
      setProgress(0, 1);
      document.querySelector("[data-seed-result-wrap]").hidden = true;

      const response = await fetch("/dev/seed/start/", {
        method: "POST",
        body: new FormData(form),
        headers: { "X-CSRFToken": decodeURIComponent(cookieValue("csrftoken")) },
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        setSubmitting(false);
        showResult(`Ошибка: ${data.error || "Не удалось запустить генерацию."}`);
        return;
      }
      pollProgress();
    });

    const stopButton = document.querySelector("[data-seed-stop]");
    stopButton?.addEventListener("click", async () => {
      stopButton.disabled = true;
      stopButton.innerHTML = '<i class="bi bi-hourglass-split"></i> Останавливаем...';
      const response = await fetch("/dev/seed/stop/", {
        method: "POST",
        headers: { "X-CSRFToken": decodeURIComponent(cookieValue("csrftoken")) },
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        stopButton.disabled = false;
        stopButton.innerHTML = '<i class="bi bi-stop-fill"></i> Стоп';
        showResult(`Ошибка: ${data.error || "Не удалось остановить генерацию."}`);
      }
      // On success the button stays disabled with "Останавливаем..." until
      // the next poll tick sees finished:true and setSubmitting(false)
      // resets it - the stop only takes effect once the seed command
      // reaches its next territorial-organ boundary.
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initOrganList();
    initForm();
  });
})();
