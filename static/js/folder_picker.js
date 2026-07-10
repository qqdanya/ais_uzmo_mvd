// Folder destination picker: single-select mini-explorer for choosing where
// a photo or folder should live, replacing a long flat <select> dropdown.
function toggleFolderPicker(button) {
  const box = button.closest("[data-folder-picker-box]");
  const panel = box?.querySelector("[data-folder-picker-panel]");
  if (!box || !panel) return;
  panel.hidden = !panel.hidden;
}

function selectFolderPickerDestination(button) {
  const box = button.closest("[data-folder-picker-box]");
  if (!box) return;
  const hidden = box.querySelector("[data-folder-picker-hidden]");
  const label = box.querySelector("[data-folder-picker-current-label]");
  if (hidden) hidden.value = button.dataset.folderId || "";
  if (label) label.textContent = button.dataset.folderLabel || "Корень";
  const panel = box.querySelector("[data-folder-picker-panel]");
  if (panel) panel.hidden = true;
}
