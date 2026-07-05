// Shared app storage keys and helpers. Loaded before feature modules.
window.selectedOrgan = window.selectedOrgan || null;
const ORGAN_STORAGE_KEY = "asu-zmo:selected-organ";
const ORGAN_MODE_KEY = "asu-zmo:organ-mode";
const MULTI_ORGANS_KEY = "asu-zmo:multi-organs";
const DEPARTMENT_STORAGE_PREFIX = "asu-zmo:last-department:";
const DEPARTMENT_TABLE_PREFIX = "asu-zmo:last-table:";
const TABLE_STATE_PREFIX = "asu-zmo:table-state:";
const COLLAPSED_PANELS_KEY = "asu-zmo:collapsed-panels";

function storedValue(key) {
  try {
    return localStorage.getItem(key) ?? sessionStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function storeValue(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    try {
      sessionStorage.setItem(key, value);
    } catch (fallbackError) {
      // Browser storage can be unavailable in strict privacy modes.
    }
  }
}

function removeStoredValue(key) {
  try {
    localStorage.removeItem(key);
    sessionStorage.removeItem(key);
  } catch (error) {
    // Nothing to clean up when storage is unavailable.
  }
}

function formatLocalDateTime(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function departmentStorageKey(organId) {
  return `${DEPARTMENT_STORAGE_PREFIX}${organId}`;
}

function departmentTableStorageKey(departmentSlug) {
  return `${DEPARTMENT_TABLE_PREFIX}${departmentSlug}`;
}

function tableStateStorageKey(departmentSlug, tableKey) {
  return `${TABLE_STATE_PREFIX}${departmentSlug}:${tableKey}`;
}
