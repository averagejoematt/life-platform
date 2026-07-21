// attribution.js — site-wide UTM capture, persisted across navigation (#1621).
//
// The realistic acquisition path is: land on `/` with `?utm_source=reddit`, browse
// three or four pages, subscribe later. By the time the subscribe form renders,
// `window.location.search` is clean — so a capture scoped to the subscribe page alone
// attributes almost nothing while appearing to work. This module is loaded from the
// canonical site footer (v4_chrome.site_footer), which every chrome-bearing page
// carries, so capture happens on FIRST landing anywhere on the site and survives
// navigation in sessionStorage until the form posts.
//
// First-write-wins by design: the landing that brought the visitor in is the
// attribution. A later internal navigation that happens to carry UTM params (or a
// second campaign link opened mid-session) must not overwrite the original referral.
//
// Values are normalized hard (lowercased, charset-restricted, length-capped) before
// storage. UTM values are attacker-controlled free text off the querystring; they are
// posted to the API and rendered into an owner-facing digest email, so they are
// treated as untrusted input at the boundary rather than at the sink.

export const STORAGE_KEY = "ajm_attr_v1";
export const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"];

// Campaign tokens are machine identifiers, not prose: lowercase alphanumerics plus
// `_ . -`. Anything else is dropped rather than escaped, which keeps arbitrary
// querystring content (including anything that could carry PII) out of storage
// entirely. 64 chars is well past any real campaign name.
const MAX_LEN = 64;
const ALLOWED = /[^a-z0-9_.-]+/g;

/** Normalize one UTM value to a safe machine token. Returns "" if nothing survives. */
export function normalize(value) {
  if (typeof value !== "string") return "";
  return value.trim().toLowerCase().replace(ALLOWED, "-").replace(/^-+|-+$/g, "").slice(0, MAX_LEN);
}

/**
 * Extract the normalized UTM params present in a querystring.
 * @param {string} search - e.g. "?utm_source=Reddit&utm_campaign=quantifiedself"
 * @returns {Object} only the keys actually present and non-empty after normalization.
 */
export function parseUtm(search) {
  const out = {};
  if (!search || typeof search !== "string") return out;
  let params;
  try {
    params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  } catch {
    return out;
  }
  for (const key of UTM_KEYS) {
    const normalized = normalize(params.get(key));
    if (normalized) out[key] = normalized;
  }
  return out;
}

/** Read the persisted attribution record, or null if none / unreadable. */
export function readAttribution(storage) {
  if (!storage) return null;
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Capture UTM params from a location onto sessionStorage. First-write-wins: if a
 * record already exists for this session, the existing one is kept and returned.
 * @returns {Object|null} the effective attribution record, or null if nothing captured.
 */
export function captureFromLocation(location, storage) {
  const existing = readAttribution(storage);
  if (existing) return existing;
  const utm = parseUtm(location && location.search);
  if (!Object.keys(utm).length) return null;
  const record = { ...utm, landing_path: safePath(location), captured_at: new Date().toISOString() };
  if (storage) {
    try {
      storage.setItem(STORAGE_KEY, JSON.stringify(record));
    } catch {
      // Private-mode / quota / disabled storage — capture degrades to nothing.
      // Attribution is a nice-to-have; a failed write must never break the page.
    }
  }
  return record;
}

/**
 * The landing PATH only, never the full URL — the querystring is exactly where
 * arbitrary third-party content (and potential PII) lives, and it is already
 * represented by the normalized UTM fields above.
 */
function safePath(location) {
  const path = location && typeof location.pathname === "string" ? location.pathname : "";
  return path.slice(0, MAX_LEN);
}

/**
 * The subset of the stored record that is posted to the subscribe API.
 * Returns a flat object of only non-empty utm_* fields — safe to spread into a
 * JSON body against the CURRENT deployed API, which ignores unknown fields.
 */
export function attributionPayload(storage) {
  const record = readAttribution(storage);
  const out = {};
  if (!record) return out;
  for (const key of UTM_KEYS) {
    if (record[key]) out[key] = record[key];
  }
  return out;
}

/**
 * The canonical outbound-link tagger — one function, so no surface hand-types a
 * UTM string. Existing query params are preserved; existing utm_* params on the
 * input URL win (an already-tagged link is left alone).
 * @param {string} url - absolute or root-relative.
 * @param {Object} tags - {source, medium, campaign}
 */
export function withUtm(url, tags) {
  if (!url || typeof url !== "string") return url;
  const base = typeof location !== "undefined" ? location.origin : "https://averagejoematt.com";
  let parsed;
  try {
    parsed = new URL(url, base);
  } catch {
    return url;
  }
  const mapping = { utm_source: tags && tags.source, utm_medium: tags && tags.medium, utm_campaign: tags && tags.campaign };
  for (const [key, value] of Object.entries(mapping)) {
    const normalized = normalize(value);
    if (normalized && !parsed.searchParams.has(key)) parsed.searchParams.set(key, normalized);
  }
  return url.startsWith("/") ? parsed.pathname + parsed.search + parsed.hash : parsed.href;
}

// ── Browser auto-init ────────────────────────────────────────────────────────
// Guarded so the module stays importable in node for unit tests. The global is
// how the subscribe page's classic (non-module) inline script reads the capture;
// it is deliberately a tiny read-only surface, not the module itself.
if (typeof window !== "undefined") {
  try {
    captureFromLocation(window.location, window.sessionStorage);
  } catch {
    /* never let attribution break a page render */
  }
  window.__ajmAttribution = {
    payload: () => {
      try {
        return attributionPayload(window.sessionStorage);
      } catch {
        return {};
      }
    },
    withUtm,
  };
}
