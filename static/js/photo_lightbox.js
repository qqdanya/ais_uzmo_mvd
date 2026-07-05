let photoLightboxState = {
  items: [],
  index: 0,
  scale: 1,
  offsetX: 0,
  offsetY: 0,
  isDragging: false,
  dragStartX: 0,
  dragStartY: 0,
  dragOriginX: 0,
  dragOriginY: 0,
  didDrag: false,
  lastTrigger: null,
};

function ensurePhotoLightbox() {
  let lightbox = document.querySelector("[data-photo-lightbox]");
  if (lightbox) return lightbox;
  lightbox = document.createElement("div");
  lightbox.className = "photo-lightbox";
  lightbox.dataset.photoLightbox = "true";
  lightbox.setAttribute("aria-hidden", "true");
  lightbox.innerHTML = `
    <div class="photo-lightbox-backdrop" data-lightbox-action="close"></div>
    <section class="photo-lightbox-dialog" role="dialog" aria-modal="true" aria-label="Просмотр фотографии">
      <div class="photo-lightbox-toolbar">
        <button class="btn btn-icon" type="button" data-lightbox-action="previous" data-bs-toggle="tooltip" data-bs-title="Предыдущая" aria-label="Предыдущая фотография"><i class="bi bi-chevron-left"></i></button>
        <button class="btn btn-icon" type="button" data-lightbox-action="next" data-bs-toggle="tooltip" data-bs-title="Следующая" aria-label="Следующая фотография"><i class="bi bi-chevron-right"></i></button>
        <span class="photo-lightbox-counter" data-lightbox-counter></span>
        <button class="btn btn-icon" type="button" data-lightbox-action="zoom-out" data-bs-toggle="tooltip" data-bs-title="Уменьшить" aria-label="Уменьшить"><i class="bi bi-zoom-out"></i></button>
        <button class="btn btn-icon" type="button" data-lightbox-action="reset" data-bs-toggle="tooltip" data-bs-title="Масштаб 100%" aria-label="Сбросить масштаб"><span data-lightbox-scale>100%</span></button>
        <button class="btn btn-icon" type="button" data-lightbox-action="zoom-in" data-bs-toggle="tooltip" data-bs-title="Увеличить" aria-label="Увеличить"><i class="bi bi-zoom-in"></i></button>
        <a class="btn btn-icon btn-download" data-lightbox-download data-bs-toggle="tooltip" data-bs-title="Скачать" aria-label="Скачать фотографию"><i class="bi bi-download"></i></a>
        <button class="btn btn-icon danger" type="button" data-lightbox-action="close" data-bs-toggle="tooltip" data-bs-title="Закрыть" aria-label="Закрыть"><i class="bi bi-x-lg"></i></button>
      </div>
      <div class="photo-lightbox-viewport" data-lightbox-viewport>
        <img alt="" data-lightbox-image>
      </div>
      <div class="photo-lightbox-caption">
        <strong data-lightbox-description></strong>
        <span data-lightbox-meta></span>
      </div>
    </section>
  `;
  document.body.append(lightbox);
  if (typeof initTooltips === "function") initTooltips();
  return lightbox;
}

function lightboxItemFromButton(button) {
  return {
    trigger: button,
    src: button.dataset.src,
    downloadUrl: button.dataset.downloadUrl,
    description: button.dataset.description || "",
    meta: button.dataset.meta || "",
  };
}

function collectLightboxPhotos(trigger) {
  const group = trigger.dataset.lightboxGroup || "";
  if (group) {
    const groupScope = trigger.closest("[data-lightbox-scope]") || document;
    const groupedButtons = Array.from(groupScope.querySelectorAll("[data-lightbox-photo]"))
      .filter((button) => button.dataset.lightboxGroup === group);
    if (groupedButtons.length) return groupedButtons.map(lightboxItemFromButton);
  }

  const scope = trigger.closest("#photo-results") || trigger.closest("[data-lightbox-scope]") || trigger.closest(".modal-content") || document;
  return Array.from(scope.querySelectorAll("[data-lightbox-photo]")).map(lightboxItemFromButton);
}

function applyLightboxTransform() {
  const image = document.querySelector("[data-lightbox-image]");
  if (!image) return;
  const { scale, offsetX, offsetY } = photoLightboxState;
  image.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
  image.classList.toggle("is-zoomed", scale > 1);
  const scaleText = document.querySelector("[data-lightbox-scale]");
  if (scaleText) scaleText.textContent = `${Math.round(scale * 100)}%`;
}

function resetLightboxView() {
  photoLightboxState.scale = 1;
  photoLightboxState.offsetX = 0;
  photoLightboxState.offsetY = 0;
  applyLightboxTransform();
}

function renderPhotoLightbox() {
  const lightbox = ensurePhotoLightbox();
  const item = photoLightboxState.items[photoLightboxState.index];
  if (!item) return;
  const image = lightbox.querySelector("[data-lightbox-image]");
  image.src = item.src;
  image.alt = item.description;
  lightbox.querySelector("[data-lightbox-description]").textContent = item.description;
  lightbox.querySelector("[data-lightbox-meta]").textContent = item.meta;
  lightbox.querySelector("[data-lightbox-counter]").textContent = `${photoLightboxState.index + 1} / ${photoLightboxState.items.length}`;
  const download = lightbox.querySelector("[data-lightbox-download]");
  download.href = item.downloadUrl;
  resetLightboxView();
}

function openPhotoLightbox(trigger) {
  photoLightboxState.lastTrigger = trigger;
  photoLightboxState.items = collectLightboxPhotos(trigger);
  photoLightboxState.index = Math.max(0, photoLightboxState.items.findIndex((item) => item.trigger === trigger));
  const lightbox = ensurePhotoLightbox();
  renderPhotoLightbox();
  lightbox.classList.add("is-open");
  lightbox.setAttribute("aria-hidden", "false");
  document.body.classList.add("has-photo-lightbox");
}

