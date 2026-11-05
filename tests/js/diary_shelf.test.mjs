// tests/js/diary_shelf.test.mjs — the consent-gated diary shelf renderer (#1846).
//
// The server decides what a reader may see; this module decides how it reads. The
// regressions worth pinning are the ones that would make an HONEST payload render
// DISHONESTLY: a fabricated Day 1 for a pre-genesis entry, a "0:00" duration for an
// entry that was never measured, a padded shelf when nothing is published, or a
// withheld count quietly dropped on the floor.
//
// Dynamic `await import()` rather than a static import: a static specifier resolves
// BEFORE the loader registered by support/loader.mjs takes effect.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const mod = await import("../../site/assets/js/diary_shelf.js");
const { esc, human, stampHTML, metaLine, quotesHTML, claimsHTML, cardHTML, shelfHTML } = mod;

const entry = (over = {}) => ({
  date: "2026-07-27",
  cycle: 11,
  day_number: 1,
  channel: "video_diary",
  format: "video diary",
  tier: "quote",
  theme: "personal_growth",
  day_mark: { svg: "<svg class=\"fingerprint\"></svg>", warming_up: false, earned: 0.6 },
  quotes: [],
  quotes_withheld: 0,
  claims: [],
  claims_on_record: 0,
  ...over,
});

// ── escaping / formatting ────────────────────────────────────────────────────

