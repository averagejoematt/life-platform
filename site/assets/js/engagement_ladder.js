// engagement_ladder.js — The Engagement Ladder (#1393, epic #1366).
// Reader → Subscriber → Predictor → Replicator → Contributor.
//
// The reader's OWN rung is derived ENTIRELY from the existing subscriber HMAC token
// (sessionStorage 'lp_sub_token') + localStorage flags the site already writes — no
// auth system, no new identity, nothing about the reader sent to the server. The only
// network calls are (1) a read of the public rung COUNTS and (2) an optional Replicator
// self-cert POST that carries no PII.
//
// SDT guardrail (the design warning this story is built around — controlling
// gamification crowds out intrinsic motivation): the participation surface is
// INFORMATION ONLY. It states what the reader has done, neutrally; gaps carry no
// consequence and every rung is skippable. Keep all copy descriptive — no urgency,
// no countdown, no framing that treats a missed week as a loss. tests/
// test_engagement_ladder_1393.py scans this whole file for pressure/loss vocabulary.

const API = "/api";

// Keys the rest of the site already owns — we only READ them.
const SUB_TOKEN_KEY = "lp_sub_token"; // set by the ask flow after subscriber-token verification
const PREDICT_PREFIX = "ajm-predict-"; // cockpit.js: ajm-predict-{week}-{metric} = choice
const REPLICATED_KEY = "ajm-replicated"; // this component's self-cert flag (timestamp)
const FINDING_KEY = "ajm-finding-submitted"; // evidence_discovery.js sets this on submit

function _ls(key) {
  try {
    return localStorage.getItem(key);
  } catch (e) {
    return null;
  }
}
function _ss(key) {
  try {
    return sessionStorage.getItem(key);
  } catch (e) {
    return null;
  }
}

// A confirmed subscriber has a non-expired HMAC token. We only decode the expiry that
// is already embedded in the token — we never call the server to check identity.
function hasValidSubscriberToken() {
  const raw = _ss(SUB_TOKEN_KEY);
  if (!raw) return false;
  try {
    const decoded = atob(raw.replace(/-/g, "+").replace(/_/g, "/"));
    const parts = decoded.split(":"); // email : valid-until epoch : sig
    const validUntil = parseInt(parts[1], 10);
    if (!validUntil) return true; // malformed field → treat presence as membership, fail-open
    return validUntil * 1000 > Date.now();
  } catch (e) {
    return true; // opaque token present → count it, don't gatekeep on a decode quirk
  }
}

// Distinct ISO weeks the reader has predicted in, from the cockpit's own localStorage.
function predictedWeeks() {
  const weeks = new Set();
  let n = 0;
  try {
    n = localStorage.length;
  } catch (e) {
    return weeks;
  }
  for (let i = 0; i < n; i++) {
    let k;
    try {
      k = localStorage.key(i);
    } catch (e) {
      continue;
    }
    if (!k || k.indexOf(PREDICT_PREFIX) !== 0) continue;
    // ajm-predict-2026-W30-weight → week id is the "YYYY-Www" slice.
    const m = k.slice(PREDICT_PREFIX.length).match(/^(\d{4}-W\d{2})/);
    if (m) weeks.add(m[1]);
  }
  return weeks;
}

// A neutral, information-only "run" of consecutive recent weeks. A gap simply ends the
// run with no consequence, and the UI never draws attention to a missed week. Returns
// { total, run } — both purely descriptive.
function participationInfo(weeks) {
  const ids = Array.from(weeks).sort();
  const ordinal = (w) => {
    const mm = w.match(/^(\d{4})-W(\d{2})$/);
    return mm ? parseInt(mm[1], 10) * 53 + parseInt(mm[2], 10) : 0;
  };
  let run = ids.length ? 1 : 0;
  for (let i = ids.length - 1; i > 0; i--) {
    if (ordinal(ids[i]) - ordinal(ids[i - 1]) === 1) run++;
    else break;
  }
  return { total: ids.length, run };
}

function reachedRungs() {
  const weeks = predictedWeeks();
  return {
    reader: true, // the base rung — everyone, always
    subscriber: hasValidSubscriberToken(),
    predictor: weeks.size >= 1,
    replicator: !!_ls(REPLICATED_KEY),
    // Contributor is server-verified (a published finding). The client can never assert
    // it honestly, so it is NEVER auto-reached here — only informational.
    contributor: false,
    _weeks: weeks,
    _findingSubmitted: !!_ls(FINDING_KEY),
  };
}

