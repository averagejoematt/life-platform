/*
  morning_note_box.js — the owner's four-word box on the cockpit's first screen (#4189 box 3).
  ----------------------------------------------------------------------------
  Two coaches asked for four words before the number: how he slept, how his body feels, his
  mood, and whether he FEELS recovered — typed before he opens Whoop. The write door is
  POST /api/morning_note (lambdas/web/site_api_social_note.py); it accepts a note only with the
  owner token for THAT Pacific day (content.ritual_link.sign_morning_note_token — site-api's one
  owner check). This module is the box that carries that token.

  OWNER ONLY, BY CONSTRUCTION. The box renders only when the page was opened from the owner's
  signed link: /cockpit/#note=<YYYY-MM-DD>.<32-hex token>, minted into his evening nudge email
  for the next morning (lambdas/emails/evening_nudge_lambda.py). A reader's URL carries no such
  fragment, so for a reader this module touches nothing — no element, no request, no hidden
  markup in the shell. The token rides in the FRAGMENT, which a browser never sends to the
  server (no CloudFront log, no Referer), and it is stripped from the address bar as soon as it
  is read, so a screenshot or a shared link of the page never carries it.

  Honest by construction: only a 2xx says "stored". A 409 says a note already exists for the
  day; a 403 says the link is not for today; a 400 repeats the door's own reason; anything else
  (5xx, 429, network) says it was NOT stored.
*/
import { postJSON } from "/assets/js/evidence_shared.js";

export const NOTE_ENDPOINT = "/api/morning_note";
export const WORD_FIELDS = ["sleep_word", "body_word", "mood_word"];
export const WORD_MAX_CHARS = 24; // coach/morning_note.py WORD_MAX_CHARS
const WORD_RE = /^[A-Za-z]+(?:[ -][A-Za-z]+)*$/; // coach/morning_note.py WORD_RE
const GRANT_RE = /(?:^#|&)note=(\d{4}-\d{2}-\d{2})\.([0-9a-f]{32})(?:&|$)/;

/** {date, token} from the owner's link fragment, or null for every other URL. */
export function parseOwnerGrant(hash) {
  const m = GRANT_RE.exec(String(hash || ""));
  return m ? { date: m[1], token: m[2] } : null;
}

/** The fragment with the grant removed ("" when nothing else was in it). */
export function stripGrant(hash) {
  const rest = String(hash || "").replace(/^#/, "").split("&").filter((p) => p && !p.startsWith("note="));
  return rest.length ? `#${rest.join("&")}` : "";
}

/** Today's date in Pacific time, YYYY-MM-DD (the door's day). */
export function pacificToday(now = new Date()) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

/** One word as the door will validate it: whitespace collapsed; "" when it would be refused. */
export function cleanWord(raw) {
  const w = String(raw == null ? "" : raw).split(/\s+/).filter(Boolean).join(" ");
  return w && w.length <= WORD_MAX_CHARS && WORD_RE.test(w) ? w : "";
}

/** The POST body, or {error} naming the first field the door would refuse. Pure. */
export function noteBody(values, grant) {
  const body = { date: grant.date, token: grant.token };
  for (const f of WORD_FIELDS) {
    const w = cleanWord(values && values[f]);
    if (!w) return { error: f };
    body[f] = w;
  }
  const felt = values && values.felt_recovered;
  if (felt !== true && felt !== false) return { error: "felt_recovered" };
  body.felt_recovered = felt;
  return body;
}

/** What the status line says for the door's response. */
export function statusFor(res) {
  if (res && res.ok) return "Stored — the coaches read it this morning.";
  const status = res ? res.status : 0;
  if (status === 409) return "A note is already stored for today.";
  if (status === 403) return "This link is not for today — open this morning's link.";
  if (status === 400) return `Not stored: ${(res.data && res.data.error) || "check the words"}.`;
  return "Not stored — try again in a minute.";
}

const LABELS = { sleep_word: "Sleep, in a word", body_word: "Body, in a word", mood_word: "Mood, in a word" };

function el(doc, tag, attrs, text) {
  const n = doc.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  if (text) n.textContent = text;
  return n;
}

/** Build the box (DOM API only — no innerHTML, nothing typed is ever parsed as markup). */
export function buildBox(doc, grant, today) {
  const form = el(doc, "form", { class: "morning-note", "aria-label": "Morning note — owner only" });
  form.appendChild(el(doc, "p", { class: "mn-kicker label" }, "Before the number — four words, owner only"));
  if (grant.date !== today) {
    form.appendChild(el(doc, "p", { class: "mn-status", role: "status" }, `This link was for ${grant.date}; today is ${today}.`));
    return form;
  }
  const row = el(doc, "div", { class: "mn-words" });
  for (const f of WORD_FIELDS) {
    const lab = el(doc, "label", { class: "mn-field" }, LABELS[f]);
    lab.appendChild(el(doc, "input", { name: f, type: "text", maxlength: String(WORD_MAX_CHARS), autocomplete: "off", autocapitalize: "none", required: "" }));
    row.appendChild(lab);
  }
  form.appendChild(row);
  const felt = el(doc, "fieldset", { class: "mn-felt" });
  felt.appendChild(el(doc, "legend", {}, "Do you feel recovered?"));
  for (const [v, t] of [["true", "Yes"], ["false", "No"]]) {
    const lab = el(doc, "label", { class: "mn-opt" });
    lab.appendChild(el(doc, "input", { type: "radio", name: "felt_recovered", value: v, required: "" }));
    lab.appendChild(doc.createTextNode(` ${t}`));
    felt.appendChild(lab);
  }
  form.appendChild(felt);
  form.appendChild(el(doc, "button", { class: "mn-send", type: "submit" }, "Store it"));
  form.appendChild(el(doc, "p", { class: "mn-status", role: "status", "aria-live": "polite" }));
  return form;
}

function readValues(form) {
  const v = {};
  for (const f of WORD_FIELDS) v[f] = (form.querySelector(`input[name="${f}"]`) || {}).value;
  const picked = form.querySelector('input[name="felt_recovered"]:checked');
  v.felt_recovered = picked ? picked.value === "true" : null;
  return v;
}

/**
 * Mount the box for the owner, or do nothing. Returns the form, or null (every reader).
 * `post` and `now` are injectable so the test drives the real submit path without a network.
 */
export function mountMorningNoteBox({ doc, loc, hist, anchor, post = postJSON, now = new Date() } = {}) {
  const grant = parseOwnerGrant(loc && loc.hash);
  if (!grant || !doc || !anchor) return null;
  if (hist && typeof hist.replaceState === "function") {
    hist.replaceState(hist.state, "", `${loc.pathname || ""}${loc.search || ""}${stripGrant(loc.hash)}`);
  }
  const form = buildBox(doc, grant, pacificToday(now));
  anchor.insertAdjacentElement("beforebegin", form);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const status = form.querySelector(".mn-status");
    const body = noteBody(readValues(form), grant);
    if (body.error) {
      if (status) status.textContent = body.error === "felt_recovered" ? "Pick yes or no." : `${LABELS[body.error]}: letters, spaces or hyphens, up to ${WORD_MAX_CHARS}.`;
      return;
    }
    const send = form.querySelector(".mn-send");
    if (send) send.disabled = true;
    const res = await post(NOTE_ENDPOINT, body);
    if (status) status.textContent = statusFor(res);
    if (res && (res.ok || res.status === 409)) form.querySelectorAll("input, button").forEach((n) => { n.disabled = true; });
    else if (send) send.disabled = false;
  });
  return form;
}
