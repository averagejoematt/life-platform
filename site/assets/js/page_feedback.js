/*
  page_feedback.js — the reader form, site half (#4182, M3).
  ----------------------------------------------------------------------------
  "Did this page make sense?" — yes / partly / no, plus an optional ≤500-char "what were
  you looking for?". The form ships `hidden` in the canonical footer
  (scripts/v4_chrome.PAGE_FEEDBACK_FORM); this module un-hides it and POSTs
  {page, made_sense, looking_for} to /api/page_feedback through the shared postJSON.

  Honest by construction: only a 2xx says "Thanks — read weekly." A 404 (the endpoint
  not deployed yet), a 5xx, a 429 or a network failure (status 0) stays SILENT — the
  form simply stays as it was, never claiming a send that did not happen.
*/
import { postJSON } from "/assets/js/evidence_shared.js";

export const MAX_LOOKING_FOR = 500;
export const THANKS = "Thanks — read weekly.";

/** The request body — pure, so the test can pin it without a DOM. */
export function feedbackBody(pathname, madeSense, lookingFor) {
  const page = String(pathname || "/").split(/[?#]/)[0] || "/";
  const body = { page, made_sense: String(madeSense || "") };
  const text = String(lookingFor || "").trim().slice(0, MAX_LOOKING_FOR);
  body.looking_for = text;
  return body;
}

/** What the status line says for a response — "" means stay silent. */
export function statusFor(res) {
  return res && res.ok ? THANKS : "";
}

function wire(form) {
  form.hidden = false;
  const status = form.querySelector(".pf-status");
  const send = form.querySelector(".pf-send");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const choice = form.querySelector('input[name="made_sense"]:checked');
    if (!choice) return; // `required` on the radios lets the browser say so
    const area = form.querySelector('textarea[name="looking_for"]');
    if (send) send.disabled = true;
    const res = await postJSON("/api/page_feedback", feedbackBody(location.pathname, choice.value, area && area.value));
    const msg = statusFor(res);
    if (msg) {
      if (status) status.textContent = msg;
      form.querySelectorAll("input, textarea, button").forEach((el) => { el.disabled = true; });
    } else if (send) {
      send.disabled = false;
    }
  });
}

if (typeof document !== "undefined") {
  const start = () => { const f = document.querySelector("form.page-feedback"); if (f) wire(f); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
}
