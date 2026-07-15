document.addEventListener("DOMContentLoaded", () => {
  if (typeof initCustomSelects === "function") initCustomSelects(document);

  const form = document.querySelector(".report-comparison-form");
  const metrics = form?.querySelector(".report-metrics");
  const comparison = form?.querySelector("#report-comparison");
  const chartLayout = form?.querySelector("#report-chart-layout");
  const chartLayoutField = form?.querySelector("[data-report-layout-field]");
  const printButton = document.querySelector("[data-report-print]");
  if (!form || !metrics) return;

  let originalPrintUrl = "";

  const useCleanPrintUrl = () => {
    if (!window.location.search || originalPrintUrl) return;
    originalPrintUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    window.history.replaceState(window.history.state, "", window.location.pathname);
  };

  const restoreReportUrl = () => {
    if (!originalPrintUrl) return;
    window.history.replaceState(window.history.state, "", originalPrintUrl);
    originalPrintUrl = "";
  };

  printButton?.addEventListener("click", () => {
    useCleanPrintUrl();
    window.print();
    restoreReportUrl();
  });
  window.addEventListener("beforeprint", useCleanPrintUrl);
  window.addEventListener("afterprint", restoreReportUrl);

  const syncLayoutField = () => {
    if (chartLayoutField) chartLayoutField.hidden = comparison?.value === "none";
  };

  comparison?.addEventListener("change", syncLayoutField);
  syncLayoutField();

  form.addEventListener("submit", (event) => {
    if (comparison?.value === "none" && chartLayout) chartLayout.value = "combined";
    if (metrics.querySelector("[data-admin-multiselect-input]:checked")) return;
    event.preventDefault();
    metrics.classList.add("has-error");
    metrics.querySelector(".admin-multiselect-trigger")?.focus();
  });

  metrics.addEventListener("change", () => metrics.classList.remove("has-error"));
});
