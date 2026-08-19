"""
coach_sim_scoreboard.py — the standing scoreboard for the coach-chat sim harness (#2539).

WHY THIS MODULE EXISTS. ``scripts/coach_chat_sim.py`` + ``coach_sim_analyze.py`` can
measure whether a cold reader would call a coach's texting AI. What they could not do
was remember. The 2026-08-10 run produced a 64%-called-AI headline that lived in one
markdown file and a scratch ``metrics.json`` outside the repo; the next run would have
had nothing to compare against except a human re-reading prose. A baseline nobody can
read back is an impression, not a measure.

So this is the persistence + policy half of that harness, cloned deliberately from
``coach/voice_fidelity_harness.py``'s ``VOICEFIDELITY#scoreboard`` shape:

  * ``COACHSIM#scoreboard`` / ``latest``       — the most recent run, whole
  * ``COACHSIM#scoreboard`` / ``RUN#<date>``   — one immutable row per run, so the
                                                 trend is a query, not an archaeology dig
  * ``COACHSIM#scoreboard`` / ``LIMITATIONS``  — what this instrument cannot see,
                                                 stored beside the numbers rather than
                                                 in a doc that a reader of the numbers
                                                 will never open

The two harnesses are complements and the pairing is the point: voice-fidelity asks
whether the coaches are distinguishable FROM EACH OTHER, this one asks whether they are
distinguishable FROM A PERSON. Same storage shape, same cross-phase classification,
same "cumulative, never a fresh coin flip" discipline.

CROSS-PHASE (ADR-077). This measures the COACHING ENGINE's design — can a blind reader
tell the replies are generated — not a property of the current experiment run. It must
survive a reset exactly as ``VOICEFIDELITY#*`` does, so ``experiment/phase_taxonomy.py``
classifies the ``COACHSIM#`` pk prefix as CROSS_PHASE. The conversations it summarizes
are synthetic and were never stored at all (the sim is read-only by construction), so
there is no experiment-scoped record underneath it to disagree with.

NO SCHEDULE, ON PURPOSE. See ``CADENCE`` below — the cadence decision and the budget
reason it is not a per-PR CI gate are data in this module, not prose in a doc, because
the question "why doesn't this run on every PR?" is asked by whoever is reading the
scoreboard and wondering why it is three weeks stale.

Nothing here calls Bedrock. Nothing here writes outside the ``COACHSIM#`` pk.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

SCOREBOARD_PK = "COACHSIM#scoreboard"
LATEST_SK = "latest"
LIMITATIONS_SK = "LIMITATIONS"
RUN_SK_PREFIX = "RUN#"

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")


# ── The cadence decision (acceptance box 1) ──────────────────────────────────
#
# Written down as data so it travels with the scoreboard row and can be asserted on.
CADENCE: dict[str, Any] = {
    "mode": "on_demand",
    "trigger": (
        "Run the full corpus on demand around an area:coach-humanity change — once before the "
        "first PR in a batch lands and once after the batch is merged and deployed — so the claim "
        "each humanity issue makes is a delta against a stored number rather than an impression."
    ),
    "floor": (
        "If no area:coach-humanity work has shipped in a calendar month, run it anyway beside "
        "voice_fidelity_harness's monthly pass. The two measure orthogonal properties "
        "(distinguishable from each other vs. distinguishable from a person) and a scoreboard "
        "with one datapoint cannot show a trend."
    ),
    "command": "bash scripts/coach_sim_runall.sh <out-dir> && python3 scripts/coach_sim_analyze.py --runs <out-dir> --report <report.md>",
    "cost_usd_per_run": 3.73,  # measured 2026-08-10: $2.88 corpus + $0.85 panel
    "wall_clock_minutes": 25,
    "not_a_ci_gate_because": (
        "ADR-063/133: the AI ceiling is $150 base (a $200 dated window for August 2026 only, "
        "auto-reverting 2026-09-01) and the month is already projecting over it. At ~$3.73 and "
        "~25 minutes a run, gating every PR would spend more on measuring the coaches than on "
        "running them, and would trip the tier ladder into pausing the reader-facing narratives "
        "(band 2) to pay for a dev metric — exactly the audience ordering ADR-125 forbids. The "
        "LLM panel is therefore on-demand; the deterministic subset, which costs $0, is the part "
        "that can run unattended (see scripts/coach_sim_replay.py)."
    ),
    "deterministic_subset": {
        "runner": "scripts/coach_sim_replay.py",
        "cost_usd": 0.0,
        "posture": "advisory",
        "promotion_rule": (
            "ADR-108 pattern: advisory until the flag rate has been measured across enough runs to "
            "know the false-positive cost, then promoted to blocking by an explicit decision — never "
            "by default. It is advisory today and has never been armed."
        ),
    },
}


# ── The known limitations (acceptance box 4) ─────────────────────────────────
#
# These ride with every stored run. Prose in a findings doc is read once; a field on the
# row is read by whoever is about to quote the number.
KNOWN_LIMITATIONS: list[dict[str, str]] = [
    {
        "id": "subject_is_not_matthew",
        "severity": "high",
        "limitation": (
            "The simulated subject is not Matthew. It is a Haiku persona calibrated on his measured "
            "texting register (median 23 chars, range 2-126); it does not have his taste. This "
            "instrument can say a reply reads generated. It cannot say whether a reply landed."
        ),
    },
    {
        "id": "deterministic_layer_alone_is_insufficient",
        "severity": "high",
        "limitation": (
            "The deterministic layer alone would have missed the top finding. Rhetorical symmetry was "
            "25% of the judges' 2,404 free-text tells while the deterministic detector matched 9 times "
            "in 536 replies (#2537). The cheap metrics are a regression tripwire for signals already "
            "known; they do not discover the next one. Do not drop the LLM panel in favour of them."
        ),
    },
    {
        "id": "harness_tracks_its_call_site_or_it_measures_drift",
        "severity": "high",
        "limitation": (
            "Two fidelity bugs were found and fixed mid-build, both of which manufactured findings: "
            "the grounder armed without the current inbound message (the #2518 fix), and an empty "
            "transcript handed to the simulator as something to continue. Any change to the production "
            "assembly path needs a matching change here, kwarg by kwarg, or the harness measures its "
            "own drift and reports it as a coach defect."
        ),
    },
    {
        "id": "corpus_is_synthetic_and_private",
        "severity": "medium",
        "limitation": (
            "Run artifacts contain Matthew's real health facts (the AUTHORITATIVE FACTS block is real), "
            "so no corpus is committed to this public repo. What is committed is the corpus MANIFEST "
            "(sha256, conversation/reply counts) plus a small synthetic fixture for the $0 layer, so a "
            "later run can prove it replayed the same bytes without publishing them."
        ),
    },
]


# ── The 2026-08-10 baseline (acceptance box 2) ───────────────────────────────
#
# Transcribed from #2539's table, which is itself transcribed from
# docs/design/COACH_SIM_FINDINGS_2026_08_10.md. Not re-derived: re-running the corpus to
# recover a number already written down would cost ~$3.73 against a ceiling that is
# already projecting over.
BASELINE_2026_08_10: dict[str, Any] = {
    "run_date": "2026-08-10",
    "label": "baseline",
    "conversations": 120,
    "replies": 536,
    "coaches": 8,
    "panel": {
        "ai_verdict_pct": 64.0,
        "ai_verdict_n": 77,
        "ai_verdict_of": 120,
        "by_archetype_pct": {
            "identity_probe": 100.0,
            "day_in_life": 87.0,
            "terse_close": 12.0,
        },
        "free_text_tells": 2404,
    },
    "deterministic": {
        "em_dash_reply_rate": 0.77,
        "closing_question_rate": 0.20,
        "formatting_violations": 0,
        "median_reply_chars": 195,
        "median_reply_inbound_ratio": 3.1,
        "honest_answer_hits": 23,
        "honest_answer_of": 536,
    },
    "honesty_gate": {"sent": 516, "regenerated": 13, "held": 7},
    "cost_usd": {"corpus": 2.88, "panel": 0.85, "total": 3.73},
    "source": "docs/design/COACH_SIM_FINDINGS_2026_08_10.md (via #2539)",
}

# The deterministic metrics a later run is compared on. Kept as an explicit tuple so a
# renamed metric fails loudly at the diff site instead of silently reporting "no change".
DETERMINISTIC_TREND_KEYS = (
    "em_dash_reply_rate",
    "closing_question_rate",
    "formatting_violations",
    "median_reply_chars",
    "median_reply_inbound_ratio",
)

# Direction that counts as an improvement, per key. None = no opinion (context only).
_BETTER_WHEN_LOWER = {
    "em_dash_reply_rate": True,
    "closing_question_rate": True,
    "formatting_violations": True,
    "median_reply_chars": True,  # register asymmetry was finding #1 — shorter is more human here
    "median_reply_inbound_ratio": True,
}


def _table(table=None):
    """Lazy table handle. Passed-in table wins so tests never touch AWS and so a caller
    holding its own resource (the replay script) does not build a second one."""
    if table is not None:
        return table
    import boto3

    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


def build_run_record(
    run_date: str,
    *,
    panel: dict | None = None,
    deterministic: dict | None = None,
    honesty_gate: dict | None = None,
    conversations: int = 0,
    replies: int = 0,
    coaches: int = 0,
    cost_usd: dict | None = None,
    corpus_manifest: dict | None = None,
    label: str = "run",
    source: str = "",
) -> dict:
    """One scoreboard row. ``panel`` is optional by design: a $0 deterministic-only
    replay is a legitimate run and must be storable without inventing an AI verdict —
    ADR-104's behavioural-absence rule (an absent measurement is absent, never zero)."""
    record: dict[str, Any] = {
        "run_date": run_date,
        "label": label,
        "conversations": conversations,
        "replies": replies,
        "coaches": coaches,
        "deterministic": deterministic or {},
        "honesty_gate": honesty_gate or {},
        "cost_usd": cost_usd or {},
        "layers": ["deterministic"] + (["panel"] if panel else []),
        "source": source,
    }
    if panel:
        record["panel"] = panel
    if corpus_manifest:
        record["corpus_manifest"] = corpus_manifest
    return record


