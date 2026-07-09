// Login/activation/password-change form UX. Kept separate from
// app_events.js (dashboard-only) because these pages never load that bundle.
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
