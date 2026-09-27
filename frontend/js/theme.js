const STORAGE_KEY = "ari-emonio-viewer-theme";
const THEMES = ["dark", "light", "instrument"];
const LABELS = { dark: "DARK", light: "LIGHT", instrument: "INSTRUMENT" };

export function currentTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (THEMES.includes(stored)) return stored;
  } catch {
    /* storage unavailable: fall through to default */
  }
  return THEMES[0];
}

export function nextTheme(theme) {
  return THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
}

export function applyTheme(theme) {
  const resolved = THEMES.includes(theme) ? theme : THEMES[0];
  document.documentElement.dataset.theme = resolved;
  try {
    localStorage.setItem(STORAGE_KEY, resolved);
  } catch {
    /* storage unavailable: theme still applies for this session */
  }
  const button = document.getElementById("theme-toggle");
  if (button) {
    const label = button.querySelector("#theme-toggle-state");
    if (label) label.textContent = LABELS[resolved];
    button.setAttribute("aria-pressed", String(resolved !== THEMES[0]));
  }
  return resolved;
}

export function initializeThemeToggle() {
  if (globalThis.__ariThemeToggleInitialized) return;
  globalThis.__ariThemeToggleInitialized = true;
  applyTheme(currentTheme());
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    applyTheme(nextTheme(currentTheme()));
  });
}
