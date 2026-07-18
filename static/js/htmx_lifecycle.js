// HTMX progress/errors and Bootstrap modal lifecycle.
const LOADING_SHOW_DELAY_MS = 180;
const LOADING_MIN_VISIBLE_MS = 320;
const LOADING_COMPLETE_MS = 180;
const LOADING_FADE_MS = 160;
let htmxRequests = 0;
let loadingFailsafeTimer = null;
let loadingShowTimer = null;
let loadingCompleteTimer = null;
let loadingHideTimer = null;
let loadingResetTimer = null;
let loadingShownAt = 0;
let loadingCycle = 0;

function loadingProgress() {
  return document.getElementById("htmx-progress");
}

function clearLoadingTimer(timer) {
  if (timer) window.clearTimeout(timer);
  return null;
}

function clearProgressTimers() {
  loadingShowTimer = clearLoadingTimer(loadingShowTimer);
  loadingCompleteTimer = clearLoadingTimer(loadingCompleteTimer);
  loadingHideTimer = clearLoadingTimer(loadingHideTimer);
  loadingResetTimer = clearLoadingTimer(loadingResetTimer);
}

function resetProgressElement(progress = loadingProgress()) {
  progress?.classList.remove("is-active", "is-running", "is-completing", "is-hiding");
  loadingShownAt = 0;
}

function startLoadingProgress() {
  const progress = loadingProgress();
  if (!progress) return;
  const cycle = ++loadingCycle;
  clearProgressTimers();
  resetProgressElement(progress);
  loadingShowTimer = window.setTimeout(() => {
    loadingShowTimer = null;
    if (cycle !== loadingCycle || htmxRequests === 0) return;
    progress.classList.add("is-active");
    loadingShownAt = performance.now();
    window.requestAnimationFrame(() => {
      if (cycle === loadingCycle && htmxRequests > 0) progress.classList.add("is-running");
    });
  }, LOADING_SHOW_DELAY_MS);
}

function finishLoadingProgress() {
  const progress = loadingProgress();
  loadingShowTimer = clearLoadingTimer(loadingShowTimer);
  loadingCompleteTimer = clearLoadingTimer(loadingCompleteTimer);
  loadingHideTimer = clearLoadingTimer(loadingHideTimer);
  loadingResetTimer = clearLoadingTimer(loadingResetTimer);
  if (!progress?.classList.contains("is-active")) {
    resetProgressElement(progress);
    return;
  }

  const cycle = loadingCycle;
  const visibleFor = performance.now() - loadingShownAt;
  const completionDelay = Math.max(0, LOADING_MIN_VISIBLE_MS - visibleFor);
  loadingCompleteTimer = window.setTimeout(() => {
    loadingCompleteTimer = null;
    if (cycle !== loadingCycle || htmxRequests > 0) return;
    progress.classList.remove("is-running");
    progress.classList.add("is-completing");
    loadingHideTimer = window.setTimeout(() => {
      loadingHideTimer = null;
      if (cycle !== loadingCycle || htmxRequests > 0) return;
      progress.classList.add("is-hiding");
      loadingResetTimer = window.setTimeout(() => {
        loadingResetTimer = null;
        if (cycle === loadingCycle && htmxRequests === 0) resetProgressElement(progress);
      }, LOADING_FADE_MS);
    }, LOADING_COMPLETE_MS);
  }, completionDelay);
}

function syncHeaderHeight() {
  const header = document.querySelector(".app-header");
  const footer = document.querySelector(".app-footer");
  if (header) {
    document.documentElement.style.setProperty("--app-header-height", `${Math.ceil(header.getBoundingClientRect().height)}px`);
  }
  if (footer) {
    document.documentElement.style.setProperty("--app-footer-height", `${Math.ceil(footer.getBoundingClientRect().height)}px`);
  }
}

function syncLoadingState() {
  if (loadingFailsafeTimer) {
    window.clearTimeout(loadingFailsafeTimer);
    loadingFailsafeTimer = null;
  }
  if (htmxRequests > 0) {
    loadingFailsafeTimer = window.setTimeout(() => {
      htmxRequests = 0;
      finishLoadingProgress();
    }, 30000);
  }
}

function startHtmxRequest() {
  const startsNewCycle = htmxRequests === 0;
  htmxRequests += 1;
  if (startsNewCycle) startLoadingProgress();
  syncLoadingState();
}

function finishHtmxRequest() {
  htmxRequests = Math.max(0, htmxRequests - 1);
  if (htmxRequests === 0) finishLoadingProgress();
  syncLoadingState();
}

function resetHtmxLoading() {
  htmxRequests = 0;
  finishLoadingProgress();
  syncLoadingState();
}

function isAppModalOpen() {
  return document.getElementById("modal-root")?.classList.contains("show");
}

function lockDocumentScrollForModal() {
  document.documentElement.classList.add("app-modal-scroll-locked");
}

function unlockDocumentScrollForModal() {
  document.documentElement.classList.remove("app-modal-scroll-locked");
}