def write_run(record: dict, *, table=None, now=None, update_latest: bool = True) -> dict:
    """Persist one run to ``COACHSIM#scoreboard``.

    Writes the immutable ``RUN#<date>`` row, refreshes ``latest``, and (re)writes the
    LIMITATIONS row so the caveats can never drift behind the numbers they qualify.
    Floats are cast at the boundary — boto3 rejects ``float`` (see CLAUDE.md).
    """
    from common.numeric import floats_to_decimal  # bundled shared module (#1207)

    tbl = _table(table)
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    run_date = record["run_date"]
    body = {**record, "updated_at": stamp}

    tbl.put_item(Item=floats_to_decimal({"pk": SCOREBOARD_PK, "sk": f"{RUN_SK_PREFIX}{run_date}", **body}))
    if update_latest:
        tbl.put_item(Item=floats_to_decimal({"pk": SCOREBOARD_PK, "sk": LATEST_SK, **body}))
    tbl.put_item(
        Item=floats_to_decimal(
            {
                "pk": SCOREBOARD_PK,
                "sk": LIMITATIONS_SK,
                "limitations": KNOWN_LIMITATIONS,
                "cadence": CADENCE,
                "updated_at": stamp,
            }
        )
    )
    return body


def seed_baseline(*, table=None, now=None, overwrite: bool = False) -> dict:
    """Write the 2026-08-10 baseline if it is not already stored.

    Idempotent: re-running it does not clobber a real later run, because it writes the
    ``RUN#2026-08-10`` row and only claims ``latest`` when nothing newer exists.
    """
    tbl = _table(table)
    existing = read_run("2026-08-10", table=tbl)
    if existing and not overwrite:
        return {"skipped": "already_seeded", "run_date": "2026-08-10"}

    record = build_run_record(
        BASELINE_2026_08_10["run_date"],
        panel=BASELINE_2026_08_10["panel"],
        deterministic=BASELINE_2026_08_10["deterministic"],
        honesty_gate=BASELINE_2026_08_10["honesty_gate"],
        conversations=BASELINE_2026_08_10["conversations"],
        replies=BASELINE_2026_08_10["replies"],
        coaches=BASELINE_2026_08_10["coaches"],
        cost_usd=BASELINE_2026_08_10["cost_usd"],
        label=BASELINE_2026_08_10["label"],
        source=BASELINE_2026_08_10["source"],
    )
    latest = read_latest(table=tbl)
    newer_exists = bool(latest) and str(latest.get("run_date", "")) > record["run_date"]
    return write_run(record, table=tbl, now=now, update_latest=not newer_exists)


