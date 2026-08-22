"""tests/test_qa_window_derivation_2818.py — #2818: QA window expectations derive
from the producer's cron, and the mirror pair compute_stack.py ↔ qa_check_outputs.py
is asserted.

The timezone sub-class with no syntactic signature (#2670/#2780): both sides use the
PT helpers correctly, and the defect is a *schedule contract* — "which day may this
artifact honestly carry at this hour". #2670's fix hand-typed the compute cutoff as
10:30 PT beside a comment mirroring the CDK cron, which is right under PDT and wrong
under PST (16:40Z = 08:40 PST), with nothing asserting the literal pair agreed.

What this file pins:

  * **The pair.** Every `PRODUCER_CRON_MIRRORS` entry in qa_check_outputs matches
    that function's real schedule in cdk/stacks/ — read by AST through the #2845
    model generator (`generate_platform_model.extract_lambdas`), NEVER by importing
    aws_cdk (which is not installed in the test lanes and dies at collection).
  * **The SET.** check_doc_facts' sweep discovers the declaration from the tree (so
    any future producer-gate pair that uses the same dict name joins the gate with
    no enumeration), the sweep is non-vacuous (a drifted scratch mirror reds it, a
    correct one doesn't, the AnnAssign form is not invisible — the #1677 lesson),
    and the real repo pair is currently clean.
  * **The derivation.** The Pacific cutoff is computed FROM the mirror: a moved cron
    moves the window (injected, both directions), the window is correct under both
    PST and PDT (one UTC instant, two wall clocks), an evening-PT D-2 stays strict
    (the UTC-midnight wrap trap), and the derived cutoff stays before the scheduled
    qa-smoke sweep in the CDK — so a genuinely dead compute is still caught the
    same day, whatever season it is.

Runs pre-merge (`_PREMERGE_EXTRA_FILES`): its verdict is pure repo shape — a cron
move on either side must red BEFORE the merge, not after the QA window has silently
drifted a second time.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# qa_check_outputs reads S3_BUCKET at import time (conftest supplies fake creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")

from common.pacific_time import PACIFIC  # noqa: E402
from operational import qa_check_outputs as qco  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent
_QA_MODULE = _REPO / "lambdas" / "operational" / "qa_check_outputs.py"

_PRODUCER = "daily-metrics-compute"


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def facts():
    """scripts/check_doc_facts.py, loaded by path (scripts/ is not a package)."""
    return _load("scripts/check_doc_facts.py", "_facts_2818")


@pytest.fixture(scope="module")
def cdk_map(facts):
    """function_name -> [cron, ...] derived from cdk/stacks/ by AST (#2845/#2866)."""
    cmap = facts._cdk_cron_map()
    assert cmap, "the CDK cron map derived EMPTY — the AST ground truth is dead, nothing below can verify anything"
    return cmap


def _freeze_pacific(monkeypatch, frozen: datetime) -> None:
    from common import pacific_time

    monkeypatch.setattr(pacific_time, "pacific_now", lambda: frozen)


# ──────────────────────────────────────────────────────────────────────────────
# The pair: the declared mirror matches the CDK truth
# ──────────────────────────────────────────────────────────────────────────────


def test_every_declared_mirror_matches_the_cdk_schedule(cdk_map):
    """THE #2818 assertion: the literal pair compute_stack.py ↔ qa_check_outputs.py
    (and every future entry) agrees. A cron move in cdk/stacks/ that is not
    reflected in the mirror reds here, pre-merge."""
    assert qco.PRODUCER_CRON_MIRRORS, "the mirror dict emptied — the window derivation has no producer schedule to derive from"
    for name, cron in qco.PRODUCER_CRON_MIRRORS.items():
        assert name in cdk_map, (
            f"PRODUCER_CRON_MIRRORS names `{name}`, which has no resolvable cron in cdk/stacks/ — "
            "the producer was renamed/removed or its schedule went dynamic; update the mirror WITH the CDK change"
        )
        assert cron in cdk_map[name], (
            f"mirror for `{name}` claims {cron}, CDK schedules {cdk_map[name]} — "
            "a producer cron moved without its QA-window mirror; update qa_check_outputs.PRODUCER_CRON_MIRRORS in the same PR"
        )


def test_the_compute_producer_is_the_declared_pair(cdk_map):
    """#2670's specific pair, pinned by name so a silent re-keying of the dict to a
    different producer can't satisfy the generic loop above vacuously."""
    assert _PRODUCER in qco.PRODUCER_CRON_MIRRORS
    assert qco.PRODUCER_CRON_MIRRORS[_PRODUCER] in cdk_map[_PRODUCER]


# ──────────────────────────────────────────────────────────────────────────────
# The SET: check_doc_facts' sweep discovers, bites, and is currently clean
# ──────────────────────────────────────────────────────────────────────────────


def test_the_gate_sweep_discovers_the_real_declaration(facts):
    """Blindness detector (#2578's rule): the tree sweep must FIND the mirror in
    qa_check_outputs.py — an empty or elsewhere-pointing sweep means the gate went
    blind, which is worse than red."""
    mirrors = facts._collect_producer_mirrors(facts._scan_source_files())
    assert any(Path(src) == _QA_MODULE and name == _PRODUCER for src, _lineno, name, _cron in mirrors), (
        f"check_doc_facts' sweep did not discover the {_PRODUCER} mirror in {_QA_MODULE} — "
        "the #2818 gate can no longer see the declaration it exists to police"
    )


def test_the_real_repo_pair_is_clean(facts, cdk_map):
    mirrors = facts._collect_producer_mirrors(facts._scan_source_files())
    hits = facts._producer_mirror_hits(mirrors, cdk_map)
    assert hits == [], f"live producer-cron mirror(s) disagree with the CDK: {hits}"


def test_a_drifted_scratch_mirror_reds_the_gate(facts, cdk_map, tmp_path):
    """Inject a moved cron into the GUARD (the #1189 non-vacuous-scan lesson): a
    mirror claiming a cron the CDK does not schedule must be a hit, and the fixed
    version of the same file must be silence."""
    real_cron = qco.PRODUCER_CRON_MIRRORS[_PRODUCER]
    assert real_cron != "cron(40 17 * * ? *)", "pick a different synthetic drift — it collided with the real schedule"

    drifted = tmp_path / "scratch_qa_module.py"
    drifted.write_text(f'PRODUCER_CRON_MIRRORS = {{"{_PRODUCER}": "cron(40 17 * * ? *)"}}\n', encoding="utf-8")
    hits = facts._producer_mirror_hits(facts._collect_producer_mirrors([drifted]), cdk_map)
    assert len(hits) == 1 and _PRODUCER in hits[0] and "cron(40 17 * * ? *)" in hits[0]

    fixed = tmp_path / "scratch_qa_module_fixed.py"
    fixed.write_text(f'PRODUCER_CRON_MIRRORS = {{"{_PRODUCER}": "{real_cron}"}}\n', encoding="utf-8")
    assert facts._producer_mirror_hits(facts._collect_producer_mirrors([fixed]), cdk_map) == []


def test_a_mirror_naming_a_ghost_producer_reds_the_gate(facts, cdk_map, tmp_path):
    """A renamed/removed producer is drift too: the mirror then describes a schedule
    contract with nothing on the other end."""
    ghost = tmp_path / "scratch_ghost.py"
    ghost.write_text('PRODUCER_CRON_MIRRORS = {"no-such-function-2818": "cron(0 12 * * ? *)"}\n', encoding="utf-8")
    hits = facts._producer_mirror_hits(facts._collect_producer_mirrors([ghost]), cdk_map)
    assert len(hits) == 1 and "no-such-function-2818" in hits[0]


def test_the_annassign_form_is_not_invisible(facts, tmp_path):
    """#1677's lesson replayed for this sweep: annotating the dict turns Assign into
    AnnAssign, and a walk matching only the former goes BLIND rather than red."""
    ann = tmp_path / "scratch_ann.py"
    ann.write_text(f'PRODUCER_CRON_MIRRORS: dict[str, str] = {{"{_PRODUCER}": "cron(1 2 * * ? *)"}}\n', encoding="utf-8")
    mirrors = facts._collect_producer_mirrors([ann])
    assert [(n, c) for _s, _l, n, c in mirrors] == [(_PRODUCER, "cron(1 2 * * ? *)")]


# ──────────────────────────────────────────────────────────────────────────────
# The derivation: the window is computed FROM the mirror
# ──────────────────────────────────────────────────────────────────────────────


def test_cron_parser_reads_minute_then_hour():
    assert qco._cron_utc_hhmm("cron(40 16 * * ? *)") == (16, 40)
    assert qco._cron_utc_hhmm("cron(30 18 ? * * *)") == (18, 30)


def test_cron_parser_fails_loudly_on_a_non_fixed_schedule():
    """A mirror that stops being a daily fixed-UTC cron must not quietly become a
    garbage window."""
    with pytest.raises(ValueError):
        qco._cron_utc_hhmm("cron(0 {WHOOP_HOURS} * * ? *)")


def test_the_derived_window_preserves_the_2670_behavior_under_pdt(monkeypatch):
    """The #2670 boundary, now derived: 16:40Z + 50m = 10:30 PDT. 08:45 (the live
    false-FAIL time) is inside the honest window; 11:30 (the old scheduled sweep
    hour) is not."""
    _freeze_pacific(monkeypatch, datetime(2026, 8, 16, 8, 45, tzinfo=PACIFIC))
    assert qco._before_compute_window() is True
    _freeze_pacific(monkeypatch, datetime(2026, 8, 16, 11, 30, tzinfo=PACIFIC))
    assert qco._before_compute_window() is False


def test_a_moved_cron_moves_the_window(monkeypatch):
    """Inject a moved cron into the DERIVATION: the same wall-clock instant flips
    verdict when the producer's schedule moves — the window FOLLOWS the cron
    instead of waiting for a human to re-mirror it."""
    frozen = datetime(2026, 7, 15, 10, 45, tzinfo=PACIFIC)
    _freeze_pacific(monkeypatch, frozen)
    assert qco._before_compute_window() is False, "10:45 PDT is past the real 10:30 PDT cutoff"

    monkeypatch.setattr(qco, "PRODUCER_CRON_MIRRORS", {_PRODUCER: "cron(15 18 * * ? *)"})
    cutoff = qco._compute_cutoff_pt()
    assert (cutoff.hour, cutoff.minute) == (12, 5), "18:15Z + 50m = 19:05Z = 12:05 PDT"
    assert qco._before_compute_window() is True, "the window did not follow the moved cron — the #2818 defect is back"


def test_dst_boundary_one_utc_instant_two_wall_clocks(monkeypatch):
    """The producer fires at a fixed UTC instant; the honest window must close at
    that instant in BOTH seasons. Under PST the derived cutoff is 09:30 — the
    hand-typed 10:30 stayed lax for an extra hour all winter."""
    _freeze_pacific(monkeypatch, datetime(2026, 7, 15, 9, 0, tzinfo=PACIFIC))
    pdt = qco._compute_cutoff_pt()
    assert (pdt.hour, pdt.minute) == (10, 30)
    assert pdt.utcoffset() == timedelta(hours=-7)

    _freeze_pacific(monkeypatch, datetime(2026, 1, 15, 9, 0, tzinfo=PACIFIC))
    pst = qco._compute_cutoff_pt()
    assert (pst.hour, pst.minute) == (9, 30)
    assert pst.utcoffset() == timedelta(hours=-8)

    for cutoff in (pdt, pst):
        as_utc = cutoff.astimezone(timezone.utc)
        assert (as_utc.hour, as_utc.minute) == (17, 30), "the cutoff drifted off the producer's fixed-UTC fire time + slack"


def test_dst_boundary_window_verdicts_follow_the_seasonal_cutoff(monkeypatch):
    """Either side of the derived PST cutoff (09:30 PST = 17:30Z). The hand-typed
    10:30 would have called BOTH of these 'inside the window' all winter."""
    _freeze_pacific(monkeypatch, datetime(2026, 1, 15, 9, 15, tzinfo=PACIFIC))
    assert qco._before_compute_window() is True, "09:15 PST is 17:15Z — still inside the producer's runtime+slack window"
    _freeze_pacific(monkeypatch, datetime(2026, 1, 15, 9, 45, tzinfo=PACIFIC))
    assert qco._before_compute_window() is False, "09:45 PST is 17:45Z — past the derived cutoff; D-2 is now real staleness"


def test_evening_pt_d2_stays_strict(monkeypatch):
    """The UTC-midnight wrap trap: 19:00 PDT is 02:00Z *tomorrow* — a naive
    UTC-clock comparison against 17:30Z would read it as 'before the cutoff' and
    excuse a dead compute all evening. The Pacific-frame comparison must not."""
    _freeze_pacific(monkeypatch, datetime(2026, 7, 15, 19, 0, tzinfo=PACIFIC))
    assert qco._before_compute_window() is False


def test_the_derived_cutoff_stays_before_the_scheduled_sweep(cdk_map):
    """Ordering invariant, from the CDK truth on BOTH sides: the honest-D-2 window
    closes before the scheduled qa-smoke sweep fires (fixed UTC, so this holds in
    both seasons) — otherwise the sweep loses its ability to catch a genuinely
    dead compute the same day."""
    ph, pm = qco._cron_utc_hhmm(qco.PRODUCER_CRON_MIRRORS[_PRODUCER])
    cutoff_minutes = ph * 60 + pm + qco._COMPUTE_SLACK_MINUTES
    sweep_crons = cdk_map.get("life-platform-qa-smoke")
    assert sweep_crons, "the qa-smoke sweep has no resolvable CDK cron — the ordering invariant has nothing to hold against"
    for cron in sweep_crons:
        sh, sm = qco._cron_utc_hhmm(cron)
        assert cutoff_minutes < sh * 60 + sm, (
            f"derived cutoff ({cutoff_minutes}m UTC) is not before the scheduled sweep ({cron}) — "
            "either the producer moved later or the sweep moved earlier; re-derive _COMPUTE_SLACK_MINUTES"
        )
