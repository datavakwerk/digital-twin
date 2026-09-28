// Colour scheme. By default the chat follows the OS (prefers-color-scheme).
// Embedded via widget.js, the host site can pin it to its own light/dark
// switch: ?theme= sets the initial scheme and "ask-ruud:theme" messages from
// the parent follow later changes. index.css keys off <html data-theme>.

function applyTheme(theme: unknown) {
  const root = document.documentElement;
  if (theme === "light" || theme === "dark") root.dataset.theme = theme;
  else delete root.dataset.theme; // back to following the OS
}

export function initTheme() {
  applyTheme(new URLSearchParams(window.location.search).get("theme"));

  if (window.parent === window) return;
  window.addEventListener("message", (event) => {
    // Any site may embed us (within frame-ancestors), so the parent's origin
    // isn't known here; the message can only flip the colour scheme.
    if (event.source !== window.parent) return;
    if (event.data?.type === "ask-ruud:theme") applyTheme(event.data.theme);
  });
}
