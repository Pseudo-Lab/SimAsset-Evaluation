// Apply the saved palette before the stylesheet paints, without rebuilding the review form.
(() => {
  const key = 'simasset-theme';
  const choices = new Set(['light', 'dark', 'system']);
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  const normalize = value => choices.has(value) ? value : 'dark';
  let preference = 'dark';
  try { preference = normalize(localStorage.getItem(key)); } catch { /* Storage may be blocked. */ }

  function apply() {
    const theme = preference === 'system' ? (system.matches ? 'dark' : 'light') : preference;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    const select = document.getElementById('theme');
    if (select) select.value = preference;
    document.querySelectorAll('[data-theme-link]').forEach(link => {
      const url = new URL(link.href);
      url.searchParams.set('theme', theme);
      link.href = url.href;
    });
  }

  apply();
  document.addEventListener('DOMContentLoaded', () => {
    apply();
    document.getElementById('theme').addEventListener('change', event => {
      preference = normalize(event.target.value);
      try { localStorage.setItem(key, preference); } catch { /* Keep the current page usable. */ }
      apply();
    });
  });
  system.addEventListener('change', () => { if (preference === 'system') apply(); });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) {
      preference = normalize(event.newValue);
      apply();
    }
  });
})();
