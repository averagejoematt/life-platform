"""#5609 — verbatim coach quotations (owner ruling 2026-11-02, decision C of #5607).

"Preserve historical coach quotations exactly as originally recorded. Add human-readable date explanations
outside the quotation rather than silently modifying the source text. Apply the same validation rules in CI
and production."

Three halves, each pinned here:
  1. the exporter (`scripts/publish_snapshot_contract.word_dates`) no longer rewrites ISO dates inside the
     seven VERBATIM_PATHS — a claim reaches the snapshot byte-identical to the `/api/ledger_export` row —
     while every authored key (grading.how, the title, a summary) is still written in words;
  2. the rule (`scripts/www_verbatim.py`): an ISO date outside a `data-verbatim="coach"` quotation fails,
     inside one passes, inside a correction fails, inside a heading fails, and a fake `data-verbatim` on
     authored words fails because the quoted text must be a string the snapshot carries;
  3. one rule, two callers: tests/web_preview_gate.py (CI, the rendered fixture) and
     scripts/check_www_build.py scan() (every build — the LIVE root deploy runs `--scan-only`).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")
FIXTURES = os.path.join(REPO, "www", "content", "fixtures")
sys.path.insert(0, SCRIPTS)

import publish_snapshot_contract as contract  # noqa: E402
import www_verbatim  # noqa: E402


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


ps = _load("publish_snapshot", os.path.join(SCRIPTS, "publish_snapshot.py"))

# A served claim with two ISO dates and the non-ASCII characters a coach line really carries (an en dash, a %).
SERVED_CLAIM = (
    "  Recovery score will be 52.9% tomorrow based on the night of 2026-09-09 baseline (80% interval 26.7–79.2%), through 2026-09-12.  "
)


# ── 1. the exporter ──────────────────────────────────────────────────────────────────────────────────
def test_a_served_claim_reaches_the_snapshot_byte_identical(monkeypatch):
    """The live mapper → partition() → the snapshot's `claim` is the API's own characters (strip() aside, which the
    mapper has always applied) — the dates are NOT rewritten. The grader's sentence on the same row IS worded."""
    row = {
        "item_id": "sleep:pred_20260911_recovery",
        "prediction_id": "pred_20260911_recovery",
        "coach_id": "sleep",
        "coach_name": "Lisa Park",
        "retired": False,
        "claim": SERVED_CLAIM,
        "status": "confirmed",
        "kind": "number",
        "logged_date": "2026-09-11",
        "due_date": "2026-09-12",
        "settled_date": "2026-09-12",
        "grading": {"how": "compared with the reading of 2026-09-12", "outcome_notes": None, "actual_text": None, "tolerance_text": None},
    }

    def fake_get(base, path, timeout):
        assert path.startswith("/api/ledger_export"), path
        return {"items": [copy.deepcopy(row)], "pages": 1, "total": 1}

    monkeypatch.setattr(ps, "_get", fake_get)
    ctx = ps.LiveContext("https://example.test", {"edition": {"as_of": "2026-11-02"}}, 1.0)
    ctx.coach_ids.add("sleep_coach")
    ps._live_ledger(ctx)
    raw = ctx.objs["prediction"][0]
    pred = contract.word_dates(raw, type_="prediction")
    assert pred["claim"].encode("utf-8") == SERVED_CLAIM.strip().encode("utf-8"), "the quotation was rewritten on its way to the snapshot"
    assert pred["grading"]["how"] == "compared with the reading of 12 September 2026", "authored copy is still written in words"
    assert "2026-09" not in pred["title"], "the title is authored copy (a clipped claim is worded, never shown as a quote)"