const RUNGS = [
  {
    key: "reader",
    name: "Reader",
    blurb: "You're reading. That's the baseline — no account, nothing about you is tracked.",
  },
  {
    key: "subscriber",
    name: "Subscriber",
    blurb: "One email a week: the chronicle, the week's data, and the AI's read. Double opt-in, unsubscribe anytime.",
    cta: { href: "#main", label: "Follow by email ↑" },
  },
  {
    key: "predictor",
    name: "Predictor",
    blurb: "Call which way a metric moves this week on the cockpit. See it against everyone else's read.",
    cta: { href: "/cockpit/", label: "Predict the week →" },
  },
  {
    key: "replicator",
    name: "Replicator",
    blurb: "Run a Replication Kit against your own data, then self-certify it. Self-reported — no proof asked for or stored.",
    cta: { href: "/protocols/experiments/", label: "Browse the kits →" },
    selfCert: true,
  },
  {
    key: "contributor",
    name: "Contributor",
    blurb: "Submit a finding from the data. If it's verified it gets published — with named credit, only if you opt in.",
    cta: { href: "/cockpit/", label: "Submit a finding →" },
  },
];

function el(tag, cls, html) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
}

function countLabel(rung, data) {
  if (!data || !data.rungs) return null;
  const r = data.rungs[rung.key];
  if (!r || r.countable === false || r.count == null) return null;
  const n = r.count;
  return `${n.toLocaleString()} so far`;
}

async function selfCertify(btn, mount, data) {
  btn.disabled = true;
  btn.textContent = "Logging…";
  try {
    await fetch(`${API}/replicate_certify`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  } catch (e) {
    /* fail-soft: still credit the reader locally so their rung resolves */
  }
  try {
    localStorage.setItem(REPLICATED_KEY, String(Date.now()));
  } catch (e) {}
  render(mount, data); // re-render with the reader now on the Replicator rung
}

function render(mount, data) {
  const reached = reachedRungs();
  mount.textContent = "";

  const list = el("ol", "ladder-rungs");
  list.setAttribute("aria-label", "The engagement ladder");

  // The reader's current position = the highest rung they've reached.
  const order = RUNGS.map((r) => r.key);
  let hereIdx = 0;
  order.forEach((k, i) => {
    if (reached[k]) hereIdx = i;
  });

  RUNGS.forEach((rung, i) => {
    const li = el("li", "ladder-rung");
    li.dataset.rung = rung.key;
    if (reached[rung.key]) li.dataset.reached = "1";
    if (i === hereIdx) li.dataset.here = "1";

    const head = el("div", "lr-head");
    head.appendChild(el("span", "lr-name", rung.name));
    if (reached[rung.key]) head.appendChild(el("span", "lr-badge", "you're here"));
    const cnt = countLabel(rung, data);
    if (cnt) head.appendChild(el("span", "lr-count", cnt));
    li.appendChild(head);

    li.appendChild(el("p", "lr-blurb", rung.blurb));

    // Contributor is verified server-side; if the reader has submitted a finding, say so
    // — neutrally, as status, never as pressure.
    if (rung.key === "contributor" && reached._findingSubmitted) {
      li.appendChild(el("p", "lr-note", "You've submitted a finding — it's in the review queue."));
    }

    // The Replicator self-cert lives on its rung.
    if (rung.selfCert && !reached.replicator) {
      const b = el("button", "lr-selfcert", "I ran a Replication Kit");
      b.type = "button";
      b.addEventListener("click", () => selfCertify(b, mount, data));
      li.appendChild(b);
    } else if (rung.cta && !reached[rung.key]) {
      const a = el("a", "lr-cta");
      a.href = rung.cta.href;
      a.textContent = rung.cta.label;
      li.appendChild(a);
    }

    list.appendChild(li);
  });
  mount.appendChild(list);

  // Participation info — INFORMATION ONLY. Shown only if they've predicted; gaps are
  // neutral, no run is ever described as lost or in jeopardy.
  if (reached.predictor) {
    const info = participationInfo(reached._weeks);
    let msg;
    if (info.run >= 2) {
      msg = `You've predicted ${info.run} weeks in a row — ${info.total} in total. Predict whenever you like; skipping a week changes nothing.`;
    } else {
      msg = `You've predicted in ${info.total} week${info.total === 1 ? "" : "s"}. Come back whenever — there's no clock on it.`;
    }
    mount.appendChild(el("p", "ladder-you", msg));
  }

  // Provenance disclosure — the counts are derived from data, and we show how.
  if (data && data.rungs) {
    const det = el("details", "ladder-prov");
    det.appendChild(el("summary", null, "How these counts are derived"));
    const dl = el("dl", "ladder-prov-list");
    order.forEach((k) => {
      const r = data.rungs[k];
      if (!r || !r.provenance) return;
      dl.appendChild(el("dt", null, r.label || k));
      const p = r.provenance;
      dl.appendChild(el("dd", null, `${p.method || ""}${p.source && p.source !== "none" ? ` — <code>${p.source}</code>` : ""}. ${p.note || ""}`));
    });
    det.appendChild(dl);
    mount.appendChild(det);
  }
}

async function init() {
  const mount = document.querySelector("[data-ladder-body]");
  if (!mount) return;
  let data = null;
  try {
    const res = await fetch(`${API}/ladder_counts`);
    if (res.ok) data = await res.json();
  } catch (e) {
    /* fail-soft: render the ladder without public counts */
  }
  render(mount, data);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
else init();
