// Small DOM/input helpers shared by frontend modules.
function normalizeAuthInput(input) {
  const value = input.value.replace(/[^\x21-\x7E]/g, "");
  if (input.value !== value) input.value = value;
}

function normalizeSearchText(value) {
  return String(value || "").trim().toLocaleLowerCase("ru-RU");
}

function isEditableTarget(target) {
  return Boolean(target?.closest?.("input, textarea, select, [contenteditable='true'], [data-custom-select]"));
}

function isVisibleElement(element) {
  return Boolean(element && !element.disabled && element.getClientRects().length);
}
