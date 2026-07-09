// Application bootstrap. Feature logic lives in focused frontend modules.
function initApp() {
  syncHeaderHeight();
  resetHtmxLoading();
  initCustomSelects();
  initTooltips();
  document.querySelectorAll(".auth-ascii-input").forEach(normalizeAuthInput);
  autoDismissAlerts();
  applyCollapsedPanels();
  if (typeof registerAppEventHandlers === "function") registerAppEventHandlers();

  // organ_navigation.js (and the dashboard bootstrap below) only loads on the
  // dashboard page — everything past this point would throw a ReferenceError
  // anywhere else.
  if (typeof applyDashboardUrlState !== "function") return;

  applyDashboardUrlState();
  const restoredOrganCount = restoreCheckedOrgans();
  const savedOrganId = storedValue(ORGAN_STORAGE_KEY);
  // Fall back to the first organ when the remembered/linked one is not in
  // this user's list (revoked access, deactivated organ, foreign deep link).
  const organ = findOrganById(savedOrganId) || document.querySelector(".organ-item[data-organ-id]");
  // Multi-organ mode is never server-rendered, so it never matches the SSR
  // default and always needs the real fetch.
  const serverDefault = !isMultiOrganMode() ? serverRenderedWorkspaceState() : null;

  if (organ) {
    setActiveOrgan(organ);
    if (isMultiOrganMode()) {
      clearSingleOrganHighlight();
      renderMultiOrganInfo();
    } else if (!serverDefault || serverDefault.organId !== String(window.selectedOrgan)) {
      loadOrganInfo(window.selectedOrgan);
    }
    syncOrganModeButtons();
    const department = !isMultiOrganMode() || restoredOrganCount ? preferredDepartmentForOrgan(window.selectedOrgan) : null;
    if (department) {
      setActiveDepartment(department);
      const tableKey = savedTableKeyForDepartment(department.dataset.departmentSlug);
      // Compare against what the server actually rendered (organ, department
      // *and* table), not just "is anything saved" — a returning visitor
      // whose saved state happens to match the default also skips this,
      // not just a visitor with nothing saved at all. A saved search/filter/
      // page for that table still means the SSR default (which never
      // applies it) isn't actually what should be shown, so that still
      // forces the real fetch even when organ/department/table all match.
      const matchesServerDefault = serverDefault
        && serverDefault.organId === String(window.selectedOrgan)
        && serverDefault.departmentSlug === department.dataset.departmentSlug
        && serverDefault.tableKey === tableKey
        && !savedTableQuery(department.dataset.departmentSlug, tableKey);
      if (!matchesServerDefault) loadDepartment(department);
      else syncDashboardUrl();
    } else if (isMultiOrganMode()) {
      clearActiveDepartment();
      renderMultiOrganWorkspaceEmpty();
    }
  }
}

registerModalLifecycle();
registerHtmxLifecycle();

document.addEventListener("DOMContentLoaded", initApp);
window.addEventListener("resize", syncHeaderHeight);
