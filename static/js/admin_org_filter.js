// Admin organ filter dropdown: checkbox state, summary label and empty-selection marker.
function updateAdminFilterOrgBox(box) {
  if (!box) return;
  const items = Array.from(box.querySelectorAll(".admin-org-filter-item"));
  const checkboxes = items.map((item) => item.querySelector('input[type="checkbox"][name="organ_ids"]')).filter(Boolean);
  const checked = checkboxes.filter((checkbox) => checkbox.checked);
  items.forEach((item) => {
    const checkbox = item.querySelector('input[type="checkbox"][name="organ_ids"]');
    item.classList.toggle("is-selected", Boolean(checkbox?.checked));
  });
  const meta = box.querySelector(".admin-org-filter-toggle-meta strong");
  if (meta) {
    if (!checkboxes.length || checked.length === checkboxes.length) {
      meta.textContent = "выбраны все";
    } else if (checked.length === 1) {
      meta.textContent = "выбран 1";
    } else if (checked.length === 0) {
      meta.textContent = "ничего не выбрано";
    } else {
      meta.textContent = `выбрано ${checked.length}`;
    }
  }

  const form = box.closest("form");
  let emptyMarker = form?.querySelector('input[name="organ_filter_empty"][data-admin-organ-empty-marker]');
  if (form && checkboxes.length && checked.length === 0) {
    if (!emptyMarker) {
      emptyMarker = document.createElement("input");
      emptyMarker.type = "hidden";
      emptyMarker.name = "organ_filter_empty";
      emptyMarker.dataset.adminOrganEmptyMarker = "true";
      form.append(emptyMarker);
    }
    emptyMarker.value = "1";
  } else {
    emptyMarker?.remove();
  }
}

function initAdminFilterOrgBoxes() {
  document.querySelectorAll(".admin-org-filter-box").forEach(updateAdminFilterOrgBox);
}

document.addEventListener("change", (event) => {
  const checkbox = event.target.closest('input[type="checkbox"][name="organ_ids"]');
  if (!checkbox) return;
  updateAdminFilterOrgBox(checkbox.closest(".admin-org-filter-box"));
});

document.addEventListener("DOMContentLoaded", initAdminFilterOrgBoxes);

document.addEventListener("click", (event) => {
  const selectAll = event.target.closest("[data-admin-filter-organ-select-all]");
  if (selectAll) {
    event.preventDefault();
    const box = selectAll.closest(".admin-org-filter-box");
    box?.querySelectorAll('input[type="checkbox"][name="organ_ids"]').forEach((checkbox) => {
      checkbox.checked = true;
    });
    updateAdminFilterOrgBox(box);
    return;
  }

  const clearAll = event.target.closest("[data-admin-filter-organ-clear-all]");
  if (!clearAll) return;
  event.preventDefault();
  const box = clearAll.closest(".admin-org-filter-box");
  box?.querySelectorAll('input[type="checkbox"][name="organ_ids"]').forEach((checkbox) => {
    checkbox.checked = false;
  });
  updateAdminFilterOrgBox(box);
}, true);

window.updateAdminFilterOrgBox = updateAdminFilterOrgBox;
window.initAdminFilterOrgBoxes = initAdminFilterOrgBoxes;