def test_every_verbatim_path_is_left_alone_and_authored_keys_are_still_worded():
    """partition() over the fixture (which carries a dated claim, coach line and chip — #5609): each VERBATIM_PATHS
    string is byte-identical to the fixture's, and a dated authored key planted beside it is worded."""
    objs = contract.load_fixtures(FIXTURES)
    raw = copy.deepcopy(objs)
    dated = next(p for p in objs["prediction"] if p["id"] == "physical-20261016-weight02")
    dated["grading"]["how"] = "against the reading of 2026-10-17"
    public, _ = contract.partition(objs)
    preds = {p["id"]: p for p in public["prediction"]}
    raw_preds = {p["id"]: p for p in raw["prediction"]}
    for pid, p in preds.items():
        assert p["claim"] == raw_preds[pid]["claim"], pid
    assert www_verbatim.ISO_DATE.search(preds["physical-20261016-weight02"]["claim"]), "the fixture must carry a dated claim"
    assert preds["physical-20261016-weight02"]["grading"]["how"] == "against the reading of 17 October 2026"
    raw_days = {d["id"]: d for d in raw["day"]}
    seen = 0
    for d in public["day"]:
        r = raw_days[d["id"]]
        for key, field in (("coach_lines", "text"), ("calls_open", "text"), ("calls_settled", "claim_short")):
            for got, want in zip(d.get(key) or [], r.get(key) or []):
                assert got[field] == want[field], f"{d['id']} {key}[].{field} rewritten"
                seen += bool(www_verbatim.ISO_DATE.search(got[field]))
    assert seen >= 2, "the fixture's dated coach line and open-call chip must reach the snapshot verbatim"
    for d in public["disagreement"]:
        r = next(x for x in raw["disagreement"] if x["id"] == d["id"])
        assert (d.get("claim_a"), d.get("claim_b")) == (r.get("claim_a"), r.get("claim_b"))


def test_verbatim_paths_name_only_the_coachs_own_words():
    """The set is a ratchet: only a coach's words, never an authored key. A grader sentence or a title joining it would
    let ISO dates back into authored copy."""
    assert contract.VERBATIM_PATHS == {
        ("prediction", "claim"),
        ("disagreement", "claim_a"),
        ("disagreement", "claim_b"),
        ("day", "coach_lines[].text"),
        ("day", "calls_settled[].claim_short"),
        ("day", "calls_open[].text"),
        ("edition", "blocks.coach_lines.data.lines[].text"),
    }
    # a key name alone is not enough: `text` elsewhere (simple_guess.text) is authored and stays worded
    o = {"simple_guess": {"text": "stays on 2026-09-12"}, "coach_lines": [{"text": "said on 2026-09-12"}]}
    out = contract.word_dates(o, type_="day")
    assert out["simple_guess"]["text"] == "stays on 12 September 2026"
    assert out["coach_lines"][0]["text"] == "said on 2026-09-12"


# ── 2. the rule ──────────────────────────────────────────────────────────────────────────────────────
def test_the_rule_fails_and_passes_on_every_planted_case():
    """One test that reports every misjudged case (the self-test the live scan runs before it scans)."""
    assert www_verbatim.self_test() == []


def test_mutation_controls_named_in_the_ruling():
    allowed = {"Weight will hold within a pound of 304 through 2026-10-17, the morning after the long walk."}
    quote = 'Weight will hold within a pound of 304 through <time datetime="2026-10-17">2026-10-17</time>, the morning after the long walk.'
    gloss = '<span class="gloss" data-quote-gloss> [Saturday 17 October 2026]</span>'
    cases = {
        "ISO outside a quote fails": ("<p>Weighed on 2026-10-17.</p>", True),
        "ISO inside a verbatim quote passes": (f'<p>Lisa Park: <q data-verbatim="coach">{quote}</q>{gloss}</p>', False),
        "ISO inside a correction fails": (
            f'<blockquote data-verbatim="coach">{quote}</blockquote><p class="correction" role="note">Corrected on 2026-11-02.</p>',
            True,
        ),
        "a fake data-verbatim on authored text fails": ('<p><q data-verbatim="coach">Authored copy dated 2026-10-17.</q></p>', True),
        "a quote inside a heading fails": (f'<h1><q data-verbatim="coach">{quote}</q></h1>', True),
        "a clipped quote passes (ellipsis outside)": (
            '<q data-verbatim="coach">Weight will hold within a pound of 304 through</q>…',
            False,
        ),
        "a gloss repeating the ISO form fails": (f'<q data-verbatim="coach">{quote}</q><span data-quote-gloss>[2026-10-17]</span>', True),
    }
    wrong = [name for name, (html, must_fail) in cases.items() if bool(www_verbatim.page_issues(html, "t", allowed)) != must_fail]
    assert wrong == []


