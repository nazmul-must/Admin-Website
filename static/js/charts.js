// Pro3AI chart styling: Inter, muted ticks, slate-200 grid lines.
Chart.defaults.font.family = "'Inter', sans-serif";
Chart.defaults.color = '#64748b';
Chart.defaults.borderColor = '#e2e8f0';

// Renders every <canvas data-chart="ID"> from the <script id="ID" type="application/json"> config.
function renderCharts(root) {
  root.querySelectorAll('canvas[data-chart]').forEach((el) => {
    if (el.chart) return;
    const config = JSON.parse(document.getElementById(el.dataset.chart).textContent);
    el.chart = new Chart(el, config);
  });
}

document.addEventListener('DOMContentLoaded', () => renderCharts(document));
document.addEventListener('htmx:afterSwap', (event) => renderCharts(event.target));