function isScrollableY(element) {
  const style = window.getComputedStyle(element);
  return ["auto", "scroll"].includes(style.overflowY) && element.scrollHeight > element.clientHeight;
}

function closestScrollableModalElement(target, dialog) {
  let element = target instanceof Element ? target : null;
  while (element && element !== dialog.parentElement) {
    if (dialog.contains(element) && isScrollableY(element)) return element;
    if (element === dialog) break;
    element = element.parentElement;
  }
  const modalBody = dialog.querySelector(".modal-body");
  return modalBody && isScrollableY(modalBody) ? modalBody : null;
}

function preventBackgroundModalScroll(event) {
  if (!isAppModalOpen()) return;
  const dialog = event.target?.closest?.("#modal-root .modal-dialog");
  if (!dialog) {
    event.preventDefault();
    return;
  }
  const scrollElement = closestScrollableModalElement(event.target, dialog);
  if (!scrollElement) {
    event.preventDefault();
    return;
  }
  const deltaY = event.deltaY || 0;
  if (!deltaY) return;
  const scrollTop = scrollElement.scrollTop;
  const maxScrollTop = scrollElement.scrollHeight - scrollElement.clientHeight;
  const canScrollDown = deltaY > 0 && scrollTop < maxScrollTop;
  const canScrollUp = deltaY < 0 && scrollTop > 0;
  if (event.target?.closest?.(".modal-body") && (canScrollDown || canScrollUp)) return;
  event.preventDefault();
  if (canScrollDown || canScrollUp) {
    scrollElement.scrollTop += deltaY;
  }
}

// Generic modal/search-focus utilities (isVisibleElement comes from
// app_dom_utils.js, also core). These live here rather than in
// table_interactions.js (dashboard-only) because photo_lightbox.js's global
// Escape/"/" shortcut handler — also core — calls closeOpenModal() and
// focusCurrentSearch() unconditionally on every page.
function focusCurrentSearch() {
  const modal = document.querySelector("#modal-root.show .modal-content");
  const scopes = [modal, document.getElementById("workspace"), document].filter(Boolean);
  const selectors = [
    "#request-photo-search-input",
    "#photo-search-input",
    "[id^='table-search-']",
    "[data-table-search]",
    "#organ-search",
  ];
  for (const scope of scopes) {
    for (const selector of selectors) {
      const input = scope.querySelector(selector);
      if (!isVisibleElement(input)) continue;
      input.focus();
      input.select?.();
      return true;
    }
  }
  return false;
}

function closeOpenModal() {
  const modalElement = document.getElementById("modal-root");
  if (!modalElement?.classList.contains("show")) return false;
  bootstrap.Modal.getInstance(modalElement)?.hide();
  return true;
}

function scrollAfterPaginationSwap(event) {
  const trigger = event.detail?.requestConfig?.elt;
  const pagination = trigger?.closest?.("[data-pagination-scroll]");
  if (!pagination) return;
  const targetSelector = pagination.dataset.paginationScroll;
  if (!targetSelector) return;
  const swapTarget = event.detail?.target;
  const target = targetSelector === "self" ? swapTarget : swapTarget?.querySelector?.(targetSelector);
  if (!target) return;
  target.scrollTo?.({ top: 0, left: target.scrollLeft, behavior: "smooth" });
}

function releaseModalObjectUrls(container) {
  // Bulk/single photo pickers create blob: URLs for local-file previews
  // (photo_upload.js). Revoking them here, not just on the next successful
  // upload, is what actually frees that memory when a form is abandoned
  // (closed without submitting) — URL.revokeObjectURL is never called
  // automatically just because the referencing DOM node was removed.
  container.querySelectorAll("[data-bulk-preview-url]").forEach((preview) => {
    URL.revokeObjectURL(preview.dataset.bulkPreviewUrl);
  });
  container.querySelectorAll("[data-object-url]").forEach((preview) => {
    URL.revokeObjectURL(preview.dataset.objectUrl);
  });
}

function cleanupModalContent() {
  const modalContent = document.getElementById("modal-content");
  if (!modalContent) return;
  releaseModalObjectUrls(modalContent);
  modalContent.replaceChildren();
}

function registerModalLifecycle() {
  document.addEventListener("wheel", preventBackgroundModalScroll, { passive: false });
  document.addEventListener("touchmove", preventBackgroundModalScroll, { passive: false });

  const appModalRoot = document.getElementById("modal-root");
  appModalRoot?.addEventListener("show.bs.modal", lockDocumentScrollForModal);
  appModalRoot?.addEventListener("hidden.bs.modal", unlockDocumentScrollForModal);
  // Runs after the close transition, once the modal is already invisible, so
  // clearing #modal-content here can't be seen mid-close.
  appModalRoot?.addEventListener("hidden.bs.modal", cleanupModalContent);
  appModalRoot?.addEventListener("shown.bs.modal", () => {
    const input = appModalRoot.querySelector("[autofocus]");
    if (!isVisibleElement(input)) return;
    input.focus();
    input.select?.();
  });
}


