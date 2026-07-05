// TMC product suggestions for request forms.
var tmcProductSuggestTimers = new WeakMap();

function closeTmcProductSuggestions(field) {
  const box = field?.querySelector("[data-tmc-product-suggestions]");
  if (!box) return;
  box.hidden = true;
  box.innerHTML = "";
}

function closeAllTmcProductSuggestions(exceptField = null) {
  document.querySelectorAll("[data-tmc-product-field]").forEach((field) => {
    if (field !== exceptField) closeTmcProductSuggestions(field);
  });
}

function renderTmcProductSuggestions(input, results) {
  const field = input.closest("[data-tmc-product-field]");
  const box = field?.querySelector("[data-tmc-product-suggestions]");
  if (!field || !box) return;
  box.innerHTML = "";
  if (!results.length) {
    closeTmcProductSuggestions(field);
    return;
  }
  results.forEach((product) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tmc-product-suggestion";
    button.dataset.tmcProductSuggestion = "true";
    button.dataset.productId = product.id;
    button.dataset.productName = product.name;
    button.dataset.productUnit = product.unit || "шт.";
    button.innerHTML = `<span>${product.name}</span><small>${product.unit || "шт."}</small>`;
    box.append(button);
  });
  box.hidden = false;
}

function requestTmcProductSuggestions(input) {
  const field = input.closest("[data-tmc-product-field]");
  if (!field) return;
  field.querySelector("[data-tmc-product-id]").value = "";
  const query = input.value.trim();
  window.clearTimeout(tmcProductSuggestTimers.get(input));
  if (query.length < 2) {
    closeTmcProductSuggestions(field);
    return;
  }
  const timer = window.setTimeout(async () => {
    try {
      const url = `${input.dataset.suggestUrl}?q=${encodeURIComponent(query)}`;
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok || input.value.trim() !== query) return;
      const data = await response.json();
      renderTmcProductSuggestions(input, data.results || []);
    } catch {
      closeTmcProductSuggestions(field);
    }
  }, 250);
  tmcProductSuggestTimers.set(input, timer);
}

function chooseTmcProductSuggestion(button) {
  const field = button.closest("[data-tmc-product-field]");
  const row = button.closest("[data-tmc-item-row]");
  if (!field || !row) return;
  field.querySelector("[data-tmc-product-id]").value = button.dataset.productId || "";
  field.querySelector("[data-tmc-product-input]").value = button.dataset.productName || "";
  const unitInput = row.querySelector('[name="item_unit"]');
  if (unitInput && button.dataset.productUnit) unitInput.value = button.dataset.productUnit;
  closeTmcProductSuggestions(field);
}

window.closeTmcProductSuggestions = closeTmcProductSuggestions;
window.closeAllTmcProductSuggestions = closeAllTmcProductSuggestions;
window.renderTmcProductSuggestions = renderTmcProductSuggestions;
window.requestTmcProductSuggestions = requestTmcProductSuggestions;
window.chooseTmcProductSuggestion = chooseTmcProductSuggestion;
window.TmcProducts = {
  closeTmcProductSuggestions,
  closeAllTmcProductSuggestions,
  renderTmcProductSuggestions,
  requestTmcProductSuggestions,
  chooseTmcProductSuggestion,
};