function closePhotoLightbox(options = {}) {
  const lightbox = document.querySelector("[data-photo-lightbox]");
  if (!lightbox) return;
  lightbox.classList.remove("is-open");
  lightbox.setAttribute("aria-hidden", "true");
  document.body.classList.remove("has-photo-lightbox");
  photoLightboxState.isDragging = false;

  if (options.blurTrigger) {
    const active = document.activeElement;
    if (active && typeof active.blur === "function") active.blur();
    if (photoLightboxState.lastTrigger && typeof photoLightboxState.lastTrigger.blur === "function") {
      photoLightboxState.lastTrigger.blur();
    }
    photoLightboxState.lastTrigger = null;
  }
}

function navigatePhotoLightbox(direction) {
  if (!photoLightboxState.items.length) return;
  photoLightboxState.index = (photoLightboxState.index + direction + photoLightboxState.items.length) % photoLightboxState.items.length;
  renderPhotoLightbox();
}

function zoomPhotoLightbox(delta) {
  const nextScale = Math.min(4, Math.max(1, photoLightboxState.scale + delta));
  photoLightboxState.scale = Number(nextScale.toFixed(2));
  if (photoLightboxState.scale === 1) {
    photoLightboxState.offsetX = 0;
    photoLightboxState.offsetY = 0;
  }
  applyLightboxTransform();
}

function togglePhotoLightboxZoom() {
  if (photoLightboxState.scale <= 1) {
    photoLightboxState.scale = 2;
  } else {
    photoLightboxState.scale = 1;
    photoLightboxState.offsetX = 0;
    photoLightboxState.offsetY = 0;
  }
  applyLightboxTransform();
}

function handlePhotoLightboxClick(event) {
  const lightboxPhoto = event.target.closest("[data-lightbox-photo]");
  if (lightboxPhoto) {
    event.preventDefault();
    openPhotoLightbox(lightboxPhoto);
    return;
  }

  if (event.target.matches("[data-lightbox-image]")) {
    event.preventDefault();
    if (photoLightboxState.didDrag) {
      photoLightboxState.didDrag = false;
      return;
    }
    togglePhotoLightboxZoom();
    return;
  }

  const lightboxAction = event.target.closest("[data-lightbox-action]");
  if (!lightboxAction) return;
  event.preventDefault();
  const action = lightboxAction.dataset.lightboxAction;
  if (action === "close") closePhotoLightbox();
  if (action === "previous") navigatePhotoLightbox(-1);
  if (action === "next") navigatePhotoLightbox(1);
  if (action === "zoom-in") zoomPhotoLightbox(.25);
  if (action === "zoom-out") zoomPhotoLightbox(-.25);
  if (action === "reset") resetLightboxView();
}

function handlePhotoLightboxKeydown(event) {
  if (!document.querySelector("[data-photo-lightbox].is-open")) return;

  if (event.key === "Escape") closePhotoLightbox({ blurTrigger: true });
  else if (event.key === "ArrowLeft") navigatePhotoLightbox(-1);
  else if (event.key === "ArrowRight") navigatePhotoLightbox(1);
  else if (event.key === "+" || event.key === "=") zoomPhotoLightbox(.25);
  else if (event.key === "-") zoomPhotoLightbox(-.25);
  else if (event.key === "0") resetLightboxView();
  else return;

  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation?.();
}

document.addEventListener("keydown", handlePhotoLightboxKeydown, true);

document.addEventListener("keydown", (event) => {
  if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey && !isEditableTarget(event.target)) {
    if (focusCurrentSearch()) event.preventDefault();
    return;
  }

  const trigger = event.target.closest("[data-custom-select-trigger]");
  if (trigger && ["Enter", " ", "ArrowDown"].includes(event.key)) {
    event.preventDefault();
    openCustomSelect(trigger.closest("[data-custom-select]"));
    return;
  }
  if (event.key === "Escape") {
    closeCustomSelects();
    closeRequestPhotoSortSelects();
    closeAllTmcProductSuggestions();
    closeOpenModal();
  }
});

document.addEventListener("wheel", (event) => {
  if (!event.target.closest("[data-lightbox-viewport]")) return;
  event.preventDefault();
  zoomPhotoLightbox(event.deltaY < 0 ? .18 : -.18);
}, { passive: false });

document.addEventListener("pointerdown", (event) => {
  if (!event.target.matches("[data-lightbox-image]") || photoLightboxState.scale <= 1) return;
  event.preventDefault();
  photoLightboxState.isDragging = true;
  photoLightboxState.dragStartX = event.clientX;
  photoLightboxState.dragStartY = event.clientY;
  photoLightboxState.dragOriginX = photoLightboxState.offsetX;
  photoLightboxState.dragOriginY = photoLightboxState.offsetY;
  photoLightboxState.didDrag = false;
  event.target.setPointerCapture?.(event.pointerId);
});

document.addEventListener("pointermove", (event) => {
  if (!photoLightboxState.isDragging) return;
  if (Math.abs(event.clientX - photoLightboxState.dragStartX) > 3 || Math.abs(event.clientY - photoLightboxState.dragStartY) > 3) {
    photoLightboxState.didDrag = true;
  }
  photoLightboxState.offsetX = photoLightboxState.dragOriginX + event.clientX - photoLightboxState.dragStartX;
  photoLightboxState.offsetY = photoLightboxState.dragOriginY + event.clientY - photoLightboxState.dragStartY;
  applyLightboxTransform();
});

document.addEventListener("pointerup", () => {
  photoLightboxState.isDragging = false;
});

document.addEventListener("click", handlePhotoLightboxClick);
