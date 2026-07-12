(() => {
  const formSelector = ".audit-filters";
  const multiselectSelector = "[data-admin-multiselect]";

  const refresh = (form) => {
    if (!form || form.dataset.auditFilterPending === "true") return;
    form.dataset.auditFilterPending = "true";
    window.setTimeout(() => {
      delete form.dataset.auditFilterPending;
      if (window.htmx) {
        window.htmx.trigger(form, "audit-filter-change");
      } else {
        form.requestSubmit();
      }
    }, 60);
  };

  const markMultiselect = (element) => {
    const root = element.closest(multiselectSelector);
    if (root) root.dataset.auditFilterDirty = "true";
  };

  document.addEventListener("change", (event) => {
    const form = event.target.closest(formSelector);
    if (!form) return;
    if (event.target.matches("[data-admin-multiselect-input]")) {
      markMultiselect(event.target);
      return;
    }
    if (event.target.matches("[data-date-range-from], [data-date-range-to]")) refresh(form);
  });

  document.addEventListener("click", (event) => {
    const action = event.target.closest("[data-admin-multiselect-select-all], [data-admin-multiselect-clear]");
    if (action?.closest(formSelector)) markMultiselect(action);
  });

  document.addEventListener("hidden.bs.dropdown", (event) => {
    const root = event.target.closest?.(multiselectSelector);
    if (!root || root.dataset.auditFilterDirty !== "true") return;
    delete root.dataset.auditFilterDirty;
    refresh(root.closest(formSelector));
  });

  document.addEventListener("submit", (event) => {
    const form = event.target.closest(formSelector);
    if (!form) return;
    event.preventDefault();
    refresh(form);
  });
})();
