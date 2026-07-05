/*
  tabs.js — shared ARIA tab-list wiring (#579 a11y + focus pass).
  ----------------------------------------------------------------------------
  coaching.js, dispatches.js, and story.js each build the same `.dx-tab` section
  switcher (Read / By Coach / Team / … or Chronicle / Podcast / Journal / …) but
  only toggled `aria-pressed`, which announces a set of independent toggle
  buttons rather than the single-choice tablist they actually are. This module
  applies the WAI-ARIA Tabs pattern (https://www.w3.org/WAI/ARIA/apg/patterns/tabs/)
  on top of markup the caller already owns:

    - role="tablist" on the container, role="tab" + aria-selected on each button,
      role="tabpanel" + aria-labelledby on the single content region they control.
    - Roving tabindex (only the selected tab is in the Tab order; arrow keys move
      focus within the tablist).
    - Left/Right/Up/Down/Home/End keyboard navigation, each move both re-focusing
      AND activating the tab (this is a small, content-light tablist — "automatic
      activation" per the APG, not "manual").

  This module does NOT own selection logic or rendering — the caller still
  decides what a tab click means (fetch, render, pushState, …). Call `markActiveTab`
  every time the caller updates which section is active (replacing the old
  `aria-pressed`/`is-active` loop); call `wireTabList` once, after the tab buttons
  exist, to attach the arrow-key handler.

  NOT wired into evidence.js (Data/Protocols doors' `.ev-tab` tablist) — that file
  is mid-split for #581 (router + per-door modules); re-audit its tabs once that
  lands, since editing it now would collide with the concurrent refactor.
*/

/**
 * Attach roving-tabindex + arrow-key navigation to an existing tablist.
 * Call once after the tab buttons are built (their DOM nodes may be replaced
 * later by re-running the caller's own build step — call this again if so).
 *
 * @param {HTMLElement} tabsEl - the tablist container (e.g. nav[data-dx-tabs]).
 * @param {(key: string) => void} onActivate - called with the tab's key when
 *   an arrow/Home/End move selects a new tab (click handling stays the caller's).
 * @param {{tabSelector?: string, keyAttr?: string}} [opts]
 */
export function wireTabList(tabsEl, onActivate, { tabSelector = ".dx-tab", keyAttr = "sec" } = {}) {
  if (!tabsEl || tabsEl.__tabsWired) return;
  tabsEl.__tabsWired = true;
  if (!tabsEl.hasAttribute("role")) tabsEl.setAttribute("role", "tablist");

  const tabs = () => Array.from(tabsEl.querySelectorAll(tabSelector));

  function focusAndActivate(idx, list) {
    const i = (idx + list.length) % list.length;
    list.forEach((t, j) => t.setAttribute("tabindex", j === i ? "0" : "-1"));
    list[i].focus();
    onActivate(list[i].dataset[keyAttr]);
  }

  tabsEl.addEventListener("keydown", (e) => {
    const list = tabs();
    const cur = list.indexOf(document.activeElement);
    if (cur < 0) return;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); focusAndActivate(cur + 1, list); }
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); focusAndActivate(cur - 1, list); }
    else if (e.key === "Home") { e.preventDefault(); focusAndActivate(0, list); }
    else if (e.key === "End") { e.preventDefault(); focusAndActivate(list.length - 1, list); }
  });
}

/**
 * Mark which tab is active: sets role="tab"/aria-selected/roving tabindex on
 * every tab button, and links the shared content panel with aria-labelledby
 * (+ role="tabpanel") so assistive tech announces which tab a panel belongs to.
 * Call this every time selection changes — it replaces the old
 * `.dx-tab.forEach(t => t.setAttribute("aria-pressed", ...))` loop.
 *
 * @param {HTMLElement} tabsEl
 * @param {HTMLElement|null} panelEl - the single content region the tabs control (may be null).
 * @param {string} activeKey
 * @param {{tabSelector?: string, keyAttr?: string}} [opts]
 */
export function markActiveTab(tabsEl, panelEl, activeKey, { tabSelector = ".dx-tab", keyAttr = "sec" } = {}) {
  if (!tabsEl) return;
  if (panelEl && !panelEl.id) panelEl.id = `tabpanel-${Math.random().toString(36).slice(2, 8)}`;
  if (!tabsEl.__tabsBaseId) tabsEl.__tabsBaseId = `tabs-${Math.random().toString(36).slice(2, 8)}`;
  let activeId = null;
  tabsEl.querySelectorAll(tabSelector).forEach((t, i) => {
    const on = t.dataset[keyAttr] === activeKey;
    if (!t.id) t.id = `${tabsEl.__tabsBaseId}-${i}`;
    t.setAttribute("role", "tab");
    t.setAttribute("aria-selected", String(on));
    t.setAttribute("tabindex", on ? "0" : "-1");
    t.classList.toggle("is-active", on);
    if (panelEl) t.setAttribute("aria-controls", panelEl.id);
    if (on) activeId = t.id;
  });
  if (panelEl && activeId) {
    panelEl.setAttribute("role", "tabpanel");
    panelEl.setAttribute("aria-labelledby", activeId);
    if (!panelEl.hasAttribute("tabindex")) panelEl.setAttribute("tabindex", "-1");
  }
}
