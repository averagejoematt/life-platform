// tests/js/evidence_discovery_decision_source_label_4190.test.mjs — #4190.
//
// /protocols/experiments/ rendered a logged decision's `source: "mcp"` as
// "from the mcp" — a reader has no reason to know "mcp" is the MCP transport a
// coaching chat calls through. Pinned here as a pure string assertion on
// renderExperiments' output, offline — no browser needed (same harness as
// evidence_discovery_pipeline.test.mjs).
import "./support/loader.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { renderExperiments } = await import("../../site/assets/js/evidence_discovery.js");

function libItem(i) {
  return {
    id: `lib-${i}`,
    name: `Library Entry ${i}`,
    origin: "library",
    status: "backlog",
    hypothesis: "A placeholder hypothesis for the test fixture.",
    pillar: "test",
    evidence_tier: "emerging",
    citation_status: "verified",
    evidence_citation: "Some Journal 2024",
  };
}

// Stubs fetch so /api/decisions answers with `decisions`, and every other
// tryJSON call renderExperiments makes (experiment_synthesis, experiment_library)
// answers "nothing available" instead of throwing.
function stubFetchWithDecisions(decisions) {
  globalThis.fetch = async (url) => {
    if (String(url).includes("/api/decisions")) {
      return { ok: true, status: 200, json: async () => ({ decisions, count: decisions.length }) };
    }
    return { ok: false, status: 404, json: async () => null };
  };
}

test("decision source 'mcp' renders a reader-facing label, never the transport name", async () => {
  stubFetchWithDecisions([
    {
      date: "2026-09-08",
      decision: "Committed to Hevy as Foundation - Push - 3 - 11.",
      source: "mcp",
      followed: true,
      note: "Went with the platform's call.",
      note_at: "2026-09-08T10:00:00Z",
    },
  ]);
  const html = await renderExperiments({ experiments: [libItem(0)] });
  assert.equal(html.includes("from the mcp"), false, "must never print the raw transport name");
  assert.ok(html.includes("logged from the coaching chat"), "must print the reader-facing label for source=mcp");
});

test("other sources keep the plain-English fallback label (daily_brief -> 'from the daily brief')", async () => {
  stubFetchWithDecisions([
    {
      date: "2026-09-01",
      decision: "Take a rest day.",
      source: "daily_brief",
      followed: false,
      override_reason: "Felt fine, trained anyway.",
      note: "My call — I felt good.",
      note_at: "2026-09-01T10:00:00Z",
    },
  ]);
  const html = await renderExperiments({ experiments: [libItem(0)] });
  assert.ok(html.includes("from the daily brief"), "an untranslated source must keep the generic 'from the <source>' form");
});
