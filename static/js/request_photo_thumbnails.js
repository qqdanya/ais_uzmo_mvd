(function () {
  const GROUP_SELECTOR = "[data-request-photo-thumbnails]";
  const ITEM_SELECTOR = "[data-request-photo-thumbnail-item]";
  const MORE_SELECTOR = "[data-request-photo-more]";
  const DEFAULT_GAP = 6;
  const DEFAULT_THUMB_SIZE = 60;

  function numericCssValue(value, fallback) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function setHidden(element, hidden) {
    if (!element) {
      return;
    }
    element.hidden = hidden;
    element.classList.toggle("request-photo-thumbnail-hidden", hidden);
  }

  function safeGroupWidth(group) {
    const width = group.clientWidth || group.getBoundingClientRect().width;
    if (!width) {
      return null;
    }
    return width;
  }

  function visibleCapacity(group, sampleItem, moreButton) {
    const groupWidth = safeGroupWidth(group);
    if (!groupWidth) {
      return null;
    }
    const groupStyles = window.getComputedStyle(group);
    const gap = numericCssValue(groupStyles.columnGap || groupStyles.gap, DEFAULT_GAP);
    const itemWidth = sampleItem.getBoundingClientRect().width || sampleItem.offsetWidth || DEFAULT_THUMB_SIZE;
    const moreWidth = moreButton ? (moreButton.getBoundingClientRect().width || moreButton.offsetWidth || itemWidth) : itemWidth;
    const singleItemSpace = itemWidth + gap;
    if (!singleItemSpace) {
      return null;
    }
    const fullCapacity = Math.max(1, Math.floor((groupWidth + gap) / singleItemSpace));
    const capacityWithMore = Math.max(1, Math.floor((groupWidth - moreWidth) / singleItemSpace));
    return { fullCapacity, capacityWithMore };
  }

  function updateGroup(group) {
    const items = Array.from(group.querySelectorAll(ITEM_SELECTOR));
    const moreButton = group.querySelector(MORE_SELECTOR);
    if (!items.length) {
      setHidden(moreButton, true);
      return;
    }

    const capacity = visibleCapacity(group, items[0], moreButton);
    if (!capacity) {
      return;
    }

    const total = items.length;
    const needsMore = total > capacity.fullCapacity;
    const visibleCount = needsMore
      ? Math.max(1, Math.min(total - 1, capacity.capacityWithMore))
      : Math.min(total, capacity.fullCapacity);

    items.forEach((item, index) => setHidden(item, index >= visibleCount));

    if (moreButton) {
      const hiddenCount = total - visibleCount;
      moreButton.textContent = `+${hiddenCount}`;
      moreButton.setAttribute("aria-label", `Показать все фотографии заявки, скрыто ${hiddenCount}`);
      setHidden(moreButton, hiddenCount <= 0);
    }
  }

  function updateAll(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll(GROUP_SELECTOR).forEach(updateGroup);
  }

  const observer = "ResizeObserver" in window
    ? new ResizeObserver((entries) => entries.forEach((entry) => updateGroup(entry.target)))
    : null;

  function observeAll(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll(GROUP_SELECTOR).forEach((group) => {
      if (observer) {
        observer.observe(group);
      }
      updateGroup(group);
    });
  }

  document.addEventListener("DOMContentLoaded", () => observeAll(document));
  document.body.addEventListener("htmx:afterSwap", (event) => observeAll(event.target || document));
  document.body.addEventListener("shown.bs.modal", (event) => observeAll(event.target || document));
  window.addEventListener("resize", () => updateAll(document));
})();