# The three reads below are written out rather than routed through one `_get(sk)` helper
# on purpose. tests/test_singleton_tombstone_guards.py keys its tombstone exemptions by
# (file, unparsed sk expression) so that an entry "survives line drift but dies with a
# refactor — forcing the reason to be re-argued, not inherited". A shared helper collapses
# all three sites onto the key `sk`, a bare local name that would go on matching through
# refactors that ought to invalidate it. Naming each constant at its own call site is what
# makes the exemption a statement about a specific row rather than about this file.
#
# Every one of them fail-softs to {}: absence is the designed state before the first seed
# (see the KNOWN_OPTIONAL entries in tests/test_ddb_key_contracts.py), and a read failure
# must not take a $0 replay run down with it. Callers report "no stored baseline" — they
# never substitute a zero.


def read_latest(*, table=None) -> dict:
    """The most recent stored run. ``{}`` before the first seed — never a fabricated zero."""
    try:
        return _table(table).get_item(Key={"pk": SCOREBOARD_PK, "sk": LATEST_SK}).get("Item") or {}
    except Exception:
        return {}


def read_run(run_date: str, *, table=None) -> dict:
    try:
        return _table(table).get_item(Key={"pk": SCOREBOARD_PK, "sk": f"{RUN_SK_PREFIX}{run_date}"}).get("Item") or {}
    except Exception:
        return {}


