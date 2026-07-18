// Authentication forms and shared signed-in header interactions. Kept separate
// from app_events.js because these behaviours are needed on every page.
const USER_MENU_OPEN_DELAY_MS = 140;
const USER_MENU_CLOSE_DELAY_MS = 280;
const USER_MENU_CLOSE_ANIMATION_MS = 220;
const USER_MENU_HOVER_QUERY = "(min-width: 721px) and (hover: hover) and (pointer: fine)";

function initUserMenuHover() {
  const root = document.querySelector("[data-user-menu]");
  const toggle = root?.querySelector("[data-bs-toggle='dropdown']");
  const menu = root?.querySelector(".user-menu");
  if (!root || !toggle || !menu || typeof bootstrap === "undefined") return;

  const hoverQuery = window.matchMedia(USER_MENU_HOVER_QUERY);
  const dropdown = bootstrap.Dropdown.getOrCreateInstance(toggle);
  let openTimer = null;
  let closeTimer = null;
  let closeAnimationTimer = null;
  let closeRequiresPointerExit = false;
  let allowImmediateHide = false;

  function clearOpenTimer() {
    if (openTimer) window.clearTimeout(openTimer);
    openTimer = null;
  }

  function clearCloseTimer() {
    if (closeTimer) window.clearTimeout(closeTimer);
    closeTimer = null;
  }

  function cancelCloseAnimation() {
    if (closeAnimationTimer) window.clearTimeout(closeAnimationTimer);
    closeAnimationTimer = null;
    closeRequiresPointerExit = false;
    menu.classList.remove("is-closing");
  }

  function startCloseAnimation(requirePointerExit = false) {
    if (!toggle.classList.contains("show")) return;
    if (closeAnimationTimer) {
      if (!requirePointerExit) closeRequiresPointerExit = false;
      return;
    }
    closeRequiresPointerExit = requirePointerExit;
    menu.classList.add("is-closing");
    closeAnimationTimer = window.setTimeout(() => {
      closeAnimationTimer = null;
      if (closeRequiresPointerExit && root.matches(":hover")) {
        cancelCloseAnimation();
        return;
      }
      allowImmediateHide = true;
      dropdown.hide();
      allowImmediateHide = false;
      closeRequiresPointerExit = false;
      menu.classList.remove("is-closing");
    }, USER_MENU_CLOSE_ANIMATION_MS);
  }

  root.addEventListener("pointerenter", () => {
    if (!hoverQuery.matches) return;
    clearCloseTimer();
    cancelCloseAnimation();
    if (toggle.classList.contains("show")) return;
    clearOpenTimer();
    openTimer = window.setTimeout(() => {
      openTimer = null;
      if (hoverQuery.matches && root.matches(":hover")) dropdown.show();
    }, USER_MENU_OPEN_DELAY_MS);
  });

  root.addEventListener("pointerleave", () => {
    if (!hoverQuery.matches) return;
    clearOpenTimer();
    clearCloseTimer();
    closeTimer = window.setTimeout(() => {
      closeTimer = null;
      if (!hoverQuery.matches || root.matches(":hover") || !toggle.classList.contains("show")) return;
      startCloseAnimation(true);
    }, USER_MENU_CLOSE_DELAY_MS);
  });

  root.addEventListener("hide.bs.dropdown", (event) => {
    if (allowImmediateHide) return;
    event.preventDefault();
    clearCloseTimer();
    startCloseAnimation(false);
  });

  hoverQuery.addEventListener("change", () => {
    clearOpenTimer();
    clearCloseTimer();
    cancelCloseAnimation();
  });

  root.addEventListener("hidden.bs.dropdown", () => {
    cancelCloseAnimation();
    toggle.blur();
  });
}
document.addEventListener("input", (event) => {
  if (event.target.matches(".auth-ascii-input")) normalizeAuthInput(event.target);
});

document.addEventListener("beforeinput", (event) => {
  if (!event.target.matches(".auth-ascii-input") || !event.data) return;
  if (/[^\x21-\x7E]/.test(event.data)) event.preventDefault();
});

document.addEventListener("click", (event) => {
  const passwordToggle = event.target.closest("[data-password-toggle]");
  if (!passwordToggle) return;
  const input = document.getElementById(passwordToggle.getAttribute("aria-controls"));
  if (!input) return;
  const shouldShow = input.type === "password";
  input.type = shouldShow ? "text" : "password";
  passwordToggle.setAttribute("aria-label", shouldShow ? "Скрыть пароль" : "Показать пароль");
  passwordToggle.innerHTML = shouldShow ? '<i class="bi bi-eye-slash"></i>' : '<i class="bi bi-eye"></i>';
  input.focus();
});

document.addEventListener("DOMContentLoaded", initUserMenuHover);