def test_entities_in_rendered_quotes_compare_as_characters():
    """Astro escapes an apostrophe as &#39; — the provenance check compares the characters, not the escaping."""
    allowed = {"read 2026-10-17's weigh-in"}
    html = '<blockquote data-verbatim="coach">read <time datetime="2026-10-17">2026-10-17</time>&#39;s weigh-in</blockquote>'
    assert www_verbatim.page_issues(html, "t", allowed) == []


def test_the_other_forbidden_rules_still_scan_inside_quotations():
    """The exemption is the ISO rule only: the build scan's sentinel check reads the whole file, quotes included."""
    cbw = _load("check_www_build_5609", os.path.join(SCRIPTS, "check_www_build.py"))
    assert any(s in '<q data-verbatim="coach">POISON-HELD</q>' for s in cbw.SENTINELS)
    assert (
        "POISON-HELD" not in www_verbatim.strip_verbatim("<p>x</p>")
        and www_verbatim.strip_verbatim('<q data-verbatim="coach">POISON-HELD</q>').strip() == ""
    )


# ── 3. one rule, two callers ─────────────────────────────────────────────────────────────────────────
def test_both_gates_call_the_one_shared_rule():
    gate_src = open(os.path.join(HERE, "web_preview_gate.py"), encoding="utf-8").read()
    build_src = open(os.path.join(SCRIPTS, "check_www_build.py"), encoding="utf-8").read()
    assert "www_verbatim.page_issues(" in gate_src and "www_verbatim.page_issues(" in build_src
    assert "www_verbatim.self_test()" in build_src, "the live scan proves the rule can fail before it trusts a pass"
    assert r"\b20\d\d-\d\d-\d\d\b" not in gate_src, "the render gate's own ISO regex is retired in favour of the shared rule"


def test_the_build_scan_holds_the_rule_on_a_live_shaped_build(tmp_path):
    """scan() on a tiny dist + a LIVE-mode snapshot: a dated authored line fails, the same date inside a quote the
    snapshot carries passes — the property the root deploy's `--scan-only` now enforces (run 41519666090's lesson:
    a page-universal rule only)."""
    cbw = _load("check_www_build_5609b", os.path.join(SCRIPTS, "check_www_build.py"))
    snap = tmp_path / "snapshot"
    snap.mkdir()
    (snap / "manifest.json").write_text(json.dumps({"mode": "live"}))
    claim = "Weight will hold through 2026-10-17."
    (snap / "predictions.json").write_text(json.dumps([{"id": "p", "claim": claim, "claim_withheld": None}]))
    dist = tmp_path / "dist"
    (dist / "a").mkdir(parents=True)
    ok = '<q data-verbatim="coach">Weight will hold through <time datetime="2026-10-17">2026-10-17</time>.</q>'
    (dist / "a" / "index.html").write_text(f"<html><body><p>{ok}</p></body></html>")
    assert cbw.scan(str(dist), require_noindex=False, forbidden_ids=set(), snapshot_dir=str(snap)) == []
    (dist / "b").mkdir()
    (dist / "b" / "index.html").write_text("<html><body><p>Weighed on 2026-10-17.</p></body></html>")
    issues = cbw.scan(str(dist), require_noindex=False, forbidden_ids=set(), snapshot_dir=str(snap))
    assert any(i.startswith("b/index.html: an ISO date outside a verbatim quotation") for i in issues), issues


def test_a_withheld_claims_chip_is_never_a_quotation(tmp_path):
    """A withheld claim's Day chip carries the hold's own sentence ("Not quoted: …") — authored copy. Wrapped as a
    verbatim quotation it would put words in the coach's mouth, so the provenance set refuses it (the Day page renders
    it as plain text; 21 such chips on 10 live Day pages, 2026-11-02)."""
    hold = "Not quoted: this was said on September 14 and rests on his glucose sensor"
    (tmp_path / "predictions.json").write_text(json.dumps([{"id": "held-1", "claim": hold, "claim_withheld": "unsourced"}]))
    (tmp_path / "days.json").write_text(
        json.dumps(
            [{"id": "2026-09-20", "calls_open": [{"prediction_id": "held-1", "text": hold}], "calls_settled": [], "coach_lines": []}]
        )
    )
    allowed = www_verbatim.verbatim_strings(str(tmp_path))
    assert allowed == set()
    assert www_verbatim.page_issues(f'<q data-verbatim="coach">{hold}</q>', "t", allowed)
    assert www_verbatim.page_issues(f"<span>{hold}</span>", "t", allowed) == []
