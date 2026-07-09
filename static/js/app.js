// Application bootstrap. Feature logic lives in focused frontend modules.
function initApp() {
  syncHeaderHeight();
  resetHtmxLoading();
  initCustomSelects();
  initTooltips();
  document.querySelectorAll(".auth-ascii-input").forEach(normalizeAuthInput);
  autoDismissAlerts();
  applyCollapsedPanels();

  applyDashboardUrlState();
  const restoredOrganCount = restoreCheckedOrgans();
  const savedOrganId = storedValue(ORGAN_STORAGE_KEY);
  // Fall back to the first organ when the remembered/linked one is not in
  // this user's list (revoked access, deactivated organ, foreign deep link).
  const organ = findOrganById(savedOrganId) || document.querySelector(".organ-item[data-organ-id]");
  // The dashboard view always server-renders the same default (first organ,
  // first department, first table) — see dashboard_context(). That's
  // guaranteed to already match only when there's no saved/linked organ at
  // all, so skip the otherwise-unconditional re-fetch of #organ-info and
  // #workspace that fired on every single page load for no reason.
  const isFreshVisit = !savedOrganId && !isMultiOrganMode();

  if (organ) {
    setActiveOrgan(organ);
    if (isMultiOrganMode()) {
      clearSingleOrganHighlight();
      renderMultiOrganInfo();
    } else if (!isFreshVisit) {
      loadOrganInfo(window.selectedOrgan);
    }
    syncOrganModeButtons();
    const department = !isMultiOrganMode() || restoredOrganCount ? preferredDepartmentForOrgan(window.selectedOrgan) : null;
    if (department) {
      setActiveDepartment(department);
      if (!isFreshVisit) loadDepartment(department);
      else syncDashboardUrl();
    } else if (isMultiOrganMode()) {
      clearActiveDepartment();
      renderMultiOrganWorkspaceEmpty();
    }
  }
}

registerModalLifecycle();
registerHtmxLifecycle();
registerAppEventHandlers();

document.addEventListener("DOMContentLoaded", initApp);
window.addEventListener("resize", syncHeaderHeight);
