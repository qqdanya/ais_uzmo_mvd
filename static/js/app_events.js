// Delegated user interaction handlers for the main application shell.
function registerAppEventHandlers() {
  document.addEventListener("submit", (event) => {
    const bulkForm = event.target.closest("[data-bulk-photo-form]");
    if (!bulkForm) return;
    event.preventDefault();
    event.stopPropagation();
    PhotoUpload.uploadBulkPhotos(bulkForm);
  }, true);
  
  document.addEventListener("input", (event) => {
    if (event.target.matches(".auth-ascii-input")) {
      normalizeAuthInput(event.target);
      return;
    }
    if (event.target.matches("[data-tmc-product-input]")) {
      requestTmcProductSuggestions(event.target);
      return;
    }
    if (event.target.matches("[data-table-search]")) {
      filterCurrentTable(event.target);
      return;
    }
    if (event.target.id !== "organ-search") return;
    const query = normalizeSearchText(event.target.value);
    document.querySelectorAll("[data-organ-row]").forEach((item) => {
      if (!query) {
        item.hidden = false;
        item.style.order = "";
        return;
      }
      const organMatch = normalizeSearchText(item.dataset.organSearch).includes(query);
      const childMatch = normalizeSearchText(item.dataset.childSearch).includes(query);
      item.hidden = !organMatch && !childMatch;
      item.style.order = organMatch ? "0" : "1";
    });
  });
  
  document.addEventListener("mouseover", (event) => {
    const row = event.target.closest(".data-row[data-row-group]");
    if (row) setTableGroupHover(row);
  });
  
  document.addEventListener("mouseout", (event) => {
    const tableWrap = event.target.closest(".table-wrap");
    if (tableWrap && !tableWrap.contains(event.relatedTarget)) {
      clearTableGroupHover(tableWrap);
    }
  });
  
  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-request-photo-checkbox]")) {
      setRequestPhotoSelected(event.target);
      return;
    }
  
    const status = event.target.closest('[data-tmc-request-form] [name="status"], [data-status-form] [name="status"]');
    if (status) {
      fillCompletedDate(status.closest("[data-tmc-request-form], [data-status-form]"));
      return;
    }
    if (event.target.matches("[data-single-file-picker] input[type='file']")) {
      PhotoUpload.updateSingleFilePicker(event.target);
      return;
    }
    if (!event.target.matches("[data-bulk-photo-input]")) return;
    const form = event.target.closest("[data-bulk-photo-form]");
    if (form) PhotoUpload.renderBulkPhotoFiles(form, event.target.files);
  });
  
  document.addEventListener("dragover", (event) => {
    const dropzone = PhotoUpload.photoDropTarget(event);
    if (!dropzone) return;
    event.preventDefault();
    PhotoUpload.clearPhotoDragState();
    dropzone.classList.add("is-dragover");
  });
  
  document.addEventListener("dragleave", (event) => {
    const dropzone = PhotoUpload.photoDropTarget(event);
    if (!dropzone || dropzone.contains(event.relatedTarget)) return;
    dropzone.classList.remove("is-dragover");
  });
  
  document.addEventListener("drop", (event) => {
    const dropzone = PhotoUpload.photoDropTarget(event);
    if (!dropzone) return;
    event.preventDefault();
    PhotoUpload.clearPhotoDragState();
    PhotoUpload.openBulkPhotoModal(dropzone, event.dataTransfer.files);
  });
  
  document.addEventListener("beforeinput", (event) => {
    if (!event.target.matches(".auth-ascii-input") || !event.data) return;
    if (/[^\x21-\x7E]/.test(event.data)) event.preventDefault();
  });
  
  
  document.addEventListener("click", (event) => {
    const preparingDownload = event.target.closest("a[data-download-preparing]");
    if (preparingDownload) {
      const key = downloadKey(preparingDownload);
      const activeDownload = activeDownloads.get(key);
      if (preparingDownload.dataset.downloadPreparingActive === "true") {
        event.preventDefault();
        showDownloadPreparingNotice(activeDownload?.label || preparingDownload.dataset.downloadPreparing || "Файл уже готовится...");
        return;
      }
      if (activeDownload) {
        event.preventDefault();
        showDownloadPreparingNotice(activeDownload.label);
        return;
      }
      if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && preparingDownload.target !== "_blank") {
        event.preventDefault();
        const token = downloadToken();
        const label = preparingDownload.dataset.downloadPreparing || "Подготовка файла...";
        activeDownloads.set(key, { token, label, startedAt: Date.now() });
        markPreparingDownload(preparingDownload, key, label);
        waitForDownloadStart(token, key);
        window.location.href = downloadUrlWithToken(preparingDownload.href, token);
      }
      return;
    }
  
    const tab = event.target.closest('[data-table-tab="true"][data-table-key]');
    if (!tab) return;
    const departmentSlug = tab.closest("[data-tables-workspace]")?.dataset.departmentSlug;
    if (departmentSlug) {
      storeValue(departmentTableStorageKey(departmentSlug), tab.dataset.tableKey);
      tab.setAttribute("hx-get", tableUrlWithSavedState(tab));
    }
  }, true);
  
  document.addEventListener("click", (event) => {
    const resetTableState = event.target.closest("[data-reset-table-state]");
    if (resetTableState) {
      clearCurrentTableState();
      const restoredOrganId = resetTableStateToSingleOrgan(resetTableState.dataset.resetOrganId);
      if (restoredOrganId) {
        const url = new URL(resetTableState.getAttribute("hx-get") || resetTableState.href, window.location.href);
        url.searchParams.delete("organ_ids");
        url.pathname = url.pathname.replace(/\/organs\/\d+\//, `/organs/${restoredOrganId}/`);
        const nextUrl = `${url.pathname}${url.search}`;
        resetTableState.setAttribute("hx-get", nextUrl);
        resetTableState.setAttribute("href", nextUrl);
      }
    }
  
    const organMode = event.target.closest("[data-organ-mode]");
    if (organMode) {
      event.preventDefault();
      setOrganMode(organMode.dataset.organMode);
      if (!isMultiOrganMode()) {
        const organ = findOrganById(rememberedSingleOrganId()) || document.querySelector(".organ-item[data-organ-id]");
        if (organ) {
          setActiveOrgan(organ);
          loadOrganInfo(organ.dataset.organId);
        }
        const department = preferredDepartmentForOrgan(window.selectedOrgan);
        if (department) {
          setActiveDepartment(department);
          loadDepartment(department);
        }
        return;
      }
      const department = checkedOrganIds().length ? preferredDepartmentForOrgan(window.selectedOrgan) : null;
      if (department) {
        setActiveDepartment(department);
        loadDepartment(department);
      } else {
        clearActiveDepartment();
        renderMultiOrganWorkspaceEmpty();
      }
      return;
    }
  
    const selectAll = event.target.closest("[data-organ-select-all]");
    if (selectAll) {
      event.preventDefault();
      document.querySelectorAll("[data-organ-checkbox]").forEach((checkbox) => {
        if (!checkbox.closest("[data-organ-row]")?.hidden) checkbox.checked = true;
      });
      storeCheckedOrganIds();
      const department = preferredDepartmentForOrgan(window.selectedOrgan);
      if (department) loadDepartment(department);
      return;
    }
  
    const clearAll = event.target.closest("[data-organ-clear-all]");
    if (clearAll) {
      event.preventDefault();
      document.querySelectorAll("[data-organ-checkbox]").forEach((checkbox) => {
        checkbox.checked = false;
      });
      storeCheckedOrganIds();
      renderMultiOrganInfo();
      clearActiveDepartment();
      renderMultiOrganWorkspaceEmpty();
      return;
    }
  
    const productSuggestion = event.target.closest("[data-tmc-product-suggestion]");
    if (productSuggestion) {
      chooseTmcProductSuggestion(productSuggestion);
      return;
    }
  
  
    if (!event.target.closest("[data-tmc-product-field]")) closeAllTmcProductSuggestions();
  
    const panelToggle = event.target.closest("[data-panel-toggle]");
    if (panelToggle) {
      const state = readCollapsedPanels();
      const panel = panelToggle.dataset.panelToggle;
      state[panel] = !state[panel];
      writeCollapsedPanels(state);
      applyCollapsedPanels();
      return;
    }
  
    const bulkPicker = event.target.closest("[data-bulk-photo-picker]");
    if (bulkPicker) {
      bulkPicker.closest("[data-bulk-photo-form]")?.querySelector("[data-bulk-photo-input]")?.click();
      return;
    }
  
    const bulkRemove = event.target.closest("[data-remove-bulk-photo]");
    if (bulkRemove) {
      const form = bulkRemove.closest("[data-bulk-photo-form]");
      if (form) PhotoUpload.removeBulkPhotoFile(form, Number(bulkRemove.dataset.removeBulkPhoto));
      return;
    }
  
    const singleFileButton = event.target.closest("[data-single-file-button]");
    if (singleFileButton) {
      singleFileButton.closest("[data-single-file-picker]")?.querySelector("input[type='file']")?.click();
      return;
    }
  
    const requestPhotoToggle = event.target.closest("[data-request-photo-toggle]");
    if (requestPhotoToggle) {
      const box = requestPhotoToggle.closest("[data-request-photo-box]");
      const panel = box?.querySelector("[data-request-photo-panel]");
      if (!box || !panel) return;
      panel.hidden = !panel.hidden;
      syncRequestPhotoPicker(box);
      if (!panel.hidden) scheduleRequestPhotoPickerScroll(box);
      return;
    }
  
    const detachPhoto = event.target.closest("[data-detach-request-photo]");
    if (detachPhoto) {
      detachRequestPhoto(detachPhoto);
      return;
    }
  
    const addTmcItem = event.target.closest("[data-add-tmc-item]");
    if (addTmcItem) {
      const list = addTmcItem.closest("[data-tmc-request-form]")?.querySelector("[data-tmc-items]");
      const row = list?.querySelector("[data-tmc-item-row]");
      if (!list || !row) return;
      const clone = row.cloneNode(true);
      clone.querySelectorAll("input").forEach((input) => {
        input.value = input.name === "item_unit" ? "шт." : "";
      });
      list.append(clone);
      clone.querySelector("input")?.focus();
      return;
    }
  
    const removeTmcItem = event.target.closest("[data-remove-tmc-item]");
    if (removeTmcItem) {
      const list = removeTmcItem.closest("[data-tmc-items]");
      const rows = list?.querySelectorAll("[data-tmc-item-row]");
      if (!list || !rows) return;
      if (rows.length > 1) {
        removeTmcItem.closest("[data-tmc-item-row]")?.remove();
      } else {
        rows[0].querySelectorAll("input").forEach((input) => {
          input.value = input.name === "item_unit" ? "шт." : "";
        });
      }
      return;
    }
  
    const passwordToggle = event.target.closest("[data-password-toggle]");
    if (passwordToggle) {
      const input = document.getElementById(passwordToggle.getAttribute("aria-controls"));
      if (!input) return;
      const shouldShow = input.type === "password";
      input.type = shouldShow ? "text" : "password";
      passwordToggle.setAttribute("aria-label", shouldShow ? "Скрыть пароль" : "Показать пароль");
      passwordToggle.innerHTML = shouldShow ? '<i class="bi bi-eye-slash"></i>' : '<i class="bi bi-eye"></i>';
      input.focus();
      return;
    }
  
    const tab = event.target.closest('[data-table-tab="true"]');
    if (!tab) return;
    const tabList = tab.closest(".nav-tabs");
    if (!tabList) return;
    tabList.querySelectorAll(".nav-link").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
  });
  
  document.addEventListener("click", (event) => {
    const organ = event.target.closest(".organ-item[data-organ-id]");
    if (!organ) return;
    if (isMultiOrganMode()) {
      event.preventDefault();
      const checkbox = organ.closest("[data-organ-row]")?.querySelector("[data-organ-checkbox]");
      if (checkbox) {
        checkbox.checked = !checkbox.checked;
        storeCheckedOrganIds();
      }
      const department = preferredDepartmentForOrgan(window.selectedOrgan);
      if (department) loadDepartment(department);
      return;
    }
    setActiveOrgan(organ);
  
    const departments = document.querySelectorAll(".department-item[data-department-slug]");
    departments.forEach((department) => {
      department.classList.remove("active");
      department.removeAttribute("aria-current");
    });
  
    const department = preferredDepartmentForOrgan(window.selectedOrgan);
    if (department) {
      setActiveDepartment(department);
      loadDepartment(department);
    }
  });
  
  document.addEventListener("change", (event) => {
    if (!event.target.matches("[data-organ-checkbox]")) return;
    storeCheckedOrganIds();
    if (!isMultiOrganMode()) return;
    const department = preferredDepartmentForOrgan(window.selectedOrgan);
    if (department) loadDepartment(department);
  });
  
  document.addEventListener("click", (event) => {
    const department = event.target.closest(".department-item[data-department-slug]");
    if (!department) return;
    event.preventDefault();
    setActiveDepartment(department);
    loadDepartment(department);
  });
}
