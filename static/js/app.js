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

  if (organ) {
    setActiveOrgan(organ);
    if (isMultiOrganMode()) {
      clearSingleOrganHighlight();
      renderMultiOrganInfo();
    } else {
      loadOrganInfo(window.selectedOrgan);
    }
    syncOrganModeButtons();
    const department = !isMultiOrganMode() || restoredOrganCount ? preferredDepartmentForOrgan(window.selectedOrgan) : null;
    if (department) {
      setActiveDepartment(department);
      loadDepartment(department);
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
