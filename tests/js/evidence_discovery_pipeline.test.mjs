// tests/js/evidence_discovery_pipeline.test.mjs — #2151.
//
// Two failure modes found during #1983's render QA (PR #2146): (1) the pipeline
// header printed the FULL count while a `pipeline.slice(0, 60)` silently capped
// the render — 7 of 67 entries never showed, including a "no direct study"
// marker; (2) that marker's citation_note reached readers only via a hover
// `title`, unreadable on touch. Both are pinned here as pure string assertions
// on renderExperiments' output, offline — no browser needed.
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { renderExperiments } = await import("../../site/assets/js/evidence_discovery.js");

// renderExperiments makes three best-effort network calls (tryJSON, which
// swallows failures and returns null) — stub `fetch` so they resolve to
// "nothing available" instead of throwing in this browser-less environment.
function stubEmptyFetch() {
  globalThis.fetch = async () => ({ ok: false, status: 404, json: async () => null });
}

function libItem(i, status, extra) {
  return {
    id: `lib-${i}`,
    name: `Library Entry ${String(i).padStart(2, "0")}`,
    origin: "library",
    status,
    hypothesis: "A placeholder hypothesis for the test fixture.",
    pillar: "test",
    evidence_tier: "emerging",
    citation_status: "verified",
    evidence_citation: "Some Journal 2024",
    ...extra,
  };
}

test("pipeline — rendered card count equals the header's claimed count, past the old 60-cap", async () => {
  stubEmptyFetch();
  // 67 total (5 available + 62 backlog) mirrors the live count that exposed the
  // bug (#2151) and stays comfortably above the old slice(0, 60) boundary.
  const avail = Array.from({ length: 5 }, (_, i) => libItem(i, "available"));
  const backlog = Array.from({ length: 62 }, (_, i) => libItem(i + 5, "backlog"));
  const pipeline = [...avail, ...backlog];
  assert.equal(pipeline.length, 67, "fixture sanity check");

  const html = await renderExperiments({ experiments: pipeline });

  const claimMatch = /In the pipeline \((\d+)\)/.exec(html);
  assert.ok(claimMatch, "the pipeline section must state its count in the header");
  const claimed = Number(claimMatch[1]);
  assert.equal(claimed, 67, "header count must be the full pipeline length");

  // The fixture has no "running" experiments and no published decisions, so
  // every "<article class=\"rd-card\">" in the output belongs to the pipeline —
  // rendered count is a direct proxy for pipeline cards drawn.
  const rendered = (html.match(/<article class="rd-card">/g) || []).length;
  assert.equal(rendered, claimed, "rendered card count must equal the claimed header count");
  assert.equal(rendered, 67, "all 67 entries must render — none silently capped");

  for (const item of pipeline) {
    assert.ok(html.includes(item.name), `${item.name} must appear — the old slice(0, 60) silently dropped the pipeline's tail`);
  }
});

test("pipeline — a small pipeline still reports and renders a matching count (no off-by-one)", async () => {
  stubEmptyFetch();
  const pipeline = [libItem(0, "available"), libItem(1, "backlog"), libItem(2, "backlog")];
  const html = await renderExperiments({ experiments: pipeline });
  const claimed = Number(/In the pipeline \((\d+)\)/.exec(html)[1]);
  const rendered = (html.match(/<article class="rd-card">/g) || []).length;
  assert.equal(claimed, 3);
  assert.equal(rendered, 3);
});

test("citation_note — reachable without hover on the no-direct-study marker", async () => {
  stubEmptyFetch();
  const noStudyNote = "No RCTs test this directly — carried as an internal hypothesis, not a proven claim.";
  const pipeline = [
    libItem(0, "backlog", {
      citation_status: "no-direct-study",
      citation_note: noStudyNote,
      evidence_citation: null,
    }),
  ];

  const html = await renderExperiments({ experiments: pipeline });

  // The note text must land in the markup somewhere OTHER than a hover-only
  // `title=` attribute.
  assert.ok(html.includes(noStudyNote), "the citation note text must reach the rendered DOM");
  assert.equal(html.includes(`title="${noStudyNote}"`), false, "must not be hover-only via a title attribute");

  // Tap-to-reveal: a focusable wrapper (tabindex) around the marker, containing
  // a panel that carries the note text — the same idiom the Evidence Bar uses
  // (evidence_bar.js' .evb/.evb-tip, shown on :hover/:focus/:focus-within).
  assert.match(
    html,
    /<span class="supp-ev-nostudy" tabindex="0"[^>]*>no direct study<span class="supp-tip" role="tooltip"><span class="supp-tip-l">/,
    "the no-direct-study marker must be a focusable tap-reveal, not bare hover text"
  );
});

test("citation_note — absent note still renders the marker, just without a dead affordance", async () => {
  stubEmptyFetch();
  const pipeline = [libItem(0, "backlog", { citation_status: "no-direct-study", citation_note: null, evidence_citation: null })];
  const html = await renderExperiments({ experiments: pipeline });
  assert.ok(html.includes("no direct study"));
  // No note to show — no tabindex/tap target promising a reveal that has nothing in it.
  assert.equal(/supp-ev-nostudy" tabindex/.test(html), false);
});
