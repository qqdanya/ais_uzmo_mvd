// HTMX progress/errors and Bootstrap modal lifecycle.
let htmxRequests = 0;
let loadingFailsafeTimer = null;

function setLoading(isLoading) {
  const progress = document.getElementById("htmx-progress");
  if (!progress) return;
  progress.classList.toggle("is-active", isLoading);
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
  setLoading(htmxRequests > 0);
  if (loadingFailsafeTimer) {
    window.clearTimeout(loadingFailsafeTimer);
    loadingFailsafeTimer = null;
  }
  if (htmxRequests > 0) {
    loadingFailsafeTimer = window.setTimeout(() => {
      htmxRequests = 0;
      setLoading(false);
    }, 30000);
  }
}

function startHtmxRequest() {
  htmxRequests += 1;
  syncLoadingState();
}

function finishHtmxRequest() {
  htmxRequests = Math.max(0, htmxRequests - 1);
  syncLoadingState();
}

function resetHtmxLoading() {
  htmxRequests = 0;
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

function registerModalLifecycle() {
  document.addEventListener("wheel", preventBackgroundModalScroll, { passive: false });
  document.addEventListener("touchmove", preventBackgroundModalScroll, { passive: false });

  const appModalRoot = document.getElementById("modal-root");
  appModalRoot?.addEventListener("show.bs.modal", lockDocumentScrollForModal);
  appModalRoot?.addEventListener("hidden.bs.modal", unlockDocumentScrollForModal);
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
  refreshCurrentTableArea();
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
      if (bulkForm) {
        PhotoUpload.renderPendingBulkPhotoFiles(bulkForm);
      }
      event.detail.target.querySelectorAll("[data-request-photo-box]").forEach(syncRequestPhotoPicker);
      syncActiveDownloadButtons(event.detail.target);
      return;
    }
    saveTableStateFromHtmxEvent(event);
    initCustomSelects(event.detail.target);
    initTooltips();
    autoDismissAlerts();
    event.detail.target.querySelectorAll?.("[data-request-photo-box]").forEach((box) => {
      syncRequestPhotoPicker(box);
      scheduleRequestPhotoPickerScroll(box);
    });
    const requestPhotoBox = event.detail.target.closest?.("[data-request-photo-box]");
    if (requestPhotoBox) {
      syncRequestPhotoPicker(requestPhotoBox);
      scheduleRequestPhotoPickerScroll(requestPhotoBox);
    }
    syncActiveDownloadButtons(event.detail.target);
    applyCollapsedPanels();
    scrollAfterPaginationSwap(event);
  });

  body.addEventListener("htmx:configRequest", (event) => {
    if (!isResetTableStateTrigger(event.detail?.elt)) return;
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
