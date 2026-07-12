function selectedOption(select) {
  return select.options[select.selectedIndex] || select.querySelector("option");
}

function syncCustomSelect(select) {
  const wrapper = select.nextElementSibling;
  if (!wrapper?.matches?.("[data-custom-select]")) return;
  const current = selectedOption(select);
  wrapper.querySelector("[data-custom-select-value]").textContent = current?.textContent || "";
  wrapper.querySelectorAll("[data-custom-select-option]").forEach((option) => {
    const isSelected = option.dataset.value === select.value;
    option.classList.toggle("is-selected", isSelected);
    option.setAttribute("aria-selected", String(isSelected));
  });
  wrapper.classList.toggle("is-disabled", select.disabled);
  wrapper.querySelector("[data-custom-select-trigger]").disabled = select.disabled;
}

function closeCustomSelects(except = null) {
  document.querySelectorAll("[data-custom-select].is-open").forEach((wrapper) => {
    if (wrapper === except) return;
    wrapper.classList.remove("is-open");
    wrapper.querySelector("[data-custom-select-trigger]")?.setAttribute("aria-expanded", "false");
  });
}

function openCustomSelect(wrapper) {
  if (wrapper.classList.contains("is-disabled")) return;
  closeCustomSelects(wrapper);
  wrapper.classList.add("is-open");
  wrapper.querySelector("[data-custom-select-trigger]")?.setAttribute("aria-expanded", "true");
}

function toggleCustomSelect(wrapper) {
  if (wrapper.classList.contains("is-open")) {
    closeCustomSelects();
  } else {
    openCustomSelect(wrapper);
  }
}

function chooseCustomSelectOption(option) {
  if (option.disabled || option.getAttribute("aria-disabled") === "true") return;
  const wrapper = option.closest("[data-custom-select]");
  const select = wrapper?.previousElementSibling;
  if (!select?.matches?.("select")) return;
  select.value = option.dataset.value;
  syncCustomSelect(select);
  closeCustomSelects();
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function initCustomSelects(scope = document) {
  const selects = scope.matches?.("select.form-select:not([data-native-select])")
    ? [scope]
    : Array.from(scope.querySelectorAll("select.form-select:not([data-native-select])"));
  selects.forEach((select) => {
    if (select.nextElementSibling?.matches?.("[data-custom-select]")) {
      select.dataset.nativeSelect = "true";
      select.classList.add("custom-select-native");
      syncCustomSelect(select);
      return;
    }
    select.dataset.nativeSelect = "true";
    select.classList.add("custom-select-native");
    const wrapper = document.createElement("div");
    wrapper.className = `custom-select${select.classList.contains("form-select-sm") ? " custom-select-sm" : ""}`;
    wrapper.dataset.customSelect = "true";
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "custom-select-trigger";
    trigger.dataset.customSelectTrigger = "true";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    if (select.getAttribute("aria-label")) {
      trigger.setAttribute("aria-label", select.getAttribute("aria-label"));
    }
    const value = document.createElement("span");
    value.className = "custom-select-value";
    value.dataset.customSelectValue = "true";
    const leadingIconClass = select.dataset.customSelectIcon;
    if (leadingIconClass) {
      const leadingIcon = document.createElement("i");
      leadingIcon.className = `bi ${leadingIconClass} custom-select-leading-icon`;
      leadingIcon.setAttribute("aria-hidden", "true");
      trigger.append(leadingIcon);
    }
    const icon = document.createElement("i");
    icon.className = "bi bi-chevron-down";
    trigger.append(value, icon);

    const menu = document.createElement("div");
    menu.className = "custom-select-menu";
    menu.setAttribute("role", "listbox");
    Array.from(select.options).forEach((selectOption) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "custom-select-option";
      option.dataset.customSelectOption = "true";
      option.dataset.value = selectOption.value;
      option.textContent = selectOption.textContent;
      option.setAttribute("role", "option");
      if (selectOption.disabled) {
        option.disabled = true;
        option.setAttribute("aria-disabled", "true");
      }
      menu.append(option);
    });
    wrapper.append(trigger, menu);
    select.after(wrapper);
    select.addEventListener("change", () => syncCustomSelect(select));
    syncCustomSelect(select);
  });
}


function handleCustomSelectClick(event) {
  const customSelectTrigger = event.target.closest("[data-custom-select-trigger]");
  if (customSelectTrigger) {
    toggleCustomSelect(customSelectTrigger.closest("[data-custom-select]"));
    return;
  }

  const customSelectOption = event.target.closest("[data-custom-select-option]");
  if (customSelectOption) {
    chooseCustomSelectOption(customSelectOption);
    return;
  }

  if (!event.target.closest("[data-custom-select]")) closeCustomSelects();
}

function handleCustomSelectKeydown(event) {
  const trigger = event.target.closest("[data-custom-select-trigger]");
  if (trigger && ["Enter", " ", "ArrowDown"].includes(event.key)) {
    event.preventDefault();
    openCustomSelect(trigger.closest("[data-custom-select]"));
    return;
  }
  if (event.key === "Escape") {
    closeCustomSelects();
  }
}

document.addEventListener("click", handleCustomSelectClick);
document.addEventListener("keydown", handleCustomSelectKeydown);