def read_limitations(*, table=None) -> dict:
    try:
        return _table(table).get_item(Key={"pk": SCOREBOARD_PK, "sk": LIMITATIONS_SK}).get("Item") or {}
    except Exception:
        return {}


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def delta_vs(current: dict, previous: dict) -> dict:
    """Deterministic-metric trend between two stored runs.

    A metric missing from EITHER side is reported as ``"unmeasured"`` rather than as a
    delta of zero (ADR-104): a run that did not measure em-dash rate has not held it flat.
    """
    cur = (current or {}).get("deterministic") or {}
    prev = (previous or {}).get("deterministic") or {}
    out: dict[str, Any] = {}
    for key in DETERMINISTIC_TREND_KEYS:
        c, p = _as_float(cur.get(key)), _as_float(prev.get(key))
        if c is None or p is None:
            out[key] = {"status": "unmeasured", "current": cur.get(key), "previous": prev.get(key)}
            continue
        change = round(c - p, 4)
        if change == 0:
            direction = "flat"
        elif _BETTER_WHEN_LOWER.get(key) is None:
            direction = "changed"
        else:
            direction = "better" if (change < 0) == _BETTER_WHEN_LOWER[key] else "worse"
        out[key] = {"status": "measured", "current": c, "previous": p, "change": change, "direction": direction}
    return {
        "from_run": (previous or {}).get("run_date"),
        "to_run": (current or {}).get("run_date"),
        "metrics": out,
    }
