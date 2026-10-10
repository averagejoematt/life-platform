// tests/js/morning_note_box_4189.test.mjs — the owner's four-word box (#4189 box 3).
// Owner only by construction: no signed #note=<day>.<token> fragment -> nothing is built, nothing
// is posted. With the grant: the box mounts above the hero, the token leaves the address bar,
// and the submit posts {date, token, sleep_word, body_word, mood_word, felt_recovered} — the
// exact body coach/morning_note.validate_note_body accepts.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const mn = await import("../../site/assets/js/morning_note_box.js");

// A fake 32-hex grant, built (not written as one literal) so it never reads as a credential.
const TOKEN = "ab".repeat(16);
const DAY = "2026-10-10";
const NOW = new Date("2026-10-10T12:30:00Z"); // 05:30 PT on DAY

// ── a minimal DOM: just the calls the module makes ─────────────────────────────────────────
class Node {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.children = []; this.text = ""; this.listeners = {}; this.disabled = false; this.value = ""; this.checked = false; }
  setAttribute(k, v) { this.attrs[k] = v; if (k === "value") this.value = v; }
  set textContent(t) { this.text = t; } get textContent() { return this.text + this.children.map((c) => c.textContent).join(""); }
  appendChild(c) { this.children.push(c); c.parent = this; return c; }
  addEventListener(t, fn) { this.listeners[t] = fn; }
  insertAdjacentElement(where, n) { this.inserted = { where, n }; }
  all() { return this.children.flatMap((c) => [c, ...c.all()]); }
  _match(sel, n) {
    const m = /^(\w+)?(?:\.([\w-]+))?(?:\[name="(\w+)"\])?(:checked)?$/.exec(sel.trim());
    if (!m) throw new Error(`fake DOM: unhandled selector ${sel}`);
    return (!m[1] || n.tag === m[1]) && (!m[2] || (n.attrs.class || "").split(" ").includes(m[2])) && (!m[3] || n.attrs.name === m[3]) && (!m[4] || n.checked);
  }
  querySelectorAll(sel) { const parts = sel.split(","); return this.all().filter((n) => parts.some((p) => this._match(p, n))); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const fakeDoc = () => ({ createElement: (t) => new Node(t), createTextNode: (t) => { const n = new Node("#text"); n.text = t; return n; } });
const fakeHist = () => ({ state: null, calls: [], replaceState(s, t, url) { this.calls.push(url); } });

test("a reader's URL builds nothing, posts nothing and leaves history alone", () => {
  for (const hash of ["", "#", "#scope=week", `#note=${DAY}`, `#note=${DAY}.nothex`, `#xnote=${DAY}.${TOKEN}`]) {
    const hist = fakeHist();
    const anchor = new Node("div");
    let posted = 0;
    const out = mn.mountMorningNoteBox({ doc: fakeDoc(), loc: { pathname: "/cockpit/", search: "", hash }, hist, anchor, post: () => { posted += 1; }, now: NOW });
    assert.equal(out, null, hash);
    assert.equal(anchor.inserted, undefined, hash);
    assert.deepEqual(hist.calls, [], hash);
    assert.equal(posted, 0, hash);
  }
});

test("the owner's grant mounts the box above the hero and strips the token from the address bar", () => {
  const hist = fakeHist();
  const anchor = new Node("div");
  const form = mn.mountMorningNoteBox({ doc: fakeDoc(), loc: { pathname: "/cockpit/", search: "?x=1", hash: `#note=${DAY}.${TOKEN}&scope=week` }, hist, anchor, now: NOW });
  assert.ok(form);
  assert.equal(anchor.inserted.where, "beforebegin");
  assert.equal(anchor.inserted.n, form);
  assert.deepEqual(hist.calls, ["/cockpit/?x=1#scope=week"]);
  assert.ok(!JSON.stringify(hist.calls).includes(TOKEN));
  assert.equal(form.querySelectorAll("input").filter((n) => n.attrs.type === "text").length, 3);
});

test("submit posts exactly the door's body, and only a 2xx says stored", async () => {
  const posts = [];
  const form = mn.mountMorningNoteBox({
    doc: fakeDoc(), loc: { pathname: "/cockpit/", search: "", hash: `#note=${DAY}.${TOKEN}` }, hist: fakeHist(), anchor: new Node("div"), now: NOW,
    post: async (path, body) => { posts.push([path, body]); return { ok: true, status: 200, data: {} }; },
  });
  form.querySelector('input[name="sleep_word"]').value = "  heavy ";
  form.querySelector('input[name="body_word"]').value = "stiff";
  form.querySelector('input[name="mood_word"]').value = "quietly  steady";
  const no = form.querySelectorAll('input[name="felt_recovered"]').find((n) => n.attrs.value === "false");
  no.checked = true;
  await form.listeners.submit({ preventDefault() {} });
  assert.deepEqual(posts, [["/api/morning_note", { date: DAY, token: TOKEN, sleep_word: "heavy", body_word: "stiff", mood_word: "quietly steady", felt_recovered: false }]]);
  assert.match(form.querySelector(".mn-status").textContent, /^Stored/);
});

test("a word the door would refuse is caught before any request", async () => {
  let posted = 0;
  const form = mn.mountMorningNoteBox({ doc: fakeDoc(), loc: { pathname: "/", search: "", hash: `#note=${DAY}.${TOKEN}` }, hist: fakeHist(), anchor: new Node("div"), now: NOW, post: async () => { posted += 1; } });
  form.querySelector('input[name="sleep_word"]').value = "slept 8h";
  await form.listeners.submit({ preventDefault() {} });
  assert.equal(posted, 0);
  assert.match(form.querySelector(".mn-status").textContent, /Sleep/);
});

test("a link for another day offers no inputs", () => {
  const form = mn.mountMorningNoteBox({ doc: fakeDoc(), loc: { pathname: "/", search: "", hash: `#note=2026-10-09.${TOKEN}` }, hist: fakeHist(), anchor: new Node("div"), now: NOW });
  assert.equal(form.querySelectorAll("input").length, 0);
  assert.match(form.textContent, /This link was for 2026-10-09/);
});

test("the status line is honest per response", () => {
  assert.match(mn.statusFor({ ok: true, status: 200 }), /^Stored/);
  assert.match(mn.statusFor({ ok: false, status: 409, data: {} }), /already stored/);
  assert.match(mn.statusFor({ ok: false, status: 403, data: {} }), /not for today/);
  assert.match(mn.statusFor({ ok: false, status: 400, data: { error: "mood_word must be a string" } }), /mood_word must be a string/);
  for (const status of [0, 429, 500, 503]) assert.match(mn.statusFor({ ok: false, status, data: {} }), /^Not stored/);
  assert.equal(mn.pacificToday(NOW), DAY);
  assert.equal(mn.pacificToday(new Date("2026-10-10T06:59:00Z")), "2026-10-09");
});