test("esc — neutralises markup in anything that came from a payload", () => {
  assert.equal(esc('<img src=x onerror="alert(1)">'), "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
  assert.equal(esc(null), "");
});

test("human — renders an ISO date, and nothing at all for a malformed one", () => {
  assert.equal(human("2026-07-27"), "July 27, 2026");
  assert.equal(human("27/07/2026"), "");
  assert.equal(human(undefined), "");
});

// ── the honest-absence rules ─────────────────────────────────────────────────

test("stampHTML — a pre-genesis entry gets no fabricated Day 1", () => {
  assert.equal(stampHTML(entry({ cycle: null, day_number: null })), "");
  assert.match(stampHTML(entry()), /Day 1 &middot; cycle 11/);
});

test("stampHTML — a known cycle with an unknown day number still names the cycle", () => {
  assert.match(stampHTML(entry({ day_number: null })), /cycle 11/);
  assert.doesNotMatch(stampHTML(entry({ day_number: null })), /Day /);
});

test("metaLine — duration appears only when the payload measured one", () => {
  assert.equal(metaLine(entry()), "July 27, 2026 &middot; video diary");
  assert.equal(
    metaLine(entry({ duration: { seconds: 401, label: "6:41" } })),
    "July 27, 2026 &middot; video diary &middot; 6:41",
  );
});

test("metaLine — a payload without a `format` label never prints a raw enum key", () => {
  const html = metaLine(entry({ format: undefined, channel: "solo_recording" }));
  assert.match(html, /solo recording/);
  assert.doesNotMatch(html, /solo_recording/);
});

// ── quotes: shown, withheld, or honestly absent ──────────────────────────────

test("quotesHTML — renders marked lines verbatim in the quote register", () => {
  const html = quotesHTML(entry({ quotes: [{ quote: "I stopped calling it a failure." }] }));
  assert.match(html, /<blockquote class="dsh-quote">&ldquo;I stopped calling it a failure\.&rdquo;<\/blockquote>/);
});

test("quotesHTML — says plainly when an entry carried no marked lines", () => {
  assert.match(quotesHTML(entry()), /No lines from this entry were marked for publication/);
});

// Owner ruling 2026-11-05: no count of the lines that stayed private — the server no longer sends one,
// and the card must never print one even if a stale payload still carries it.
test("quotesHTML — a withheld line is neither drawn as a redacted row nor counted", () => {
  const html = quotesHTML(entry({ quotes: [] }));
  assert.doesNotMatch(html, /blockquote/);
  assert.doesNotMatch(html, /stayed private|more lines?/);
});

test("quotesHTML — NEGATIVE CONTROL: a stale withheld count in the payload changes nothing on the card", () => {
  for (const n of [1, 2, 7]) {
    const html = quotesHTML(entry({ quotes: [{ quote: "I stopped calling it a failure." }], quotes_withheld: n }));
    assert.equal(html, quotesHTML(entry({ quotes: [{ quote: "I stopped calling it a failure." }] })));
    assert.doesNotMatch(html, new RegExp(`\\b${n} more`));
  }
});

test("quotesHTML — an empty quote string is dropped, not rendered as empty quotes", () => {
  const html = quotesHTML(entry({ quotes: [{ quote: "   " }] }));
  assert.doesNotMatch(html, /blockquote/);
});

// ── claims: counted always, quoted only when marked ──────────────────────────

test("claimsHTML — private claims are neither quoted nor counted (owner ruling 2026-11-05)", () => {
  // NEGATIVE CONTROL: a stale `claims_on_record` must not resurrect a count line.
  for (const n of [1, 3]) {
    const html = claimsHTML(entry({ claims: [], claims_on_record: n }));
    assert.equal(html, "");
    assert.doesNotMatch(html, /forecasts? on the record|graded privately/);
  }
});

test("claimsHTML — a publicly marked claim is listed with its called-by date", () => {
  const html = claimsHTML(entry({
    claims: [{ claim_natural: "Still logging in sixty days.", grade_by: "2026-09-25" }],
    claims_on_record: 1,
  }));
  assert.match(html, /Still logging in sixty days\./);
  assert.match(html, /called by 2026-09-25/);
});

test("claimsHTML — no claims at all renders nothing (no empty section)", () => {
  assert.equal(claimsHTML(entry()), "");
});

// ── the shelf as a whole ─────────────────────────────────────────────────────

test("cardHTML — carries the server's day-mark SVG, not a client-invented glyph", () => {
  assert.match(cardHTML(entry()), /<svg class="fingerprint">/);
});

test("cardHTML — a dateless entry renders nothing rather than a broken card", () => {
  assert.equal(cardHTML({ date: "" }), "");
  assert.equal(cardHTML(null), "");
});

test("cardHTML — the coarse theme is rendered from the shared vocabulary", () => {
  assert.match(cardHTML(entry()), /On his mind: habits and growth\./);
  // "other" is deliberately no theme at all — the tier's granularity, honoured.
  assert.doesNotMatch(cardHTML(entry({ theme: "other" })), /On his mind/);
});

test("shelfHTML — a quiet shelf renders as quiet, never padded", () => {
  const html = shelfHTML({ shelf: { entries: [], withheld: 0 } });
  assert.match(html, /No diary entries have been published yet/);
  assert.doesNotMatch(html, /dsh-card/);
});

// Owner ruling 2026-11-05 ("classify video-diary sessions as private journal activity"): the shelf
// never counts the private entries. The empty state stays TRUE without the count — it says nothing has
// been PUBLISHED, never that nothing was recorded — and the server's note states the policy.
test("shelfHTML — an all-private shelf says nothing is published, never that nothing exists, and no count", () => {
  const html = shelfHTML({ shelf: { entries: [], note: "Everything else stays in the studio — never shown, never counted." } });
  assert.match(html, /No diary entries have been published yet/);
  assert.doesNotMatch(html, /recorded|\bno diary entries exist/i);
  assert.match(html, /never shown, never counted/);
});

test("shelfHTML — NEGATIVE CONTROL: a stale `withheld` count renders exactly like no count", () => {
  for (const shelf of [{ entries: [] }, { entries: [entry()] }]) {
    const clean = shelfHTML({ shelf });
    for (const n of [1, 4, 9]) {
      const html = shelfHTML({ shelf: { ...shelf, withheld: n } });
      assert.equal(html, clean);
      assert.doesNotMatch(html, /dsh-foot|recorded and (none are|not) published/);
    }
  }
});

test("shelfHTML — no withheld entries means no footer nag", () => {
  const html = shelfHTML({ shelf: { entries: [entry()], withheld: 0 } });
  assert.doesNotMatch(html, /dsh-foot/);
});

test("shelfHTML — the empty state speaks the SERVER's policy sentence, not a client copy", () => {
  const html = shelfHTML({ shelf: { entries: [], withheld: 0, note: "Only what he cleared, ever." } });
  assert.match(html, /Only what he cleared, ever\./);
  // …and falls back to the standing line when the payload carries no note.
  assert.match(shelfHTML({ shelf: { entries: [], withheld: 0 } }), /Nothing here publishes by default/);
});

test("shelfHTML — a missing/failed payload collapses the block entirely", () => {
  assert.equal(shelfHTML(null), "");
  assert.equal(shelfHTML({}), "");
});
