"""#3615 box 4 — the voice sampler that could only see one cycle.

THE NEGATIVE CONTROL, AND WHY IT IS THE POINT

`voice_fidelity_harness._sample_recent_outputs` read `COACH#{id}/OUTPUT#` through
`with_phase_filter()` at its default (`include_pilot=False`) with `Limit=8`. DynamoDB
applies `Limit` BEFORE a `FilterExpression` — documented behaviour, not a quirk — so on
the day after a genesis, when the reset has stamped every recent coach row `phase=pilot`,
the query read eight archived rows, filtered all eight away, and returned ZERO passages.
Silently. A coach with twelve cycles of prose behind it looked exactly like a coach that
had never written a word, and the public scoreboard read `insufficient_data` for every
coach at n=3 against MIN_N_FOR_VERDICT=6.

The control below is the day-after-genesis fixture the acceptance criterion names: the
newest rows every coach has are ALL archived. It asserts two things that must both hold,
because either alone can pass for the wrong reason:

  1. the fixed sampler still returns SAMPLES_PER_COACH per coach, and a full run clears
     MIN_N_FOR_VERDICT;
  2. the MUTATION — the pre-#3615 semantics restored, filter on and lookback 8 — returns
     ZERO. A control that passes against the old code path proves nothing (#3594), so the
     mutation arm is the load-bearing half of this file.

The fake table is the WIRE, not a convenience: it parses the real
`boto3.dynamodb.conditions` key condition, sorts descending like `ScanIndexForward=False`,
applies `Limit` and only THEN applies any `FilterExpression` — the exact ordering that
produced the defect. A fixture that filtered before limiting would make the old code pass.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "coach"))

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import voice_fidelity_harness as vfh  # noqa: E402
from ai import voice_fidelity_core as vfc  # noqa: E402
from common.constants import EXPERIMENT_PHASE_CURRENT  # noqa: E402
from experiment.phase_filter import with_phase_filter as _real_with_phase_filter  # noqa: E402

PILOT = "pilot"  # what restart_intelligence_wipe.py stamps on an archived row (ADR-077)
COACHES = [
    "sleep_coach",
    "training_coach",
    "nutrition_coach",
    "mind_coach",
    "labs_coach",
    "glucose_coach",
    "explorer_coach",
    "recovery_coach",
]
PASSAGE = "A judgeable passage of coach prose. " * 12  # comfortably over MIN_PASSAGE_CHARS


# ══════════════════════════════════════════════════════════════════════════════
# the wire: a DynamoDB query that applies Limit BEFORE FilterExpression
# ══════════════════════════════════════════════════════════════════════════════
def _flatten(condition):
    """[(attr_name, operator, value)] from a real boto3 ConditionBase tree.

    Uses the public `get_expression()` shape rather than private attributes, so this
    walks the same structure boto3 serialises onto the wire.
    """
    out = []
    expr = condition.get_expression()
    operator = expr["operator"]
    values = list(expr["values"])
    if operator == "AND":
        for sub in values:
            out.extend(_flatten(sub))
        return out
    attr = values[0]
    out.append((attr.name, operator, values[1]))
    return out


class FakeTable:
    """Query semantics faithful to the two properties this defect turned on."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.queries = []
        self.written = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        conditions = _flatten(kwargs["KeyConditionExpression"])
        items = self.rows
        for name, operator, value in conditions:
            if operator == "=":
                items = [r for r in items if r.get(name) == value]
            elif operator == "begins_with":
                items = [r for r in items if str(r.get(name, "")).startswith(value)]
            else:  # pragma: no cover — the harness uses only these two
                raise AssertionError(f"unmodelled key operator {operator}")
        items = sorted(items, key=lambda r: r["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        # 1. Limit first — this is the ordering DynamoDB documents and the defect rode.
        limit = kwargs.get("Limit")
        if limit is not None:
            items = items[:limit]
        # 2. FilterExpression second, over what survived the Limit.
        if kwargs.get("FilterExpression"):
            phase_ok = kwargs["ExpressionAttributeValues"][":phase_experiment"]
            items = [r for r in items if r.get("phase") in (None, phase_ok)]
        return {"Items": items}

    def get_item(self, **kwargs):
        return {"Item": None}

    def put_item(self, Item):
        self.written.append(Item)
        # Written rows become readable, so the harness's strongly-consistent read-back of
        # its own just-written judgments is modelled rather than assumed away.
        self.rows = [r for r in self.rows if (r.get("pk"), r.get("sk")) != (Item.get("pk"), Item.get("sk"))]
        self.rows.append(dict(Item))


def _day_after_genesis_rows():
    """Every coach: its 12 newest OUTPUT# rows archived by the reset, older prose behind
    them. The shape of the live table on Day 1 of a cycle."""
    rows = []
    for coach in COACHES:
        for day in range(1, 13):  # 2026-09-01..12 — the archived block, newest first
            rows.append({"pk": f"COACH#{coach}", "sk": f"OUTPUT#2026-09-{day:02d}#brief", "content": PASSAGE, "phase": PILOT})
        for day in range(1, 13):  # 2026-08-01..12 — earlier cycles, also archived
            rows.append({"pk": f"COACH#{coach}", "sk": f"OUTPUT#2026-08-{day:02d}#brief", "content": PASSAGE, "phase": PILOT})
    return rows


def _install(monkeypatch, rows):
    table = FakeTable(rows)
    monkeypatch.setattr(vfh, "table", table)
    return table


# ══════════════════════════════════════════════════════════════════════════════
# the fixture has to be able to fail
# ══════════════════════════════════════════════════════════════════════════════
def test_the_fake_table_applies_limit_before_the_filter(monkeypatch):
    """If this ever stops being true the control below is decorative."""
    table = _install(monkeypatch, _day_after_genesis_rows())
    from boto3.dynamodb.conditions import Key

    filtered = table.query(
        **_real_with_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq("COACH#sleep_coach") & Key("sk").begins_with("OUTPUT#"),
                "ScanIndexForward": False,
                "Limit": 8,
            }
        )
    )
    assert filtered["Items"] == [], "the fixture filtered before limiting — it cannot reproduce the defect"
    unfiltered = table.query(
        KeyConditionExpression=Key("pk").eq("COACH#sleep_coach") & Key("sk").begins_with("OUTPUT#"),
        ScanIndexForward=False,
        Limit=8,
    )
    assert len(unfiltered["Items"]) == 8


