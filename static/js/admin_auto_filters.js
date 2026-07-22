(() => {
  const formSelector = "form[data-admin-auto-filter]";
  const searchDelay = 1500;
  const timerByForm = new WeakMap();

  const submit = (form, delay = 0) => {
    if (!form) return;
    window.clearTimeout(timerByForm.get(form));
    timerByForm.set(form, window.setTimeout(() => form.requestSubmit(), delay));
  };

  const markDeferred = (element) => {
    const root = element.closest("[data-admin-multiselect], .admin-org-filter-box");
    if (root) root.dataset.adminFilterDirty = "true";
  };

  const deleteParameter = (parameters, name) => {
    if (typeof parameters?.delete === "function") parameters.delete(name);
    else if (parameters) delete parameters[name];
  };

  const setParameter = (parameters, name, value) => {
    if (typeof parameters?.set === "function") parameters.set(name, value);
    else if (parameters) parameters[name] = value;
  };

  document.addEventListener("htmx:configRequest", (event) => {
    const form = event.detail?.elt?.closest?.(formSelector) || event.target.closest?.(formSelector);
    if (!form) return;
    const organInputs = [...form.querySelectorAll('input[name="organ_ids"]')];
    if (!organInputs.length) return;
    const selectedIds = organInputs
      .filter((input) => input.checked && /^\d+$/.test(input.value))
      .map((input) => input.value);
    const parameters = event.detail.parameters;
    deleteParameter(parameters, "organ_ids");
    deleteParameter(parameters, "organs");
    if (selectedIds.length && selectedIds.length !== organInputs.length) {
      setParameter(parameters, "organs", [...new Set(selectedIds)].join("-"));
    }
  });

  document.addEventListener("input", (event) => {
    const form = event.target.closest(formSelector);
    if (form && event.target.matches('input[type="search"], input[name="q"]')) submit(form, searchDelay);
  });

  document.addEventListener("submit", (event) => {
    const form = event.target.closest(formSelector);
    if (!form) return;
    window.clearTimeout(timerByForm.get(form));
    timerByForm.delete(form);
  });

  document.addEventListener("change", (event) => {
    const form = event.target.closest(formSelector);
    if (!form) return;
    if (event.target.matches("[data-admin-multiselect-input], .admin-org-filter-box input[type='checkbox']")) {
      markDeferred(event.target);
      return;
    }
    submit(form, 60);
  });

  document.addEventListener("click", (event) => {
    const bulkAction = event.target.closest("[data-admin-multiselect-select-all], [data-admin-multiselect-clear], [data-admin-filter-organ-select-all], [data-admin-filter-organ-clear-all]");
    if (bulkAction?.closest(formSelector)) markDeferred(bulkAction);
  });

  const submitDirty = (root) => {
    if (!root || root.dataset.adminFilterDirty !== "true") return;
    delete root.dataset.adminFilterDirty;
    submit(root.closest(formSelector), 60);
  };

  document.addEventListener("hidden.bs.dropdown", (event) => {
    submitDirty(event.target.closest?.("[data-admin-multiselect]"));
  });

  document.addEventListener("hidden.bs.collapse", (event) => {
    submitDirty(event.target.closest?.(".admin-org-filter-box"));
  });
})();
