// Employee form helpers: generate a readable username from Russian full name.
(() => {
  const translitMap = {
    а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh", з: "z",
    и: "i", й: "i", к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r",
    с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "ts", ч: "ch", ш: "sh", щ: "shch",
    ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
  };

  function slugifyName(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .split("")
      .map((char) => translitMap[char] ?? char)
      .join("")
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
  }

  function existingUsernames() {
    const script = document.getElementById("employee-existing-usernames");
    if (!script) return new Set();
    try {
      const data = JSON.parse(script.textContent || "[]");
      return new Set(Array.isArray(data) ? data.map((item) => String(item).toLowerCase()) : []);
    } catch (error) {
      return new Set();
    }
  }

  function generatedUsername(lastName, firstName, middleName, takenUsernames) {
    const last = slugifyName(lastName);
    const first = slugifyName(firstName);
    const middle = slugifyName(middleName);
    if (!last) return "";

    const candidates = [last];
    if (first) candidates.push(`${last}_${first}`);
    if (first && middle) candidates.push(`${last}_${first}_${middle}`);

    const taken = takenUsernames || new Set();
    const available = candidates.find((candidate) => !taken.has(candidate));
    if (available) return available;

    const base = candidates[candidates.length - 1];
    let suffix = 2;
    while (taken.has(`${base}_${suffix}`)) suffix += 1;
    return `${base}_${suffix}`;
  }

  function initEmployeeUsernameForm() {
    const username = document.querySelector("[data-employee-username]");
    const lastName = document.querySelector("[data-employee-last-name]");
    const firstName = document.querySelector("[data-employee-first-name]");
    const middleName = document.querySelector("[data-employee-middle-name]");
    const autoFlag = document.querySelector('input[name="username_auto"]');
    if (!username || !lastName || !firstName || !middleName || !autoFlag) return;

    const takenUsernames = existingUsernames();
    let lastGenerated = username.value || "";
    const isAutoEnabled = () => ["True", "true", "1", "on"].includes(autoFlag.value);
    const markManual = () => {
      if (username.value !== lastGenerated) {
        autoFlag.value = "";
      }
    };
    const updateUsername = () => {
      if (!isAutoEnabled()) return;
      const next = generatedUsername(lastName.value, firstName.value, middleName.value, takenUsernames);
      username.value = next;
      lastGenerated = next;
    };

    [lastName, firstName, middleName].forEach((input) => input.addEventListener("input", updateUsername));
    username.addEventListener("input", markManual);
    updateUsername();
  }

  function initEmployeePermissionMatrix() {
    const syncGroupActions = (group) => {
      if (!group) return;
      group.querySelectorAll("[data-permission-select-all]").forEach((button) => {
        const kind = button.dataset.permissionSelectAll;
        const selector = kind === "write" ? "[data-permission-write]" : "[data-permission-read]";
        const inputs = [...group.querySelectorAll(selector)].filter((input) => !input.disabled);
        const allChecked = inputs.length > 0 && inputs.every((input) => input.checked);
        const label = button.querySelector("[data-permission-action-label]");
        const icon = button.querySelector("i");
        const selectLabel = kind === "write" ? "Вся запись" : "Всё чтение";
        const clearLabel = kind === "write" ? "Снять запись" : "Снять чтение";
        if (label) label.textContent = allChecked ? clearLabel : selectLabel;
        if (icon) icon.className = allChecked ? "bi bi-x-lg" : (kind === "write" ? "bi bi-pencil-square" : "bi bi-eye");
        button.classList.toggle("is-clear", allChecked);
        button.setAttribute("aria-pressed", String(allChecked));
      });
    };

    document.querySelectorAll("[data-permission-row]").forEach((row) => {
      const readInput = row.querySelector("[data-permission-read]");
      const writeInput = row.querySelector("[data-permission-write]");
      if (!readInput || !writeInput) return;
      writeInput.addEventListener("change", () => {
        if (writeInput.checked) readInput.checked = true;
        syncGroupActions(row.closest("[data-permission-matrix-group]"));
      });
      readInput.addEventListener("change", () => {
        if (!readInput.checked) writeInput.checked = false;
        syncGroupActions(row.closest("[data-permission-matrix-group]"));
      });
    });

    document.querySelectorAll("[data-permission-select-all]").forEach((button) => {
      button.addEventListener("click", () => {
        const group = button.closest("[data-permission-matrix-group]");
        if (!group || button.disabled) return;
        const kind = button.dataset.permissionSelectAll;
        const selector = kind === "write" ? "[data-permission-write]" : "[data-permission-read]";
        const inputs = [...group.querySelectorAll(selector)].filter((input) => !input.disabled);
        const shouldCheck = !inputs.length || !inputs.every((input) => input.checked);
        inputs.forEach((input) => { input.checked = shouldCheck; });
        if (kind === "write" && shouldCheck) {
          group.querySelectorAll("[data-permission-read]").forEach((input) => { input.checked = true; });
        }
        if (kind === "read" && !shouldCheck) {
          group.querySelectorAll("[data-permission-write]").forEach((input) => { input.checked = false; });
        }
        syncGroupActions(group);
      });
    });

    const roleInputs = document.querySelectorAll('input[name="role"]');
    const writeInputs = document.querySelectorAll("[data-permission-write]");
    const writeAllButtons = document.querySelectorAll("[data-permission-write-all]");
    const syncRolePermissions = () => {
      const selectedRole = document.querySelector('input[name="role"]:checked')?.value;
      const isObserver = selectedRole === "observer";
      writeInputs.forEach((input) => {
        input.disabled = isObserver;
        if (isObserver) input.checked = false;
      });
      writeAllButtons.forEach((button) => { button.disabled = isObserver; });
      document.querySelectorAll("[data-permission-matrix-group]").forEach(syncGroupActions);
    };
    roleInputs.forEach((input) => input.addEventListener("change", syncRolePermissions));
    syncRolePermissions();
  }

  document.addEventListener("DOMContentLoaded", () => {
    initEmployeeUsernameForm();
    initEmployeePermissionMatrix();
  });
})();
