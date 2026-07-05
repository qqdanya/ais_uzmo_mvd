// Request photo attachment picker helpers.
function syncRequestPhotoPicker(box) {
  const selectedBox = box.querySelector("[data-request-photo-selected]");
  const checkboxes = Array.from(box.querySelectorAll("[data-request-photo-checkbox]"));
  const selectedIds = new Set(Array.from(selectedBox?.querySelectorAll("[data-request-photo-hidden]") || []).map((input) => input.value));
  checkboxes.forEach((checkbox) => {
    checkbox.checked = selectedIds.has(checkbox.value);
  });
  box.querySelector("[data-request-photo-count]").textContent = String(selectedIds.size);
  checkboxes.forEach((checkbox) => {
    checkbox.closest(".request-photo-option")?.classList.toggle("is-selected", checkbox.checked);
  });
}

function setRequestPhotoSelected(checkbox) {
  const box = checkbox.closest("[data-request-photo-box]");
  const selectedBox = box?.querySelector("[data-request-photo-selected]");
  if (!box || !selectedBox) return;
  selectedBox.querySelectorAll(`[data-request-photo-hidden][value="${CSS.escape(checkbox.value)}"]`).forEach((input) => input.remove());
  if (checkbox.checked) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "attached_photos";
    input.value = checkbox.value;
    input.dataset.requestPhotoHidden = "true";
    selectedBox.append(input);
  }
  syncRequestPhotoPicker(box);
}

function detachRequestPhoto(button) {
  const box = button.closest("[data-request-photo-box]");
  if (!box) return;
  const photoId = button.dataset.detachRequestPhoto;
  box.querySelectorAll(`[data-request-photo-hidden][value="${CSS.escape(photoId)}"]`).forEach((input) => input.remove());
  box.querySelectorAll(`[data-request-photo-checkbox][value="${CSS.escape(photoId)}"]`).forEach((checkbox) => {
    checkbox.checked = false;
  });
  button.closest("[data-request-linked-photo]")?.remove();
  const list = box.querySelector("[data-request-linked-photos]");
  if (list && !list.querySelector("[data-request-linked-photo]") && !list.querySelector("[data-request-linked-empty]")) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.dataset.requestLinkedEmpty = "true";
    empty.textContent = "К заявке фотографии не прикреплены";
    list.append(empty);
  }
  syncRequestPhotoPicker(box);
}

function scrollRequestPhotoPickerIntoView(box) {
  if (!box) return;
  const panel = box.querySelector("[data-request-photo-panel]");
  if (!panel || panel.hidden) return;

  window.requestAnimationFrame(() => {
    const target = box.querySelector("[data-request-photo-scroll-anchor]") || panel;
    const modalBody = target.closest(".modal-body");
    const container = modalBody || document.scrollingElement || document.documentElement;
    const targetRect = target.getBoundingClientRect();

    if (modalBody) {
      const containerRect = modalBody.getBoundingClientRect();
      const nextTop = modalBody.scrollTop + targetRect.bottom - containerRect.bottom + 24;
      modalBody.scrollTo({ top: Math.max(0, nextTop), behavior: "smooth" });
      return;
    }

    const viewportBottom = window.innerHeight || document.documentElement.clientHeight;
    const nextTop = window.scrollY + targetRect.bottom - viewportBottom + 32;
    if (targetRect.bottom > viewportBottom - 24) {
      window.scrollTo({ top: Math.max(0, nextTop), behavior: "smooth" });
    }
  });
}

function scheduleRequestPhotoPickerScroll(box) {
  if (!box) return;
  window.setTimeout(() => scrollRequestPhotoPickerIntoView(box), 40);
}

function refreshCurrentTableArea() {
  const tableArea = document.getElementById("table-area");
  if (!tableArea || !window.htmx) return;
  const activeTab = document.querySelector('[data-table-tab="true"].active');
  const url = activeTab?.getAttribute("hx-get") || tableArea.getAttribute("hx-get");
  if (url) window.htmx.ajax("GET", url, { target: "#table-area", swap: "innerHTML" });
}
