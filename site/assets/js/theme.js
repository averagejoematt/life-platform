/* theme.js — one theme toggle for the whole site (#577).
 *
 * Replaces six near-identical wireTheme() blocks (cockpit/evidence/dispatches/
 * coaching/mind/story) with a single source of truth: reads/writes
 * localStorage["ajm-theme"], applies documentElement.dataset.theme, keeps
 * <meta name="theme-color"> honest to the active theme, and wires any
 * .theme-toggle in scope. Uses a View Transition when the browser supports one
 * and reduced-motion is off — the same cross-fade the cockpit toggle always had,
 * now everywhere.
 *
 * The inline pre-paint boot script in each shell stays as-is — it must run
 * before first paint to avoid a light/dark flash, and this module loads async.
 */
const KEY = "ajm-theme";

function activeTheme() {
  return (
    document.documentElement.dataset.theme ||
    (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark")
  );
}

/* Keep the address-bar / PWA chrome color matched to the real page background.
 * The shells ship media-split <meta name="theme-color"> pairs that only track the
 * OS scheme; once the user picks a theme explicitly we own a single managed meta
 * (no media attr, appended last → wins) so the manual choice sticks, and drop it
 * when they fall back to system so the media pair takes over again. */
function syncThemeColor() {
  const explicit = document.documentElement.dataset.theme;
  let meta = document.getElementById("theme-color-active");
  if (!explicit) {
    if (meta) meta.remove();
    return;
  }
  if (!meta) {
    meta = document.createElement("meta");
    meta.name = "theme-color";
    meta.id = "theme-color-active";
    document.head.appendChild(meta);
  }
  const page = getComputedStyle(document.documentElement).getPropertyValue("--page").trim();
  if (page) meta.setAttribute("content", page);
}

/* Expose the toggle's current state to assistive tech (#1250). Screen-reader
 * users need name/role/value on the control: aria-pressed=true means dark is
 * active, and the accessible name tells them what the click will do next.
 * Runs on every apply — boot (initTheme) and each toggle — so the announced
 * state never drifts from documentElement.dataset.theme. */
function syncToggleState(root = document) {
  const dark = activeTheme() !== "light";
  const label = dark ? "Switch to light theme" : "Switch to dark theme";
  root.querySelectorAll(".theme-toggle").forEach((btn) => {
    btn.setAttribute("aria-pressed", dark ? "true" : "false");
    btn.setAttribute("aria-label", label);
  });
}

function setTheme(next) {
  const apply = () => {
    document.documentElement.dataset.theme = next;
    syncThemeColor();
    syncToggleState();
  };
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    document.startViewTransition(apply);
  } else {
    apply();
  }
  try {
    localStorage.setItem(KEY, next);
  } catch (e) {}
}

/* Flip light↔dark from whatever is currently active (explicit or system). */
export function toggleTheme() {
  setTheme(activeTheme() === "light" ? "dark" : "light");
}

/* Wire every .theme-toggle within `root` (default: document) and align the
 * theme-color meta to the booted theme. Idempotent per button via a data flag,
 * so re-initialising after a re-render never double-binds. */
export function initTheme(root = document) {
  syncThemeColor();
  syncToggleState(root);
  root.querySelectorAll(".theme-toggle").forEach((btn) => {
    if (btn.dataset.themeWired) return;
    btn.dataset.themeWired = "1";
    btn.addEventListener("click", toggleTheme);
  });
}