# ══════════════════════════════════════════════════════════════════════════════
# THE NEGATIVE CONTROL
# ══════════════════════════════════════════════════════════════════════════════
def test_a_coach_whose_newest_rows_are_all_archived_still_yields_samples(monkeypatch):
    _install(monkeypatch, _day_after_genesis_rows())
    for coach in COACHES:
        samples = vfh._sample_recent_outputs(coach)
        assert len(samples) == vfh.SAMPLES_PER_COACH, f"{coach} starved on an archive of 24 judgeable rows"
        assert samples[0]["sample_date"] == "2026-09-12"  # newest first, archived or not
        assert samples[0]["sample_phase"] == PILOT, "an archive-sourced passage must be LABELLED as one"


def test_the_mutation_starves_restoring_the_pre_3615_semantics(monkeypatch):
    """The same fixture against the OLD code path: filter honoured, lookback 8 → zero.

    Mutating exactly the two things #3615 box 4 changed (the `include_pilot` bypass and
    the lookback) is what makes this a control rather than a tautology.
    """
    _install(monkeypatch, _day_after_genesis_rows())
    monkeypatch.setattr(vfh, "with_phase_filter", lambda kwargs, include_pilot=False: _real_with_phase_filter(kwargs))
    assert vfh._sample_recent_outputs("sleep_coach", lookback=8) == []


def test_the_sample_query_is_key_bounded_and_reads_no_page_twice(monkeypatch):
    table = _install(monkeypatch, _day_after_genesis_rows())
    vfh._sample_recent_outputs("sleep_coach")
    assert len(table.queries) == 1, "the sampler must stay one key-bounded query per coach"
    assert table.queries[0]["Limit"] == vfh.SAMPLE_LOOKBACK
    assert "FilterExpression" not in table.queries[0], "a FilterExpression puts Limit back in front of the filter"
    assert vfh.SAMPLE_LOOKBACK >= vfh.SAMPLES_PER_COACH * 8, "the lookback must survive a run of unjudgeable rows"


def test_short_passages_still_cannot_fill_the_sample(monkeypatch):
    """Widening the lookback must not widen what counts as judgeable."""
    rows = [{"pk": "COACH#mind_coach", "sk": f"OUTPUT#2026-09-{d:02d}", "content": "tiny", "phase": PILOT} for d in range(1, 21)]
    rows.append({"pk": "COACH#mind_coach", "sk": "OUTPUT#2026-06-01", "content": PASSAGE, "phase": PILOT})
    _install(monkeypatch, rows)
    samples = vfh._sample_recent_outputs("mind_coach")
    assert [s["sample_date"] for s in samples] == ["2026-06-01"]


# ══════════════════════════════════════════════════════════════════════════════
# the run-level control: n clears the verdict floor on the day after a genesis
# ══════════════════════════════════════════════════════════════════════════════
def test_a_run_on_the_day_after_a_genesis_clears_min_n_for_verdict(monkeypatch):
    table = _install(monkeypatch, _day_after_genesis_rows())

    from ai import budget_guard

    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    monkeypatch.setattr(vfh, "_load_candidates", lambda: [{"coach_id": c, "name": c, "domain": "d"} for c in COACHES])

    # A panel that always names the true author — the scoring math is pinned elsewhere
    # (test_voice_fidelity_545.py); what is under test here is how many judgments EXIST.
    current = {"coach": COACHES[0]}
    original = vfh._sample_recent_outputs

    def _tracking_sample(coach_id, *args, **kwargs):
        current["coach"] = coach_id
        return original(coach_id, *args, **kwargs)

    monkeypatch.setattr(vfh, "_sample_recent_outputs", _tracking_sample)
    monkeypatch.setattr(vfh, "_run_panel", lambda candidates, passage: [{"guess": current["coach"], "confidence": 0.9}] * 3)

    result = vfh.lambda_handler({"force": True}, None)

    assert result["new_samples"] == len(COACHES) * vfh.SAMPLES_PER_COACH
    assert result["cumulative_n"] >= vfc.MIN_N_FOR_VERDICT, "the day-after-genesis run must not read insufficient_data"
    assert result["verdict"] != "insufficient_data"

    judgments = [w for w in table.written if str(w.get("sk", "")).startswith("JUDGMENT#")]
    assert judgments and all(j["sample_phase"] == PILOT for j in judgments), "every judgment must carry its sample's phase"
    board = next(w for w in table.written if w["pk"] == vfh.SCOREBOARD_PK and w["sk"] == "latest")
    assert board["phases_sampled"] == [PILOT], "the scoreboard must state the span it was drawn from"
    assert EXPERIMENT_PHASE_CURRENT not in board["phases_sampled"]  # this fixture has no in-cycle prose at all