function closeModalFromHtmxTrigger() {
  const modalElement = document.getElementById("modal-root");
  if (!modalElement) return;
  const modal = bootstrap.Modal.getInstance(modalElement) || bootstrap.Modal.getOrCreateInstance(modalElement);
  modal.hide();
}

function showToastFromHtmxTrigger(event) {
  const detail = event.detail || {};
  showToast(detail.message, detail.level || "success");
}

function refreshTableAfterRequestPhotosChanged() {
  if (typeof refreshCurrentTableArea === "function") refreshCurrentTableArea();
}

function registerHtmxLifecycle() {
  const body = document.body;
  if (!body) return;

  body.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail.target.id === "modal-content") {
      initCustomSelects(event.detail.target);
      initTooltips();
      autoDismissAlerts();
      bootstrap.Modal.getOrCreateInstance(document.getElementById("modal-root")).show();
      const bulkForm = event.detail.target.querySelector("[data-bulk-photo-form]");
      // Modals can open on any page (photo_upload.js/request_photo_picker.js/
      // download_preparing.js are dashboard-only), so these enrichments are
      // only safe to run where the relevant module actually loaded.
      if (bulkForm && window.PhotoUpload) {
        PhotoUpload.renderPendingBulkPhotoFiles(bulkForm);
      }
      if (typeof syncRequestPhotoPicker === "function") {
        event.detail.target.querySelectorAll("[data-request-photo-box]").forEach(syncRequestPhotoPicker);
      }
      if (typeof syncActiveDownloadButtons === "function") {
        syncActiveDownloadButtons(event.detail.target);
      }
      return;
    }
    if (typeof saveTableStateFromHtmxEvent === "function") saveTableStateFromHtmxEvent(event);
    initCustomSelects(event.detail.target);
    initTooltips();
    autoDismissAlerts();
    if (typeof syncRequestPhotoPicker === "function") {
      event.detail.target.querySelectorAll?.("[data-request-photo-box]").forEach((box) => {
        syncRequestPhotoPicker(box);
        scheduleRequestPhotoPickerScroll(box);
      });
      const requestPhotoBox = event.detail.target.closest?.("[data-request-photo-box]");
      if (requestPhotoBox) {
        syncRequestPhotoPicker(requestPhotoBox);
        scheduleRequestPhotoPickerScroll(requestPhotoBox);
      }
    }
    if (typeof syncActiveDownloadButtons === "function") syncActiveDownloadButtons(event.detail.target);
    if (typeof syncFolderPickerBox === "function") {
      const folderPickerBox = event.detail.target.closest?.("[data-folder-picker-box]");
      if (folderPickerBox) syncFolderPickerBox(folderPickerBox);
    }
    applyCollapsedPanels();
    scrollAfterPaginationSwap(event);
  });

  body.addEventListener("htmx:configRequest", (event) => {
    if (typeof isResetTableStateTrigger !== "function" || !isResetTableStateTrigger(event.detail?.elt)) return;
    const organId = event.detail.elt.dataset.resetOrganId;
    const restoredOrganId = resetTableStateToSingleOrgan(organId);
    event.detail.parameters?.delete?.("organ_ids");
    if (event.detail.parameters && typeof event.detail.parameters === "object" && !event.detail.parameters.delete) {
      delete event.detail.parameters.organ_ids;
    }
    if (event.detail.path) {
      const url = new URL(event.detail.path, window.location.href);
      url.searchParams.delete("organ_ids");
      if (restoredOrganId) {
        url.pathname = url.pathname.replace(/\/organs\/\d+\//, `/organs/${restoredOrganId}/`);
      }
      event.detail.path = `${url.pathname}${url.search}`;
    }
  });

  body.addEventListener("htmx:beforeRequest", startHtmxRequest);
  body.addEventListener("htmx:afterRequest", finishHtmxRequest);

  body.addEventListener("htmx:responseError", (event) => {
    resetHtmxLoading();
    const status = event.detail?.xhr?.status;
    const message = status === 413
      ? "Слишком большой объем данных для одного запроса. Фотографии будут надежнее загружаться пакетами."
      : "Не удалось выполнить действие.";
    showToast(message, "danger");
  });

  body.addEventListener("htmx:sendError", () => {
    resetHtmxLoading();
    showToast("Не удалось отправить запрос.", "danger");
  });

  body.addEventListener("htmx:timeout", () => {
    resetHtmxLoading();
    showToast("Запрос выполнялся слишком долго.", "warning");
  });

  body.addEventListener("htmx:abort", resetHtmxLoading);

  body.addEventListener("modal:close", closeModalFromHtmxTrigger);
  body.addEventListener("toast", showToastFromHtmxTrigger);
  body.addEventListener("requestPhotosChanged", refreshTableAfterRequestPhotosChanged);

  body.addEventListener("htmx:swapError", () => {
    resetHtmxLoading();
    showToast("Не удалось обновить данные на странице.", "danger");
  });
}
