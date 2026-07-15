// Admin panel custom dropdown multi-selects.
function adminMultiselectCheckedInputs(root) {
  return [...root.querySelectorAll("[data-admin-multiselect-input]")].filter((input) => input.checked);
}

function updateAdminMultiselectLabel(root) {
  if (!root) return;
  const label = root.querySelector("[data-admin-multiselect-label]");
  if (!label) return;
  const checked = adminMultiselectCheckedInputs(root);
  const allInputs = [...root.querySelectorAll("[data-admin-multiselect-input]")];
  const emptyLabel = root.dataset.emptyLabel || "Не выбрано";
  const allLabel = root.dataset.allLabel || "";
  if (!checked.length) {
    label.textContent = emptyLabel;
    root.classList.remove("has-selection");
    return;
  }
  root.classList.add("has-selection");
  if (allLabel && checked.length === allInputs.length) {
    label.textContent = allLabel;
    return;
  }
  if (checked.length === 1) {
    const option = checked[0].closest(".admin-multiselect-option");
    const optionLabel = option ? option.querySelector("span") : null;
    label.textContent = optionLabel ? optionLabel.textContent.trim() : checked[0].value;
    return;
  }
  label.textContent = `${checked.length} выбрано`;
}

function updateAllAdminMultiselectLabels() {
  document.querySelectorAll("[data-admin-multiselect]").forEach(updateAdminMultiselectLabel);
}

document.addEventListener("change", (event) => {
  const input = event.target.closest("[data-admin-multiselect-input]");
  if (!input) return;
  const root = input.closest("[data-admin-multiselect]");
  updateAdminMultiselectLabel(root);
  if (input.type === "radio" && root && root.classList.contains("admin-multiselect-single")) {
    const trigger = root.querySelector("[data-bs-toggle='dropdown']");
    if (trigger && window.bootstrap && bootstrap.Dropdown) {
      bootstrap.Dropdown.getOrCreateInstance(trigger).hide();
    }
  }
});

document.addEventListener("click", (event) => {
  const selectAll = event.target.closest("[data-admin-multiselect-select-all]");
  const clearAll = event.target.closest("[data-admin-multiselect-clear]");
  if (!selectAll && !clearAll) return;
  event.preventDefault();
  event.stopPropagation();
  const root = (selectAll || clearAll).closest("[data-admin-multiselect]");
  if (!root) return;
  root.querySelectorAll('[data-admin-multiselect-input][type="checkbox"]').forEach((input) => {
    input.checked = Boolean(selectAll);
  });
  updateAdminMultiselectLabel(root);
});

document.addEventListener("DOMContentLoaded", updateAllAdminMultiselectLabels);
