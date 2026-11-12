"""#5778 — the exercise library's per-block evidence review (scripts/library_evidence_review.py).

Every network call is mocked: an autouse fixture makes `urllib.request.urlopen` raise, and the script's HTTP goes
through an injected fake that serves Crossref / PubMed shaped records. Must-fail controls sit beside each pass.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import urllib.parse

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "deploy"), os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import exercise_library_reviews as reviews  # noqa: E402
import library_evidence_review as ler  # noqa: E402

_spec = importlib.util.spec_from_file_location("_attr_3005", os.path.join(ROOT, "tests", "test_no_tool_attribution_3005.py"))
attribution = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(attribution)
from training import (
    exercise_library as xl,  # noqa: E402
    quality_rubric as qr,  # noqa: E402
)

LIB = xl.load_library()
ALLOW = ler.load_allowlist()
TODAY = "2026-12-01"
ADJ_UP = {"bands": 1, "citation": "testerson2026_overhead", "why": "grew the target more than the compared movement (test)"}

NEW = {
    "doi": "10.1000/test.2026.001",
    "pmid": "40000001",
    "title": "Overhead cable extension grows the triceps long head: a randomized trial",
    "authors": "Testerson A, Second B",
    "year": 2026,
    "journal": "Journal of Test Physiology",
    "study_design": "randomized_trial",
    "finding": "overhead beat neutral for long-head volume",
    "abstract_read": True,
}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a test reached the real network")

    monkeypatch.setattr(ler.urllib.request, "urlopen", boom)


def _crossref(c, **over):
    surname = c["authors"].split(",")[0].rsplit(" ", 1)[0]
    m = {
        "title": [c["title"]],
        "author": [{"family": surname, "sequence": "first"}],
        "issued": {"date-parts": [[int(c["year"]), 1]]},
        "type": "journal-article",
    }
    m.update(over)
    return m


def _pubmed(c, **over):
    r = {
        "uid": c["pmid"],
        "title": c["title"] + ".",
        "authors": [{"name": a.strip()} for a in c["authors"].split(",")],
        "pubdate": f"{c['year']} Jan",
        "epubdate": "",
        "pubtype": ["Journal Article", "Randomized Controlled Trial"],
        "articleids": [{"idtype": "doi", "value": c.get("doi")}] if c.get("doi") else [],
    }
    r.update(over)
    return r


class FakeHttp:
    """Serves Crossref `works/<doi>` and PubMed `esummary` from dicts; anything absent is a 404; `down` ids are status 0."""

    def __init__(self, crossref=None, pubmed=None, down=()):
        self.crossref = dict(crossref or {})
        self.pubmed = dict(pubmed or {})
        self.down = set(down)
        self.calls: list[str] = []

    @classmethod
    def for_library(cls, lib=LIB, extra=(), **kw):
        cr, pm = {}, {}
        for c in list(lib["citations"].values()) + list(extra):
            if c.get("doi"):
                cr[c["doi"].lower()] = _crossref(c)
            if c.get("pmid"):
                pm[str(c["pmid"])] = _pubmed(c)
        return cls(cr, pm, **kw)

    def __call__(self, url):
        self.calls.append(url)
        u = urllib.parse.urlparse(url)
        if u.hostname == "api.crossref.org":
            doi = urllib.parse.unquote(u.path.split("/works/", 1)[1]).lower()
            if doi in self.down:
                return 0, None
            return (200, {"message": self.crossref[doi]}) if doi in self.crossref else (404, None)
        if u.hostname == "eutils.ncbi.nlm.nih.gov" and "esummary" in u.path:
            ids = urllib.parse.parse_qs(u.query)["id"][0].split(",")
            if any(i in self.down for i in ids):
                return 0, None
            res = {"uids": ids}
            for i in ids:
                res[i] = self.pubmed.get(i) or {"uid": i, "error": "cannot get document summary"}
            return 200, {"result": res}
        if u.hostname == "eutils.ncbi.nlm.nih.gov" and "esearch" in u.path:
            return 200, {"esearchresult": {"idlist": []}}
        raise AssertionError(f"unexpected URL {url}")


def _add(cid="testerson2026_overhead", c=None, via=None):
    return {"op": "add_citation", "citation_id": cid, "citation": dict(c or NEW), "found_via": via or {"kind": "pubmed"}}


def _set(confidence="rct_characteristic", cites=("testerson2026_overhead",), movement="bench_press_barbell", target="chest", **kw):
    """A `set_evidence` op (#5857: evidence is proposed; the quality tier is derived by the rubric, never proposed)."""
    op = {
        "op": "set_evidence",
        "movement": movement,
        "target": target,
        "evidence_confidence": confidence,
        "citations": list(cites),
        "rationale": "test",
        "abstract_read": True,
    }
    op.update(kw)
    return op


def _decide(ops, http=None, lib=LIB):
    http = http or FakeHttp.for_library(lib, extra=[NEW])
    rever = ler.reverify_existing(lib, http, ALLOW)
    return ler.review(lib, {"review_id": "t", "proposals": ops}, ALLOW, http, TODAY, rever), http


def _row(lib, movement, target):
    return next(r for r in lib["movements"][movement]["hypertrophy"] if r["target"] == target)


# ── allowlist enforcement ───────────────────────────────────────────────────────────────────────────────────────


def test_a_non_allowlisted_source_is_rejected_before_any_lookup():
    """Social media, blogs, bare URLs, unknown channels and unnamed reviewers never reach verification. Every case is
    reported (one test, every offender listed)."""
    cases = {
        "twitter_channel": (NEW, {"kind": "twitter"}),
        "blog_channel": (NEW, {"kind": "blog", "url": "https://someone.substack.com/p/triceps"}),
        "instagram_link_in_finding": ({**NEW, "finding": "per https://www.instagram.com/p/xyz"}, {"kind": "pubmed"}),
        "youtube_reviewer_link": (NEW, {"kind": "reviewer", "name": "Schoenfeld BJ", "url": "https://youtu.be/abc"}),
        "unlisted_reviewer": (NEW, {"kind": "reviewer", "name": "Some Influencer"}),
        "bare_url_no_identifier": (
            {**{k: v for k, v in NEW.items() if k not in ("doi", "pmid")}, "url": "https://example.com/x"},
            {"kind": "pubmed"},
        ),
        "unlisted_design": ({**NEW, "study_design": "testimonial"}, {"kind": "pubmed"}),
    }
    offenders = []
    for name, (c, via) in cases.items():
        decided, http = _decide([_add(c=c, via=via)], http=FakeHttp.for_library(extra=[NEW]))
        lookups = [u for u in http.calls if "40000001" in u or "test.2026.001" in u]
        if decided["accepted"]["citations"] or not decided["rejected"] or lookups:
            offenders.append(name)
    assert offenders == [], f"admitted or looked up despite a non-allow-listed source: {offenders}"


def test_an_allowlisted_reviewer_channel_is_admitted():
    """Control for the test above: a named reviewer's peer-reviewed paper, by DOI/PMID, passes."""
    decided, _ = _decide([_add(via={"kind": "reviewer", "name": "Schoenfeld BJ"})])
    assert list(decided["accepted"]["citations"]) == ["testerson2026_overhead"], decided["rejected"]
    assert decided["accepted"]["citations"]["testerson2026_overhead"]["found_via"] == "reviewer: Schoenfeld BJ"


def test_the_allowlist_denies_social_media_and_blogs_and_names_reviewers():
    for host in ("twitter.com", "x.com", "instagram.com", "youtube.com", "tiktok.com", "reddit.com", "substack.com", "medium.com"):
        assert ler._host_ok(host, ALLOW), host
        assert ler._host_ok("www." + host, ALLOW), host
    assert ler._host_ok("doi.org", ALLOW) is None
    assert ALLOW["reviewers"]["names"] and set(ALLOW["channels"]) == {"pubmed", "crossref", "reviewer"}
    # #5857: only a randomized trial may back rct_direct — the only evidence that may move a row off its rubric tier
    assert ALLOW["designs"]["randomized_trial"]["may_back"] == ["rct_direct", "rct_characteristic"]
    assert all("rct_direct" not in d["may_back"] for k, d in ALLOW["designs"].items() if k != "randomized_trial")
    assert all(set(d["may_back"]) <= set(xl.EVIDENCE_CONFIDENCE) - {"none_reviewed"} for d in ALLOW["designs"].values())


def test_a_narrative_review_needs_a_named_reviewer_author():
    review = {**NEW, "study_design": "narrative_review", "authors": "Testerson A, Second B"}
    named = {**review, "pmid": "40000002", "doi": "10.1000/test.2026.002", "authors": "Schoenfeld BJ, Testerson A"}
    http = FakeHttp.for_library(extra=[review, named])
    decided, _ = _decide([_add("rev_unnamed", review), _add("rev_named", named)], http=http)
    assert "rev_unnamed" not in decided["accepted"]["citations"]
    assert "rev_named" in decided["accepted"]["citations"]
    # and a review backs consensus at most: never trial evidence, never a band move
    decided, _ = _decide([_add("rev_named", named), _set(cites=["rev_named"])], http=http)
    assert decided["accepted"]["evidence_changes"] == []
    decided, _ = _decide([_add("rev_named", named), _set("consensus", cites=["rev_named"])], http=http)
    assert [t["evidence_confidence"] for t in decided["accepted"]["evidence_changes"]] == ["consensus"]


# ── verification gates the tier ─────────────────────────────────────────────────────────────────────────────────


def test_an_unverifiable_citation_cannot_raise_evidence():
    """Each way a citation can fail live verification leaves the row none_reviewed on its rubric tier. Must-fail shapes,
    one test, all reported."""
    variants = {
        "doi_404_pmid_404": FakeHttp.for_library(),
        "title_mismatch": FakeHttp.for_library(extra=[{**NEW, "title": "Something else entirely about calves"}]),
        "author_mismatch": FakeHttp.for_library(extra=[{**NEW, "authors": "Other Z"}]),
        "year_mismatch": FakeHttp.for_library(extra=[{**NEW, "year": 2019}]),
        "retracted": FakeHttp.for_library(extra=[NEW]),
        "registry_down": FakeHttp.for_library(extra=[NEW], down={"40000001"}),
        "preprint_not_article": FakeHttp.for_library(extra=[NEW]),
    }
    variants["retracted"].pubmed["40000001"]["pubtype"] = ["Journal Article", "Retracted Publication"]
    variants["preprint_not_article"].crossref[NEW["doi"]]["type"] = "posted-content"
    offenders = []
    for name, http in variants.items():
        decided, _ = _decide([_add(), _set("rct_direct", adjust=ADJ_UP)], http=http)
        after = ler.apply_review(LIB, decided) if ler.has_changes(decided) else LIB
        row = _row(after, "bench_press_barbell", "chest")
        if (
            decided["accepted"]["citations"]
            or decided["accepted"]["evidence_changes"]
            or row["evidence_confidence"] != "none_reviewed"
            or row["tier"] != row["rubric_tier"]
        ):
            offenders.append(name)
    assert offenders == [], f"an unverified citation raised evidence: {offenders}"


def test_a_verified_direct_trial_records_evidence_and_moves_the_row_one_band():
    decided, http = _decide([_add(), _set("rct_direct", adjust=ADJ_UP)])
    assert decided["rejected"] == []
    assert any(NEW["doi"] in urllib.parse.unquote(u) for u in http.calls) and any("40000001" in u for u in http.calls)
    after = ler.apply_review(LIB, decided)
    row = _row(after, "bench_press_barbell", "chest")
    assert (row["evidence_confidence"], row["citations"], row["last_reviewed"]) == ("rct_direct", ["testerson2026_overhead"], TODAY)
    assert row["rubric_tier"] != "S", "the specimen must have a band above it, or the move is invisible"
    assert row["evidence_adjustment"]["bands"] == 1 and row["tier"] == qr.shift(row["rubric_tier"], 1) != row["rubric_tier"]
    assert after["citations"]["testerson2026_overhead"]["verified_on"] == f"Crossref + PubMed, {TODAY}"
    assert xl.validate(after) == []
    assert after["version"] == ler._bump_patch(LIB["version"]) and after["change_log"][-1]["version"] == after["version"]
    assert _row(LIB, "bench_press_barbell", "chest")["evidence_confidence"] == "none_reviewed", "apply_review mutated its input"


def test_evidence_backing_needs_a_pmid_abstract_read_and_a_permitted_design():
    doi_only = {k: v for k, v in NEW.items() if k != "pmid"}
    cases = {
        "doi_only": ([_add(c=doi_only), _set()], FakeHttp.for_library(extra=[doi_only])),
        "abstract_not_read": ([_add(c={**NEW, "abstract_read": False}), _set()], None),
        "set_evidence_without_abstract_read": ([_add(), _set(abstract_read=False)], None),
        "meta_analysis_for_rct_direct": ([_add(c={**NEW, "study_design": "meta_analysis"}), _set("rct_direct")], None),
        "no_citation": ([_set(cites=())], None),
        "unknown_movement": ([_add(), _set(movement="not_a_movement")], None),
        # #5857: the quality tier is never proposed, and only a direct trial moves a row — one band, its own citation
        "proposes_a_tier": ([_add(), _set(tier="S")], None),
        "adjust_without_a_direct_trial": ([_add(), _set(adjust=ADJ_UP)], None),
        "adjust_two_bands": ([_add(), _set("rct_direct", adjust={**ADJ_UP, "bands": 2})], None),
        "adjust_cites_another_paper": ([_add(), _set("rct_direct", adjust={**ADJ_UP, "citation": "maeo2023_overhead_triceps"})], None),
    }
    offenders = [n for n, (ops, http) in cases.items() if _decide(ops, http=http)[0]["accepted"]["evidence_changes"]]
    assert offenders == [], offenders
    # controls: a meta-analysis may back rct_characteristic; a DOI-only record still registers (backing nothing)
    assert _decide([_add(c={**NEW, "study_design": "meta_analysis"}), _set()])[0]["accepted"]["evidence_changes"]
    reg = _decide([_add(c=doi_only)], http=FakeHttp.for_library(extra=[doi_only]))[0]["accepted"]["citations"]
    assert "backs no evidence" in reg["testerson2026_overhead"]["finding"]


def test_a_correction_must_verify_too():
    cid = "kubo2019_squat_depth"
    good = {**LIB["citations"][cid], "study_design": "randomized_trial", "journal": "Eur J Appl Physiol 119:1933-1942"}
    decided, _ = _decide([{"op": "correct_citation", "citation_id": cid, "citation": good, "found_via": {"kind": "crossref"}}])
    assert decided["accepted"]["citations"][cid]["journal"].startswith("Eur J Appl")
    bad = {**good, "year": 2001}
    decided, _ = _decide([{"op": "correct_citation", "citation_id": cid, "citation": bad, "found_via": {"kind": "crossref"}}])
    assert decided["accepted"]["citations"] == {} and decided["rejected"]


# ── re-verification of the registered citations ────────────────────────────────────────────────────────────────


def test_every_registered_citation_reverifies_against_its_own_record():
    """Control: the matcher accepts every registered citation served back in Crossref / PubMed shape (the live run on
    2026-11-11 verified all 15)."""
    rever = ler.reverify_existing(LIB, FakeHttp.for_library(), ALLOW)
    assert {c: v["status"] for c, v in rever.items() if v["status"] != ler.VERIFIED} == {}
    assert sum(1 for v in rever.values() if v["pmid_verified"]) == sum(1 for c in LIB["citations"].values() if c.get("pmid"))


def test_a_vanished_citation_downgrades_only_the_rows_it_alone_backs():
    gone = "maeo2021_seated_leg_curl"
    http = FakeHttp.for_library()
    del http.crossref[LIB["citations"][gone]["doi"].lower()]
    del http.pubmed[LIB["citations"][gone]["pmid"]]
    rever = ler.reverify_existing(LIB, http, ALLOW)
    assert rever[gone]["status"] == ler.NOT_FOUND
    downs = ler.auto_downgrades(LIB, rever, "t", TODAY)
    keys = {(d["movement"], d["target"]) for d in downs}
    backed = {(k, r["target"]) for k, e in LIB["movements"].items() for r in e["hypertrophy"] if r["citations"] == [gone]}
    assert keys == backed and backed
    # a mismatch or an unreachable registry never downgrades
    http2 = FakeHttp.for_library(down={LIB["citations"][gone]["pmid"]})
    http2.crossref[LIB["citations"][gone]["doi"].lower()]["title"] = ["A different paper"]
    rever2 = ler.reverify_existing(LIB, http2, ALLOW)
    assert rever2[gone]["status"] in (ler.MISMATCH, ler.UNREACHABLE)
    assert ler.auto_downgrades(LIB, rever2, "t", TODAY) == []


def test_run_exits_1_when_a_registered_citation_is_gone(tmp_path):
    http = FakeHttp.for_library()
    gone = LIB["citations"]["lake2012_kettlebell_swing"]
    del http.pubmed[gone["pmid"]]
    lines: list[str] = []
    assert ler.run([], http=http, out=lines.append) == 1
    assert any("lake2012_kettlebell_swing: not_found" in line for line in lines)
    assert ler.run([], http=FakeHttp.for_library(), out=lines.append) == 0


# ── dry run, candidates, the ledger ─────────────────────────────────────────────────────────────────────────────


def _tree_digest(paths):
    out = {}
    for p in paths:
        with open(p, "rb") as f:
            out[p] = hashlib.sha256(f.read()).hexdigest()
    return out


def test_dry_run_writes_nothing(tmp_path):
    watched = [os.path.join(ROOT, ler.LIBRARY_REL), os.path.join(ROOT, ler.LEDGER_REL), os.path.join(ROOT, ler.ALLOWLIST_REL)]
    before = _tree_digest(watched)
    prop = tmp_path / "p.json"
    prop.write_text(json.dumps({"review_id": "t", "proposals": [_add(), _set()]}))
    listing = sorted(os.listdir(tmp_path))

    def no_runner(*a, **k):
        raise AssertionError("dry run ran a subprocess")

    lines: list[str] = []
    rc = ler.run(["--proposals", str(prop), "--today", TODAY], http=FakeHttp.for_library(extra=[NEW]), out=lines.append, runner=no_runner)
    assert rc == 0
    assert _tree_digest(watched) == before
    assert sorted(os.listdir(tmp_path)) == listing
    assert any(line.startswith("--- a/config/exercise_library.json") for line in lines), "the dry run prints the diff"
    assert any("dry-run" in line for line in lines)
    # control: --out DOES write the proposal and the diff
    ler.run(
        ["--proposals", str(prop), "--today", TODAY, "--out", str(tmp_path / "o")], http=FakeHttp.for_library(extra=[NEW]), out=lines.append
    )
    assert sorted(os.listdir(tmp_path / "o")) == ["library.diff", "proposal.json"]
    assert _tree_digest(watched) == before


def _candidate(**over):
    x = {
        "key": "overhead_cable_extension_rope_test",
        "title": "Overhead Cable Triceps Extension (Rope, test)",
        "template_id": None,
        "template_note": "no Hevy template yet (test)",
        "target": {"primary": "triceps", "secondary": [], "region": "upper"},
        "family": "hypertrophy",
        "length_bias": "lengthened",
        "resistance_profile": "cable",
        "stability": "high",
        "joint_stress": {"spinal_load": "low", "shear": "low", "wrist": "low", "elbow": "moderate", "shoulder": "moderate"},
        "skill_complexity": "low",
        "equipment": ["cable_stack"],
        "hypertrophy": [{"target": "triceps_long_head", "citations": ["testerson2026_overhead"], "evidence_confidence": "rct_direct"}],
    }
    x.update(over)
    return {"op": "add_candidate", "candidate": x, "citations": ["testerson2026_overhead"], "rationale": "test", "abstract_read": True}


def test_a_new_candidate_enters_valid_with_rule_fallbacks():
    decided, _ = _decide([_add(), _candidate()])
    assert decided["rejected"] == [], decided["rejected"]
    after = ler.apply_review(LIB, decided)
    e = after["movements"]["overhead_cable_extension_rope_test"]
    row = e["hypertrophy"][0]
    assert e["source"] == "expansion" and e["fallbacks"] and row["evidence_confidence"] == "rct_direct"
    assert row["tier"] == row["rubric_tier"] == qr.rubric_tier(e, "triceps_long_head"), "the rubric derives a candidate's tier"
    assert xl.validate(after) == []
    fidx = xl.fallback_index(after)
    for k, mv in after["movements"].items():
        want = [{"movement_id": m, "reason": r} for m, r in xl.fallback_candidates(after, k, fidx)[: len(mv["fallbacks"])]]
        assert mv["fallbacks"] == want, k
    # must-fail: an unverified citation or no citation keeps the candidate out
    bad_http = FakeHttp.for_library()  # NEW is not served -> does not verify
    assert _decide([_add(), _candidate()], http=bad_http)[0]["accepted"]["candidates"] == []
    no_cite = _candidate()
    no_cite["citations"] = []
    assert _decide([no_cite])[0]["accepted"]["candidates"] == []
    derived = _candidate(fallbacks=[])
    assert _decide([_add(), derived])[0]["accepted"]["candidates"] == []
    tiered = _candidate()
    tiered["candidate"]["hypertrophy"][0]["tier"] = "S"  # #5857: a proposed tier is refused — the rubric derives it
    assert _decide([_add(), tiered])[0]["accepted"]["candidates"] == []


def test_the_builder_reapplies_the_ledger(monkeypatch):
    import build_exercise_library as b

    decided, _ = _decide([_add(), _set(), _candidate()])
    ledger = copy.deepcopy(reviews.EMPTY_LEDGER)
    ledger["reviews"].append(ler.ledger_record(decided))
    monkeypatch.setattr(b, "_LEDGER", ledger)
    assert "testerson2026_overhead" in b.library_citations()
    assert set(b.cur.CITATIONS) < set(b.library_citations())
    assert any(x["key"] == "overhead_cable_extension_rope_test" for x in b._expansion_list())
    mv = copy.deepcopy(LIB["movements"])
    assert reviews.apply_evidence_changes(mv, reviews.ledger_evidence_changes(ledger)) == []
    reviews.finalize_tiers(mv)
    row = _row({"movements": mv}, "bench_press_barbell", "chest")
    assert row["evidence_confidence"] == "rct_characteristic" and row["tier"] == row["rubric_tier"]
    assert reviews.apply_evidence_changes(mv, [{**decided["accepted"]["evidence_changes"][0], "movement": "nope"}]) == ["nope:chest"]


def test_the_committed_ledger_loads_and_is_consistent_with_the_library():
    ledger = reviews.load_ledger()
    assert "reviews" in ledger
    for cid, c in reviews.ledger_citations(ledger).items():
        assert LIB["citations"].get(cid) == c, f"ledger citation {cid} is not in the committed library"
    for t in reviews.ledger_evidence_changes(ledger):
        want = reviews.evidence_row(t)
        rows = LIB["movements"][t["movement"]]["hypertrophy"]
        assert any({k: r.get(k) for k in want} == want for r in rows), t
    for x in reviews.ledger_candidates(ledger):
        assert x["key"] in LIB["movements"]


# ── the PR: never merges, never pushes main ─────────────────────────────────────────────────────────────────────


def _lane(tmp_path):
    lane = tmp_path / "lane"
    (lane / "config").mkdir(parents=True)
    (lane / "deploy").mkdir()
    shutil.copy(os.path.join(ROOT, ler.LIBRARY_REL), lane / ler.LIBRARY_REL)
    shutil.copy(os.path.join(ROOT, ler.LEDGER_REL), lane / ler.LEDGER_REL)
    return str(lane)


class Recorder:
    def __init__(self, branch="issue-5778-library-evidence-review-t", remote_ok=True):
        self.calls: list[tuple[list[str], str | None]] = []
        self.branch = branch
        self.remote_ok = remote_ok

    def __call__(self, args, cwd=None, input=None, capture_output=True, text=True):
        self.calls.append((list(args), input))
        out = ""
        if args[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            out = self.branch
        elif args[:2] == ["git", "rev-parse"]:
            out = "a" * 40
        elif args[:2] == ["git", "ls-remote"]:
            out = ("a" * 40 if self.remote_ok else "b" * 40) + f"\trefs/heads/{self.branch}"
        elif args[:3] == ["gh", "pr", "create"]:
            out = "https://github.com/averagejoematt/life-platform/pull/1"
        return subprocess.CompletedProcess(args, 0, out, "")


def test_open_pr_pushes_the_lane_branch_and_never_merges(tmp_path):
    decided, _ = _decide([_add(), _set()])
    rec = Recorder()
    lane = _lane(tmp_path)
    url = ler.open_pr(decided, 5778, {}, [], runner=rec, make_lane=lambda n, s: lane, out=lambda s: None)
    assert url.endswith("/pull/1")
    cmds = [c for c, _ in rec.calls]
    assert not any("merge" in c for c in cmds)
    commit = next(c for c in cmds if c[:2] == ["bash", "deploy/agent_commit.sh"])
    assert commit[2] == "--push" and commit[4:] == [ler.LIBRARY_REL, ler.LEDGER_REL], "commits exactly the library + ledger"
    assert not any(c[:1] == ["git"] and c[1:2] == ["push"] for c in cmds), "the one landing path is agent_commit.sh --push"
    create = next((c, body) for c, body in rec.calls if c[:3] == ["gh", "pr", "create"])
    assert create[0][create[0].index("--base") + 1] == "main"
    body = create[1]
    assert "Refs #5778" in body and "Fixes" not in body
    assert attribution.trailer_forms(body) == [] and attribution.mention_forms(body) == []
    with open(os.path.join(lane, ler.LIBRARY_REL), encoding="utf-8") as f:
        assert _row(json.load(f), "bench_press_barbell", "chest")["evidence_confidence"] == "rct_characteristic"
    with open(os.path.join(lane, ler.LEDGER_REL), encoding="utf-8") as f:
        assert len(json.load(f)["reviews"]) == 1


def test_open_pr_refuses_main_a_merge_and_an_unlanded_push(tmp_path):
    decided, _ = _decide([_add(), _set()])
    with pytest.raises(SystemExit, match="refusing"):
        ler.open_pr(decided, 5778, {}, [], runner=Recorder(branch="main"), make_lane=lambda n, s: _lane(tmp_path), out=lambda s: None)
    with pytest.raises(SystemExit, match="push did not land"):
        ler.open_pr(
            decided, 5778, {}, [], runner=Recorder(remote_ok=False), make_lane=lambda n, s: _lane(tmp_path / "b"), out=lambda s: None
        )
    rec = Recorder()
    for args in (["gh", "pr", "merge", "1"], ["git", "push", "origin", "main"], ["git", "push", "origin", "HEAD:main"]):
        with pytest.raises(SystemExit, match="refusing"):
            ler._run(rec, args, cwd=str(tmp_path))
    assert rec.calls == [], "a refused command reached the runner"


def test_open_pr_needs_an_issue():
    assert ler.run(["--open-pr"], http=FakeHttp.for_library(), out=lambda s: None) == 2


def test_the_http_client_only_contacts_the_two_registries():
    for url in ("https://twitter.com/x", "https://example.substack.com/p/y", "https://www.google.com/search?q=x"):
        with pytest.raises(ValueError, match="refusing"):
            ler.urllib_get(url)


def test_discovery_is_a_reading_list_never_a_change():
    http = FakeHttp.for_library()

    def with_hits(url):
        if "esearch" in url:
            return 200, {"esearchresult": {"idlist": ["40000001", LIB["citations"]["kubo2019_squat_depth"]["pmid"]]}}
        if "esummary" in url and "40000001" in url:
            return 200, {"result": {"uids": ["40000001"], "40000001": _pubmed(NEW)}}
        return http(url)

    items = ler.discover(LIB, "2026-11-11", with_hits)
    assert [i["pmid"] for i in items] == ["40000001"], "an already-registered PMID is not re-listed"
    assert items[0]["status"].startswith("to_read")
    decided, _ = _decide([])
    assert not ler.has_changes(decided)
