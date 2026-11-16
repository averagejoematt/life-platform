// "Your call beside the coaches" (#6088, #6114) — the island, built DARK: it reaches a page only through
// readerCallIntegration()'s injectScript on a WEB_READERCALL=1 build, and does nothing on a page without the control.
// Vanilla, no dependency, same origin (CSP connect-src 'self'), no cookie and no storage: the server's per-reader
// marker remembers a call, and a reload asks again. The server decides what may be shown: while a call is open no
// count reaches this script at all.
import { NOT_OPEN, UNREAD, closedSentence, coachLine, gradedSentence, labelOf, openSentence, splitRows, splitSentence } from "../lib/readercall_view.js";

const MIN_WAIT_MS = 2500; // the server refuses a call whose token is under 2 s old; a quick tap simply waits

function el(tag, attrs = {}, text = null) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== null) n.textContent = text;
  return n;
}

function splitList(choices, readerCalls) {
  const ul = el("ul", { class: "rows", style: "font-size:13px;list-style:none;padding:0;margin:0" });
  for (const r of splitRows(choices, readerCalls)) {
    const li = el("li");
    li.append(el("span", {}, r.label), el("span", { class: "mono" }, r.pct === null ? "0" : `${r.count} · ${r.pct}%`));
    ul.append(li);
  }
  return ul;
}

async function getView(api, call) {
  const r = await fetch(`${api}?call=${encodeURIComponent(call)}`, { cache: "no-store", headers: { Accept: "application/json" } });
  const body = await r.json().catch(() => null);
  return { ok: r.ok, status: r.status, body };
}

function para(text, style = "font-size:13px", attrs = {}) {
  return el("p", { style, ...attrs }, text);
}

function renderOpen(root, body, view, fetchedAt) {
  body.replaceChildren();
  body.append(para(view.question, "font-size:15px;font-weight:700;line-height:1.4"));
  if (view.your_call) {
    body.append(para(openSentence(view), "font-size:14px;line-height:1.5", { role: "status" }));
    return;
  }
  const fs = el("fieldset", { style: "border:0;padding:0;margin:0;display:flex;flex-direction:column;gap:10px" });
  fs.append(el("legend", { style: "font-size:13px;margin-bottom:6px" }, "Your call:"));
  const row = el("div", { style: "display:flex;flex-wrap:wrap;gap:8px" });
  const status = para(openSentence(view), "font-size:13px", { role: "status" });
  for (const c of view.choices) {
    const b = el("button", { type: "button", class: "btn ghost sm", "data-choice": c.id }, c.label);
    b.addEventListener("click", () => tap(root, body, view, c.id, fetchedAt, row, status));
    row.append(b);
  }
  fs.append(row);
  body.append(fs, status);
}

async function tap(root, body, view, choice, fetchedAt, row, status) {
  for (const b of row.querySelectorAll("button")) b.disabled = true;
  status.textContent = "Recording your call…";
  const wait = MIN_WAIT_MS - (Date.now() - fetchedAt);
  if (wait > 0) await new Promise((res) => setTimeout(res, wait));
  const hp = root.querySelector("[data-rc-hp]");
  let r;
  try {
    r = await fetch(root.dataset.api, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ call: view.call, choice, token: view.token, hp: hp ? hp.value : "" }),
    });
  } catch {
    r = null;
  }
  const out = r ? await r.json().catch(() => null) : null;
  if (r && r.ok && out && out.recorded) {
    body.replaceChildren(
      para(view.question, "font-size:15px;font-weight:700;line-height:1.4"),
      para(openSentence({ ...view, your_call: out.your_call }), "font-size:14px;line-height:1.5", { role: "status" }),
    );
    return;
  }
  status.textContent =
    r && r.status === 409
      ? "Calls on this one are closed, or you have already made yours."
      : r && r.status === 403
        ? "This page has been open a while. Reload it to make your call."
        : "Your call was not recorded. Please try again later.";
  for (const b of row.querySelectorAll("button")) b.disabled = Boolean(r && r.status === 409);
}

function renderClosed(root, body, view) {
  body.replaceChildren(
    para(view.question, "font-size:15px;font-weight:700;line-height:1.4"),
    para(closedSentence(view), "font-size:14px;line-height:1.5"),
    para(splitSentence(view.choices, view.reader_calls)),
  );
  if (view.reader_calls && view.reader_calls.total) body.append(splitList(view.choices, view.reader_calls));
}

function renderGraded(root, body, view) {
  const coach = root.querySelector("[data-rc-coach]");
  if (coach) coach.textContent = coachLine(view);
  const readers = root.querySelector("[data-rc-readers]");
  const total = (view.reader_calls && view.reader_calls.total) || 0;
  if (readers) readers.textContent = total ? `${total} ${total === 1 ? "call" : "calls"}` : "none made";
  const mine = labelOf(view.choices, view.your_call);
  body.replaceChildren(el("span", {}, `${mine ? `You called: ${mine}. ` : ""}${gradedSentence(view)}`));
  if (total) body.after(splitList(view.choices, view.reader_calls));
}

export async function mount(root) {
  const body = root.querySelector("[data-rc-body]");
  if (!body) return;
  let res;
  try {
    res = await getView(root.dataset.api, root.dataset.call);
  } catch {
    res = { ok: false, status: 0, body: null };
  }
  const fetchedAt = Date.now();
  if (!res.ok || !res.body || !res.body.available) {
    body.replaceChildren(para(res.status === 0 ? UNREAD : NOT_OPEN, "font-size:13px", { class: "muted" }));
    return;
  }
  const view = res.body;
  if (view.graded) renderGraded(root, body, view);
  else if (view.open) renderOpen(root, body, view, fetchedAt);
  else renderClosed(root, body, view);
}

export async function mountList(root) {
  const none = root.querySelector("[data-rc-none]");
  let open = 0;
  for (const li of root.querySelectorAll("[data-rc-item]")) {
    try {
      const res = await getView(root.dataset.api, li.dataset.rcItem);
      if (res.ok && res.body && res.body.open) {
        const slot = li.querySelector("[data-rc-closes]");
        if (slot) slot.textContent = res.body.your_call ? `you called · closes ${res.body.closes_on_words}` : `open until ${res.body.closes_on_words}`;
        li.style.display = "";
        open += 1;
      }
    } catch {
      /* an unread call simply stays hidden */
    }
  }
  if (none) none.textContent = open ? "" : "No coach call is open for reader calls right now. New calls open when a coach makes one.";
  if (none && open) none.style.display = "none";
}

if (typeof document !== "undefined") {
  for (const root of document.querySelectorAll('[data-readercall="open"],[data-readercall="graded"]')) mount(root);
  for (const root of document.querySelectorAll('[data-readercall="list"]')) mountList(root);
}
