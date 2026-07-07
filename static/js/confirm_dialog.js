// Universal custom confirmation dialog for dangerous form actions.
const ConfirmDialog = (() => {
  let activeElement = null;
  let pendingForm = null;
  let pendingSubmitter = null;

  function ensureConfirmDialog() {
    let modal = document.getElementById("app-confirm-dialog");
    if (modal) return modal;

    modal = document.createElement("div");
    modal.id = "app-confirm-dialog";
    modal.className = "modal fade app-confirm-dialog";
    modal.tabIndex = -1;
    modal.setAttribute("aria-hidden", "true");
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content app-confirm-content">
          <div class="modal-header app-confirm-header">
            <div class="app-confirm-title-wrap">
              <span class="app-confirm-icon" data-confirm-icon><i class="bi bi-exclamation-triangle"></i></span>
              <h5 class="modal-title" data-confirm-title>Подтвердите действие</h5>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Закрыть"></button>
          </div>
          <div class="modal-body app-confirm-body">
            <p data-confirm-message></p>
            <div class="app-confirm-details d-none" data-confirm-details></div>
          </div>
          <div class="modal-footer app-confirm-footer">
            <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal" data-confirm-cancel>Отмена</button>
            <button type="button" class="btn btn-danger" data-confirm-accept>Подтвердить</button>
          </div>
        </div>
      </div>
    `;
    document.body.append(modal);
    modal.addEventListener("hidden.bs.modal", () => {
      pendingForm = null;
      pendingSubmitter = null;
      if (activeElement && typeof activeElement.focus === "function") activeElement.focus();
      activeElement = null;
    });
    modal.querySelector("[data-confirm-accept]").addEventListener("click", () => {
      const form = pendingForm;
      const submitter = pendingSubmitter;
      pendingForm = null;
      pendingSubmitter = null;
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      if (!form) return;
      form.dataset.confirmAccepted = "true";
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit(submitter || undefined);
      } else {
        form.submit();
      }
    });
    return modal;
  }

  function renderDetails(detailsElement, details) {
    detailsElement.classList.toggle("d-none", !details);
    detailsElement.textContent = details || "";
  }

  function applyVariant(modal, variant) {
    const icon = modal.querySelector("[data-confirm-icon]");
    const accept = modal.querySelector("[data-confirm-accept]");
    icon.className = `app-confirm-icon is-${variant}`;
    accept.className = `btn btn-${variant === "danger" ? "danger" : variant === "warning" ? "warning" : "primary"}`;
  }

  function open(options = {}) {
    const modal = ensureConfirmDialog();
    const variant = options.variant || "danger";
    modal.querySelector("[data-confirm-title]").textContent = options.title || "Подтвердите действие";
    modal.querySelector("[data-confirm-message]").textContent = options.message || "Вы уверены, что хотите выполнить это действие?";
    modal.querySelector("[data-confirm-cancel]").textContent = options.cancelLabel || "Отмена";
    modal.querySelector("[data-confirm-accept]").textContent = options.confirmLabel || "Подтвердить";
    renderDetails(modal.querySelector("[data-confirm-details]"), options.details || "");
    applyVariant(modal, variant);
    activeElement = document.activeElement;
    bootstrap.Modal.getOrCreateInstance(modal, { backdrop: "static", keyboard: true }).show();
  }

  function confirmForm(form, submitter) {
    pendingForm = form;
    pendingSubmitter = submitter || null;
    open({
      title: form.dataset.confirmTitle,
      message: form.dataset.confirmMessage,
      details: form.dataset.confirmDetails,
      confirmLabel: form.dataset.confirmConfirmLabel,
      cancelLabel: form.dataset.confirmCancelLabel,
      variant: form.dataset.confirmVariant || "danger",
    });
  }

  function handleSubmit(event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (!form.dataset.confirmMessage) return;
    if (form.dataset.confirmAccepted === "true") {
      delete form.dataset.confirmAccepted;
      return;
    }
    event.preventDefault();
    confirmForm(form, event.submitter);
  }

  function register() {
    document.addEventListener("submit", handleSubmit, true);
  }

  return { open, register };
})();

ConfirmDialog.register();
window.ConfirmDialog = ConfirmDialog;
