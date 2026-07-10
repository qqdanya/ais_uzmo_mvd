// Folder destination picker: single-select mini-explorer for choosing where
// a photo or folder should live, replacing a long flat <select> dropdown.
// There is no explicit "select" step: whatever folder is currently being
// browsed is the destination, kept in sync via syncFolderPickerBox below.
function toggleFolderPicker(button) {
  const box = button.closest("[data-folder-picker-box]");
  const panel = box?.querySelector("[data-folder-picker-panel]");
  if (!box || !panel) return;
  panel.hidden = !panel.hidden;
}

function syncFolderPickerBox(box) {
  const current = box.querySelector("[data-folder-picker-current-id]");
  if (!current) return;
  const hidden = box.querySelector("[data-folder-picker-hidden]");
  const label = box.querySelector("[data-folder-picker-current-label]");
  if (hidden) hidden.value = current.dataset.folderPickerCurrentId || "";
  if (label) label.textContent = current.dataset.folderPickerCurrentLabel || "Корень";
}
