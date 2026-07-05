// Photo upload widgets, previews, drag-and-drop and bulk upload batches.
const BULK_PHOTO_BATCH_SIZE = 25;
let pendingBulkPhotoFiles = [];

function appFormatLocalDateTime(date) {
  if (typeof window.formatLocalDateTime === "function") return window.formatLocalDateTime(date);
  const pad = (value) => String(value).padStart(2, "0");
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function appSetLoading(isLoading) {
  if (typeof window.setLoading === "function") window.setLoading(isLoading);
}

function appShowToast(message, level = "success") {
  if (typeof window.showToast === "function") window.showToast(message, level);
}

function renderBulkPhotoFiles(form, files, descriptions = null) {
  const input = form.querySelector("[data-bulk-photo-input]");
  const list = form.querySelector("[data-bulk-photo-list]");
  if (!input || !list) return;
  const previousDescriptions = descriptions || Array.from(list.querySelectorAll("[data-bulk-description]")).map((textarea) => textarea.value);
  list.querySelectorAll("[data-bulk-preview-url]").forEach((preview) => {
    URL.revokeObjectURL(preview.dataset.bulkPreviewUrl);
  });
  const images = Array.from(files).filter((file) => file.type.startsWith("image/"));
  const transfer = new DataTransfer();
  images.forEach((file) => transfer.items.add(file));
  input.files = transfer.files;
  list.replaceChildren();
  if (!images.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Изображения не выбраны";
    list.append(empty);
    return;
  }
  images.forEach((file, index) => {
    const item = document.createElement("div");
    item.className = "bulk-photo-item";
    item.dataset.bulkPhotoIndex = String(index);
    const previewUrl = URL.createObjectURL(file);
    const preview = document.createElement("div");
    preview.className = "bulk-photo-preview";
    preview.dataset.bulkPreviewUrl = previewUrl;
    const image = document.createElement("img");
    image.src = previewUrl;
    image.alt = file.name;
    image.loading = "lazy";
    preview.append(image);
    const body = document.createElement("div");
    body.className = "bulk-photo-body";
    const meta = document.createElement("div");
    meta.className = "bulk-photo-meta";
    const metaInfo = document.createElement("div");
    metaInfo.className = "bulk-photo-meta-info";
    const icon = document.createElement("i");
    icon.className = "bi bi-file-image";
    const filename = document.createElement("span");
    filename.textContent = file.name;
    metaInfo.append(icon, filename);
    const remove = document.createElement("button");
    remove.className = "btn btn-icon danger bulk-photo-remove";
    remove.type = "button";
    remove.dataset.removeBulkPhoto = String(index);
    remove.setAttribute("aria-label", "Убрать изображение из загрузки");
    remove.innerHTML = '<i class="bi bi-x-lg"></i>';
    meta.append(metaInfo, remove);
    const label = document.createElement("label");
    label.className = "form-label";
    label.setAttribute("for", `bulk-description-${index}`);
    label.textContent = "Описание";
    const textarea = document.createElement("textarea");
    textarea.className = "form-control";
    textarea.id = `bulk-description-${index}`;
    textarea.name = "descriptions";
    textarea.dataset.bulkDescription = String(index);
    textarea.rows = 2;
    textarea.placeholder = "Описание фотографии";
    textarea.value = previousDescriptions[index] || "";
    body.append(meta, label, textarea);
    item.append(preview, body);
    list.append(item);
  });
}

function removeBulkPhotoFile(form, index) {
  const input = form.querySelector("[data-bulk-photo-input]");
  const list = form.querySelector("[data-bulk-photo-list]");
  if (!input) return;
  const files = Array.from(input.files).filter((_, fileIndex) => fileIndex !== index);
  const descriptions = Array.from(list?.querySelectorAll("[data-bulk-description]") || [])
    .filter((_, descriptionIndex) => descriptionIndex !== index)
    .map((textarea) => textarea.value);
  renderBulkPhotoFiles(form, files, descriptions);
}

function csrfToken(form) {
  return form.querySelector('[name="csrfmiddlewaretoken"]')?.value || "";
}

function setBulkUploadProgress(form, uploaded, total, note = "") {
  const progress = form.querySelector("[data-bulk-upload-progress]");
  const counter = form.querySelector("[data-bulk-upload-counter]");
  const bar = form.querySelector("[data-bulk-upload-bar]");
  const noteNode = form.querySelector("[data-bulk-upload-note]");
  if (!progress) return;
  progress.hidden = false;
  if (counter) counter.textContent = `${uploaded} / ${total}`;
  if (bar) bar.style.width = `${total ? Math.round((uploaded / total) * 100) : 0}%`;
  if (noteNode && note) noteNode.textContent = note;
}

function setBulkPhotoFormBusy(form, isBusy) {
  form.classList.toggle("is-uploading", isBusy);
  form.querySelectorAll("button, input, textarea").forEach((control) => {
    control.disabled = isBusy;
  });
  const submit = form.querySelector("[data-bulk-upload-submit]");
  if (submit) {
    submit.innerHTML = isBusy
      ? '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Загрузка...'
      : '<i class="bi bi-cloud-arrow-up"></i> Загрузить';
  }
}

function updateSingleFilePicker(input) {
  const picker = input.closest("[data-single-file-picker]");
  const file = input.files?.[0];
  const name = picker?.querySelector("[data-single-file-name]");
  if (name) name.textContent = file?.name || "Изображение не выбрано";
  if (!picker || !file) return;

  const uploadedAt = appFormatLocalDateTime(new Date());
  const uploadDate = document.querySelector("[data-single-file-uploaded-at]");
  if (uploadDate) uploadDate.textContent = uploadedAt;
  const meta = picker.querySelector("[data-single-file-meta]");
  const metaTime = picker.querySelector("[data-single-file-meta-time]");
  if (metaTime) {
    metaTime.innerHTML = `<i class="bi bi-clock"></i> ${uploadedAt}`;
  } else if (meta) {
    meta.textContent = `${uploadedAt} · ${meta.dataset.singleFileOwner || "-"}`;
  }

  const preview = picker.querySelector("[data-single-file-preview]");
  if (!preview) return;
  if (preview.dataset.objectUrl) {
    URL.revokeObjectURL(preview.dataset.objectUrl);
  }
  const objectUrl = URL.createObjectURL(file);
  preview.dataset.objectUrl = objectUrl;
  preview.src = objectUrl;
  preview.alt = file.name;

  const lightboxButton = picker.querySelector("[data-lightbox-photo]");
  if (lightboxButton) {
    lightboxButton.dataset.src = objectUrl;
    lightboxButton.dataset.description = file.name;
    lightboxButton.dataset.meta = meta?.textContent?.trim() || uploadedAt;
  }
}

async function postBulkPhotoBatch(form, files, descriptions, startIndex) {
  const formData = new FormData();
  formData.append("csrfmiddlewaretoken", csrfToken(form));
  const folder = form.querySelector('[name="folder"]')?.value;
  const newFolder = form.querySelector('[name="new_folder"]')?.value?.trim();
  if (folder) formData.append("folder", folder);
  if (newFolder) formData.append("new_folder", newFolder);
  files.forEach((file, offset) => {
    formData.append("images", file, file.name);
    formData.append("descriptions", descriptions[startIndex + offset] || "");
  });
  const response = await fetch(form.getAttribute("hx-post") || form.action || window.location.href, {
    method: "POST",
    body: formData,
    headers: {
      "X-Bulk-Photo-Batch": "true",
      "X-CSRFToken": csrfToken(form),
      "X-Requested-With": "XMLHttpRequest",
    },
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

async function uploadBulkPhotos(form) {
  const input = form.querySelector("[data-bulk-photo-input]");
  const files = Array.from(input?.files || []);
  if (!files.length) {
    appShowToast("Выберите хотя бы одно изображение.", "warning");
    return;
  }
  const descriptions = Array.from(form.querySelectorAll("[data-bulk-description]")).map((textarea) => textarea.value);
  let uploaded = 0;
  let created = 0;
  let failed = 0;
  const errors = [];
  setBulkPhotoFormBusy(form, true);
  appSetLoading(true);
  try {
    for (let start = 0; start < files.length; start += BULK_PHOTO_BATCH_SIZE) {
      const batch = files.slice(start, start + BULK_PHOTO_BATCH_SIZE);
      setBulkUploadProgress(form, uploaded, files.length, `Отправка ${start + 1}-${Math.min(start + batch.length, files.length)} из ${files.length}`);
      const result = await postBulkPhotoBatch(form, batch, descriptions, start);
      uploaded += batch.length;
      created += Number(result.created || 0);
      failed += Number(result.failed || 0);
      if (Array.isArray(result.errors)) errors.push(...result.errors);
      setBulkUploadProgress(form, uploaded, files.length, `Загружено: ${created}. Ошибок: ${failed}.`);
    }
    const modal = bootstrap.Modal.getInstance(document.getElementById("modal-root"));
    if (modal) modal.hide();
    appShowToast(failed ? `Загружено: ${created}. Не загружено: ${failed}.` : `Фотографий загружено: ${created}.`, failed ? "warning" : "success");
    if (errors.length) console.warn("Bulk photo upload errors:", errors);
    const refreshUrl = form.dataset.bulkRefreshUrl;
    if (refreshUrl && window.htmx) {
      window.htmx.ajax("GET", refreshUrl, { target: "#workspace", swap: "innerHTML" });
    }
  } catch (error) {
    setBulkUploadProgress(form, uploaded, files.length, "Загрузка остановлена из-за ошибки.");
    appShowToast("Загрузка прервана. Попробуйте повторить или выбрать меньше файлов.", "danger");
    console.error(error);
  } finally {
    setBulkPhotoFormBusy(form, false);
    appSetLoading(false);
  }
}

function openBulkPhotoModal(dropzone, files) {
  pendingBulkPhotoFiles = Array.from(files).filter((file) => file.type.startsWith("image/"));
  if (!pendingBulkPhotoFiles.length || !window.htmx) return;
  const uploadUrl = dropzone.dataset.photoUploadUrl || dropzone.getAttribute("hx-get");
  if (!uploadUrl) return;
  window.htmx.ajax("GET", uploadUrl, { target: "#modal-content", swap: "innerHTML" });
}

function renderPendingBulkPhotoFiles(form) {
  renderBulkPhotoFiles(form, pendingBulkPhotoFiles);
  pendingBulkPhotoFiles = [];
}

function photoDropTarget(event) {
  const folder = event.target.closest(".folder-card[data-photo-upload-url]");
  return folder || event.target.closest("[data-photo-dropzone]");
}

function clearPhotoDragState() {
  document.querySelectorAll(".photo-browser.is-dragover, .folder-card.is-dragover").forEach((item) => item.classList.remove("is-dragover"));
}

window.PhotoUpload = {
  renderBulkPhotoFiles,
  renderPendingBulkPhotoFiles,
  removeBulkPhotoFile,
  updateSingleFilePicker,
  uploadBulkPhotos,
  openBulkPhotoModal,
  photoDropTarget,
  clearPhotoDragState,
};
