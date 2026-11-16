"""tests/test_review_estate.py — the review's ESTATE SWEEP (owner ruling 2026-11-14; scripts/review_estate.py).

Three full reviews had sound verifiers and poor recall (0 of 4 withheld issues on 2026-11-14): the graders sampled
their clauses and never walked the estate their row owns. The instrument now gives every row a fixed, bounded list
of enumerations and refuses to count a row that skipped one. Pinned here: every panel row has sweeps; every sweep
names a real tool; the brief is not an answer key; the checker reds on an absent, unrun or uncounted sweep and
grandfathers runs that predate the rule; and the two enumerators written for it read the real tree.
"""

import json
import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import review_estate as RE  # noqa: E402


def _panel() -> set:
    with open(os.path.join(_REPO, "docs", "reviews", "anchors", "ANCHORS.json"), encoding="utf-8") as fh:
        return {r["lens"] for r in json.load(fh)["records"]}


def test_every_panel_row_has_a_bounded_sweep_list_and_no_row_is_invented():
    assert set(RE.ESTATE) == _panel(), "the estate registry and the sealed panel must name the same rows"
    for lens, sweeps in RE.ESTATE.items():
        assert 1 <= len(sweeps) <= 5, f"{lens}: {len(sweeps)} sweeps — bounded on purpose (a sweep is minutes, not a second review)"
        ids = [s.id for s in sweeps]
        assert len(set(ids)) == len(ids) and all(i.startswith(f"{lens}.E") for i in ids), ids
        for s in sweeps:
            assert len(s.estate) >= 10 and len(s.how) > 20 and len(s.report) > 20, s.id
            assert s.estate.startswith(("every ", "the ", "main")), f"{s.id}: a sweep names a SET to walk — {s.estate!r}"


def test_every_tool_a_sweep_names_exists():
    for sweeps in RE.ESTATE.values():
        for s in sweeps:
            for p in s.paths:
                assert os.path.exists(os.path.join(_REPO, p)), f"{s.id} depends on {p}, which does not exist"
            for script in re.findall(r"python3 ((?:scripts|deploy|qa|tests)/[\w./]+\.py)", s.how):
                assert os.path.exists(os.path.join(_REPO, script)), f"{s.id} runs {script}, which does not exist"


def test_the_brief_is_a_list_of_sets_to_walk_never_an_answer_key():
    """A sweep names a set, not a defect: no issue number, no file-and-line, nothing a withheld control could be
    recognised from (the controls stay blind — .claude/skills/review/SKILL.md Phase 2)."""
    for lens in RE.ESTATE:
        text = RE.brief(lens)
        assert not re.search(r"#\d{3,}", text), f"{lens}: the brief names an issue"
        assert not re.search(r"\.py:\d+", text), f"{lens}: the brief points at a line"
        for s in RE.ESTATE[lens]:
            assert s.id in text
        assert "not_run" in text and "INCOMPLETE" in text


def _row(lens, **over):
    return [{"sweep_id": s.id, "examined": 7, "anomalies": [], "evidence": "cmd → 7 rows", **over.get(s.id, {})} for s in RE.ESTATE[lens]]


def test_the_checker_reds_on_an_absent_unrun_or_uncounted_sweep():
    full = {
        "date": "2026-12-15",
        "lenses": {"cost": {"grade": "B", "estate_sweep": _row("cost")}, "reader": {"grade": "B", "estate_sweep": _row("reader")}},
    }
    assert RE.check_artifact(full) == [] and RE.incomplete_lenses(full) == set()
    absent = json.loads(json.dumps(full))
    absent["lenses"]["cost"]["estate_sweep"] = absent["lenses"]["cost"]["estate_sweep"][1:]
    assert RE.incomplete_lenses(absent) == {"cost"} and "cost.E1 is absent" in RE.check_artifact(absent)[0]
    unrun = {
        "date": "2026-12-15",
        "lenses": {"cost": {"estate_sweep": _row("cost", **{"cost.E2": {"status": "not_run", "reason": "no credentials"}})}},
    }
    assert RE.check_artifact(unrun) == ["cost: sweep cost.E2 was not run — no credentials"]
    uncounted = {"date": "2026-12-15", "lenses": {"cost": {"estate_sweep": _row("cost", **{"cost.E3": {"examined": 0}})}}}
    assert "states no count" in RE.check_artifact(uncounted)[0], "'none found' with no count of what was examined is not a result"
    none_at_all = {"date": "2026-12-15", "lenses": {"devex": {"grade": "A"}}}
    assert len(RE.check_artifact(none_at_all)) == len(RE.ESTATE["devex"])


def test_a_run_dated_before_the_rule_is_grandfathered():
    old = {"date": "2026-11-14", "lenses": {"cost": {"grade": "A-"}}}
    assert RE.required(old) is False and RE.incomplete_lenses(old) == set()
    assert RE.required({"date": RE.REQUIRED_FROM}) is True


def test_broad_means_a_whole_table_a_whole_bucket_or_everything():
    assert (
        RE._broad("*")
        and RE._broad("arn:aws:dynamodb:us-west-2:1:table/life-platform")
        and RE._broad("arn:aws:s3:::bucket")
        and RE._broad("arn:aws:s3:::bucket/*")
    )
    assert not RE._broad("arn:aws:dynamodb:us-west-2:1:table/life-platform/index/GSI1")
    assert not RE._broad("arn:aws:s3:::bucket/raw/whoop/*") and not RE._broad("arn:aws:sqs:us-west-2:1:queue")


def test_the_statement_enumerator_reads_every_role_policy_and_sees_conditions():
    rows = RE.iam_statements()
    assert len(rows) > 300, f"only {len(rows)} statements read — the enumerator has gone blind"
    assert len({r["where"].split(".")[0] for r in rows}) >= 5, "every role_policies module is walked"
    assert any(r["conditioned"] for r in rows) and any(r["unconditioned_broad"] for r in rows)
    reads = [r for r in rows if any(a.startswith(("dynamodb:Get", "dynamodb:Query")) for a in r["actions"])]
    assert reads, "read statements are enumerated too — a broad READ is exposure the write-only habit walks past"
    assert not any(r.get("unreadable") for r in rows), [r["where"] for r in rows if r.get("unreadable")]


def test_the_emitter_enumerator_crosses_handlers_with_grants():
    rows = RE.emitter_reach()
    assert len(rows) > 20, "only a handful of handlers reach an emitter — the import closure has gone blind"
    assert all(r["emitters_reached"] and r["role_policy"] for r in rows)
    assert all(r["dark"] == (not r["granted"]) for r in rows)
    assert any(
        len(r["emitters_reached"]) > 0 and not r["handler"].endswith(tuple(r["emitters_reached"])) for r in rows
    ), "a reach THROUGH an import is seen, not only a direct emit"
