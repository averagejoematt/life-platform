"""tests/pair_contract_registry.py — the #2847 seed set of enrolled producer/consumer pairs.

Every entry drives the REAL shipped producer to get a REAL payload and hands that
payload to the REAL shipped consumer. The only thing stubbed is TRANSPORT — a fake
``table`` / ``s3_client`` that captures the item the producer handed it, or answers
the producer's own input query. Nothing here hand-writes a payload: a hand-written
payload agrees with the consumer by construction and is exactly the
fixture-not-the-wire defect this registry exists to catch (see ``tests/pair_contract.py``).

Enrolling a pair is ONE ``register(PairContract(...))`` call. The framework, the
mutation harness and the coverage ratchet are in ``tests/pair_contract.py`` and
``tests/test_pair_contract_sweep_2847.py``; nothing else needs editing.

Seeded 2026-08-24 with six pairs spanning four wire kinds:

  * a stamped sub-document on a compute record  (#3049 / DIL-024 input_manifest)
  * a ledger row                                (DIL-025 send_ledger / email_log)
  * three DDB partitions                        (computed_metrics, engagement_state, adaptive_mode)
  * an S3 artifact                              (generated/public_stats.json)
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAMBDAS = os.path.join(_REPO, "lambdas")
if _LAMBDAS not in sys.path:
    sys.path.insert(0, _LAMBDAS)

from pair_contract import Mutation, PairContract, register  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
# Transport stand-ins. These fake the WIRE, never the SHAPE — every field value
# that reaches a consumer below came out of a real producer.
# ══════════════════════════════════════════════════════════════════════════════


class CapturingTable:
    """Captures every ``put_item`` the producer issues. The captured Item IS the payload."""

    def __init__(self):
        self.items = []

    def put_item(self, Item, **_kw):  # noqa: N803 — boto3's own kwarg casing
        self.items.append(dict(Item))
        return {}

    def get_item(self, Key=None, **_kw):  # noqa: N803
        # #3443: store_computed_metrics reads the existing record before its
        # from-scratch re-put (the co-owned acwr_* carry). An empty read is the
        # ordinary first-write-of-the-day shape.
        return {}

    def by_sk(self, sk):
        for item in self.items:
            if item.get("sk") == sk:
                return item
        return None


class CannedQueryTable:
    """Answers the producer's own INPUT query with a canned row.

    Stubbing an input is legitimate — the contract under test is the producer's
    OUTPUT. (A canned input that made the output shape different from production
    would be the real hazard; these rows are the ordinary shape of a `DATE#` row.)
    """

    def __init__(self, items):
        self._items = [dict(i) for i in items]

    def query(self, **_kw):
        return {"Items": [dict(i) for i in self._items]}


class LedgerTable:
    """A DDB stand-in that honours pk equality — enough for the two reads the
    send-ledger consumers actually issue, and enough that a mutated ``pk``
    genuinely strands the row instead of being waved through."""

    def __init__(self, items=()):
        self.items = [dict(i) for i in items]

    def put_item(self, Item, **_kw):  # noqa: N803
        self.items.append(dict(Item))
        return {}

    def query(self, **kw):
        pk = (kw.get("ExpressionAttributeValues") or {}).get(":pk")
        rows = [dict(i) for i in self.items if i.get("pk") == pk]
        rows.sort(key=lambda i: str(i.get("sk", "")), reverse=not kw.get("ScanIndexForward", True))
        limit = kw.get("Limit")
        return {"Items": rows[:limit] if limit else rows}


class CapturingS3:
    """Captures the object body the producer wrote."""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **_kw):  # noqa: N803
        self.objects[Key] = Body
        return {}


def _in_cycle_day(offset=2):
    """A day inside the CURRENT experiment cycle, derived from live genesis.

    Never a literal: ``build_canonical_facts`` withholds every observed field on a
    pre-genesis record (#2113), so a hard-coded date would silently hollow this
    registry out on the next reset — the #2376 dated-fixture timebomb class.
    """
    from common.constants import EXPERIMENT_START_DATE

    return (date.fromisoformat(EXPERIMENT_START_DATE) + timedelta(days=offset)).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# PAIR 1 — the input manifest (#3049 / DIL-024)
#   common.input_manifest.build_input_manifest  ->  web.site_api_character._public_input_manifest
# ══════════════════════════════════════════════════════════════════════════════


def _produce_input_manifest():
    from common.input_manifest import attach_input_manifest, build_input_manifest

    day = _in_cycle_day()
    now = datetime.fromisoformat(day + "T09:00:00+00:00")
    manifest = build_input_manifest(
        ["whoop", "withings"],
        table=CannedQueryTable([{"sk": f"DATE#{day}"}]),
        user_id="matthew",
        today_iso=day,
        now=now,
    )
    # The wire the consumer actually reads is the STAMPED compute record, not the
    # bare manifest — attach_input_manifest is the second half of the producer.
    return attach_input_manifest({"pk": "USER#matthew#SOURCE#computed_metrics", "sk": f"DATE#{day}", "date": day}, manifest)


def _consume_input_manifest(record):
    from web.site_api_character import _public_input_manifest

    return _public_input_manifest(record)


def _agree_input_manifest(produced, consumed):
    manifest = produced["input_manifest"]
    assert consumed is not None, "the character page projected nothing from a stamped record"
    assert consumed["status"] == manifest["status"]
    assert consumed["as_of_day"] == manifest["as_of_day"]
    assert set(consumed["sources"]) == set(manifest["sources"]), "the reader lost or invented a declared input source"


register(
    PairContract(
        name="input_manifest -> character page projection",
        producer="common.input_manifest::build_input_manifest",
        consumer="web.site_api_character::_public_input_manifest",
        partition="computed_metrics",
        produce=_produce_input_manifest,
        consume=_consume_input_manifest,
        agree=_agree_input_manifest,
        mutations=(
            Mutation(("input_manifest", "status"), "drop", why="the manifest verdict the reader republishes"),
            Mutation(("input_manifest", "as_of_day"), "drop", why="the Pacific day the sheet is stamped as-of"),
            Mutation(("input_manifest", "sources"), "rename", to="inputs", why="the per-source block the reader iterates"),
            Mutation(("input_manifest", "sources", "whoop", "latest_day"), "drop", why="a per-source field, one level down"),
        ),
        note=(
            "#3049 / DIL-024. The reader is a fail-closed allowlist projection, so a producer rename "
            "degrades to nulls rather than an error — silent by construction, which is why it needs a pair test."
        ),
    )
)


# ══════════════════════════════════════════════════════════════════════════════
# PAIR 2 — the send ledger row (DIL-025)
#   common.send_ledger.record_sent  ->  common.send_ledger.already_sent
# ══════════════════════════════════════════════════════════════════════════════

#: The one sender + period this pair drives. `record_sent`/`already_sent` are
#: sender-agnostic; the id only has to be a real one.
_LEDGER_SENDER = "daily_brief"


def _produce_send_ledger_row():
    from common.send_ledger import record_sent

    table = CapturingTable()
    # The send instant is derived from the live cycle, never a literal epoch — a
    # hard-coded one drifts a year out of the period_key it is recorded against.
    sent_at = datetime.fromisoformat(_in_cycle_day() + "T17:00:00+00:00")
    record_sent(table, _LEDGER_SENDER, _in_cycle_day(), now=int(sent_at.replace(tzinfo=timezone.utc).timestamp()))
    assert table.items, "record_sent wrote nothing — it swallows its own write failures by design"
    return table.items[0]


def _consume_send_ledger_row(row):
    from common.send_ledger import already_sent
    from web.site_api_status import USER_PREFIX

    table = LedgerTable([row])
    # Consumer A — the replay guard (DIL-025). Fails OPEN on a read error, so a
    # broken pk shows up as "not sent" rather than as an exception.
    guard = already_sent(table, _LEDGER_SENDER, _in_cycle_day())
    # Consumer B — /api/status's per-sender freshness row. Its `_last_sync` is a
    # closure inside `site_api_status.status()` and cannot be imported, so this
    # mirrors its two load-bearing derivations (the `USER#…#SOURCE#email_log#<id>`
    # partition and the `DATE#`-prefixed sk it slices). The mirror is pinned to the
    # real source text by `test_status_page_email_log_derivation_is_still_the_mirrored_one`
    # in the sweep — without that pin this half would be a fixture, not the wire.
    status_pk = f"{USER_PREFIX}email_log#{_LEDGER_SENDER}"
    sk = str(row.get("sk") or "")
    last_sync = sk.replace("DATE#", "")[:10] if row.get("pk") == status_pk and sk.startswith("DATE#") else None
    return {"replay_guard_sees_it": guard, "status_page_last_sync": last_sync}


def _agree_send_ledger_row(produced, consumed):
    assert consumed["replay_guard_sees_it"] is True, "the writer's own row is invisible to the replay guard"
    assert consumed["status_page_last_sync"] == produced["sk"].replace("DATE#", "")[:10]


register(
    PairContract(
        name="send_ledger row -> replay guard + status page",
        producer="common.send_ledger::record_sent",
        consumer="common.send_ledger::already_sent",
        partition=None,  # email_log is not in the ADR-077 partition census
        produce=_produce_send_ledger_row,
        consume=_consume_send_ledger_row,
        agree=_agree_send_ledger_row,
        mutations=(
            Mutation(("period_key",), "drop", why="the idempotency key the guard matches on"),
            Mutation(("pk",), "retype", to="USER#matthew#SOURCE#email_log#renamed", why="the partition both readers key on"),
            Mutation(("sk",), "retype", to="SENT#2026-08-19", why="the DATE#-prefixed sk the status page slices"),
        ),
        note=(
            "DIL-025. Nine other senders write this same row WITHOUT `period_key` "
            "(weekly_digest, monday_compass, anomaly_detector, …) — for those the guard structurally "
            "cannot fire. #3113 is enrolling them; this pair pins the shape they are converging on."
        ),
    )
)


# ══════════════════════════════════════════════════════════════════════════════
# PAIR 3 — computed_metrics -> the canonical facts every coach grounds on
#   compute.daily_metrics_compute_lambda.store_computed_metrics
#     -> experiment.canonical_facts.build_canonical_facts
# ══════════════════════════════════════════════════════════════════════════════


def _produce_computed_metrics(monkeypatch=None):
    from compute import daily_metrics_compute_lambda as dmc

    day = _in_cycle_day()
    table = CapturingTable()
    real_table = dmc.table
    dmc.table = table
    try:
        dmc.store_computed_metrics(
            day,
            88.0,
            "B+",
            {"sleep": 90.0, "nutrition": 80.0},
            {"sleep": {"hours": 7.4}},
            72.0,
            "green",
            {"tier0_streak": 5, "tier01_streak": 3, "vice_streaks": {"alcohol": 12}},
            -8.0,
            41.0,
            39.0,
            2.5,
            201.4,
            203.0,
            201.0,
            weight_traj={"weekly_rate_lbs": -1.2, "rate_provisional": False},
            vitals={
                "recovery_pct": 61.0,
                "hrv_ms": 42.0,
                "rhr_bpm": 55.0,
                "protein_g_avg": 168.0,
                "protein_g_target": 190.0,
                "protein_g_floor": 150.0,
            },
        )
    finally:
        dmc.table = real_table
    assert table.items, "store_computed_metrics refused the write (validator?) — no payload to contract on"
    return table.items[0]


def _consume_computed_metrics(item):
    from experiment.canonical_facts import build_canonical_facts
    from web.site_api_common import _decimal_to_float

    return build_canonical_facts(_decimal_to_float(item))


def _agree_computed_metrics(produced, consumed):
    assert consumed["as_of"] == produced["date"]
    assert consumed["facts_are_pre_genesis"] is False, "the seeded day fell outside the live cycle — the fixture, not the code, drifted"
    for canonical, written in (
        ("recovery_pct", "recovery_pct"),
        ("hrv_ms", "hrv_ms"),
        ("protein_g_avg", "protein_g_avg"),
        ("latest_weight", "latest_weight"),
        ("weekly_rate_lbs", "weekly_rate_lbs"),
    ):
        assert consumed[canonical] is not None, f"canonical fact {canonical!r} is None although the producer wrote {written!r}"


register(
    PairContract(
        name="computed_metrics -> canonical facts",
        producer="compute.daily_metrics_compute_lambda::store_computed_metrics",
        consumer="experiment.canonical_facts::build_canonical_facts",
        partition="computed_metrics",
        produce=_produce_computed_metrics,
        consume=_consume_computed_metrics,
        agree=_agree_computed_metrics,
        mutations=(
            Mutation(("recovery_pct",), "drop", why="the vitals trio's headline number"),
            Mutation(
                ("protein_g_avg",), "rename", to="avg_7d_g", why="#1919's real historical rename — the key drifted, the window did not"
            ),
            Mutation(("weekly_rate_lbs",), "drop", why="the weight-trend rate the ask surface reads"),
            # NOT a drop: `_record_date` legitimately falls back to the sk, so dropping
            # `date` is a no-op the consumer is RIGHT to absorb. Skewing it is the real
            # disagreement — it drives the #2113 pre-genesis clamp, which withholds
            # every observed fact.
            Mutation(("date",), "retype", to="2020-01-01", why="the day the facts describe, which the pre-genesis clamp keys on"),
        ),
        note=(
            "canonical_facts' own docstring says 'the field names here MUST match what it writes'. "
            "The runtime `ingestion_validator` schema covers only 6 of the 10 numeric fields, so a rename "
            "of `latest_weight` or `weekly_rate_lbs` passes every existing gate."
        ),
    )
)


# ══════════════════════════════════════════════════════════════════════════════
# PAIR 4 — engagement_state -> /api/presence
#   content.engagement_core.compute_presence (+ adaptive_mode_lambda.store_engagement_state)
#     -> web.site_api_freshness.presence
# ══════════════════════════════════════════════════════════════════════════════


def _produce_engagement_state():
    from compute import adaptive_mode_lambda as amode
    from content.engagement_core import compute_presence

    day = _in_cycle_day(offset=12)
    quiet_since = (date.fromisoformat(day) - timedelta(days=9)).isoformat()
    signal = compute_presence(
        day,
        {"nutrition": [quiet_since], "training_notes": [quiet_since]},
        wearable_latest={"whoop": day},
        experiment_start=_in_cycle_day(offset=0),
    )
    table = CapturingTable()
    real_table = amode.table
    amode.table = table
    try:
        amode.store_engagement_state(day, signal)
    finally:
        amode.table = real_table
    record = table.by_sk("STATE#current")
    assert record is not None, "store_engagement_state did not write the STATE#current singleton the site reads"
    return record


def _consume_engagement_state(record):
    from web import site_api_data, site_api_freshness as freshness

    class _Singleton:
        def get_item(self, Key, **_kw):  # noqa: N803
            return {"Item": dict(record)} if record.get("sk") == Key.get("sk") and record.get("pk") == Key.get("pk") else {}

    # `_g` is the facade's injectable state. `_ENGAGEMENT_CHANNELS` is taken from the
    # module that really owns it (site_api_data) rather than rebuilt here — the channel
    # set + labels must be the engine's own, which is the point of that indirection.
    resp = freshness.presence(_g={"table": _Singleton(), "_ENGAGEMENT_CHANNELS": site_api_data._ENGAGEMENT_CHANNELS})
    # The consumer's real output is the serialized HTTP body a reader receives —
    # unwrapping to the pre-serialization dict would skip the JSON round-trip the
    # wire actually performs (Decimals that never serialize are a real failure mode).
    return json.loads(resp["body"])


def _agree_engagement_state(produced, consumed):
    assert consumed["available"] is True, "the site could not see the record the compute lambda just wrote"
    assert consumed["presence_class"] == produced["presence_class"]
    assert consumed["gap_days"] == produced["gap_days"]
    assert consumed["as_of"] == produced["date"]


register(
    PairContract(
        name="engagement_state -> /api/presence",
        producer="content.engagement_core::compute_presence",
        consumer="web.site_api_freshness::presence",
        partition="engagement_state",
        produce=_produce_engagement_state,
        consume=_consume_engagement_state,
        agree=_agree_engagement_state,
        mutations=(
            Mutation(("presence_class",), "drop", why="the headline class; the reader DEFAULTS it to 'present' when absent"),
            Mutation(("gap_days",), "drop", why="the canonical lag-adjusted quiet stretch"),
            Mutation(("last_food_log_date",), "drop", why="published as `last_log_date` — a rename across the wire"),
            Mutation(("date",), "rename", to="as_of", why="the reader publishes `as_of` FROM `date`; the two names must not swap"),
        ),
        note=(
            "The reader defaults `presence_class` to 'present' on an absent field — a producer rename "
            "reads as 'Matthew is fine' rather than as an error. Exactly the cycle-4 failure "
            "(#914: fourteen silent days no standing surface showed)."
        ),
    )
)


# ══════════════════════════════════════════════════════════════════════════════
# PAIR 5 — adaptive_mode -> the /api/ask grounding reads
#   compute.adaptive_mode_lambda.store_adaptive_mode
#     -> web.site_api_ai_context._ask_fetch_computed_reads
# ══════════════════════════════════════════════════════════════════════════════


def _produce_adaptive_mode():
    from compute import adaptive_mode_lambda as amode

    day = _in_cycle_day()
    table = CapturingTable()
    real_table = amode.table
    amode.table = table
    try:
        amode.store_adaptive_mode(
            day,
            {
                "engagement_score": 74,
                "brief_mode": "standard",
                "mode_label": "Steady",
                "factors": {"logging": "5 of 7 days", "training": "3 sessions"},
                "component_scores": {"logging": 40, "training": 34},
            },
        )
    finally:
        amode.table = real_table
    assert table.items, "store_adaptive_mode refused the write — no payload to contract on"
    return table.items[0]


def _consume_adaptive_mode(item):
    from web import site_api_ai_context as ctx, site_api_ai_lambda as ai

    class _EmptyTable:
        def get_item(self, **_kw):
            return {}

        def query(self, **_kw):
            return {"Items": []}

    real_latest, real_table = ai._latest_item, ctx._table
    ai._latest_item = lambda source, **_kw: dict(item) if source == "adaptive_mode" else {}
    ctx._table = lambda: _EmptyTable()
    try:
        return (ctx._ask_fetch_computed_reads() or {}).get("adaptive_mode")
    finally:
        ai._latest_item, ctx._table = real_latest, real_table


def _agree_adaptive_mode(produced, consumed):
    assert consumed is not None, "the ask surface dropped the adaptive-mode read entirely"
    assert consumed["label"] == produced["mode_label"]
    assert consumed["score"] == produced["engagement_score"]
    assert set(consumed["factors"]) == set(produced["factors"])


register(
    PairContract(
        name="adaptive_mode -> /api/ask grounding reads",
        producer="compute.adaptive_mode_lambda::store_adaptive_mode",
        consumer="web.site_api_ai_context::_ask_fetch_computed_reads",
        partition="adaptive_mode",
        produce=_produce_adaptive_mode,
        consume=_consume_adaptive_mode,
        agree=_agree_adaptive_mode,
        mutations=(
            Mutation(("mode_label",), "drop", why="the whole block is gated on this key's truthiness"),
            Mutation(("factors",), "rename", to="reasons", why="the platform's own stated reasons, published verbatim"),
            Mutation(("engagement_score",), "drop", why="the score beside the label"),
        ),
        note=(
            "The runtime `ingestion_validator` schema for adaptive_mode requires pk/sk/date/"
            "engagement_score/brief_mode/computed_at — it does NOT require `mode_label` or `factors`, "
            "and `mode_label` is the key the entire consumer block is gated on. Every AI answer "
            "loses its precomputed 'what drove today' silently."
        ),
    )
)


# ══════════════════════════════════════════════════════════════════════════════
# PAIR 6 — generated/public_stats.json -> the fingerprint broadcast projection
#   content.site_writer.write_public_stats  ->  content.fingerprint_broadcast.project_public
# ══════════════════════════════════════════════════════════════════════════════


def _produce_public_stats():
    from content.site_writer import PUBLIC_STATS_KEY, write_public_stats

    s3 = CapturingS3()
    ok = write_public_stats(
        s3,
        vitals={"weight_lbs": 201.4, "hrv_ms": 42.0, "rhr_bpm": 55.0, "recovery_pct": 61.0, "sleep_hours": 7.4},
        journey={"start_weight_lbs": 232.0, "goal_weight_lbs": 185.0, "current_weight_lbs": 201.4, "lost_lbs": 30.6},
        training={"ctl_fitness": 44.0, "atl_fatigue": 52.0, "tsb_form": -8.0},
        platform={"mcp_tools": 76, "data_sources": 20, "lambdas": 104, "days_in": 8, "tier0_streak": 5},
    )
    assert ok is True, "write_public_stats failed (it is non-fatal by design, so it returns False rather than raising)"
    return json.loads(s3.objects[PUBLIC_STATS_KEY])


def _consume_public_stats(stats):
    from content.fingerprint_broadcast import project_public

    return project_public(stats)


def _agree_public_stats(produced, consumed):
    from content.fingerprint_broadcast import PUBLIC_SOURCE_FIELDS

    for block, key in PUBLIC_SOURCE_FIELDS:
        assert consumed[f"{block}.{key}"] is not None, (
            f"the broadcast projection's allowlist names {block}.{key}, but the artifact the producer "
            f"actually writes has no such path — a dead-zone read (#2804)"
        )


register(
    PairContract(
        name="public_stats.json -> fingerprint broadcast projection",
        producer="content.site_writer::write_public_stats",
        consumer="content.fingerprint_broadcast::project_public",
        partition=None,  # an S3 artifact, not a DDB partition
        produce=_produce_public_stats,
        consume=_consume_public_stats,
        agree=_agree_public_stats,
        mutations=(
            Mutation(("vitals",), "rename", to="vital_signs", why="the block name the allowlist traverses"),
            Mutation(("vitals", "recovery_pct"), "drop", why="an allowlisted leaf"),
            Mutation(("platform", "days_in"), "drop", why="the one field build_broadcast reads by [] and would KeyError on"),
            Mutation(("platform", "tier0_streak"), "retype", to="five", why="a type the mark's arithmetic cannot use"),
        ),
        note=(
            "The producer owns the BLOCK STRUCTURE and the `_json_safe` cast; the leaf values arrive from "
            "its caller (daily_brief). Block nesting is precisely what `project_public`'s "
            "`(stats.get(block) or {}).get(key)` traverses, and it degrades to None rather than raising — "
            "so a producer that flattened or renamed a block would publish an empty mark, silently."
        ),
    )
)


# ══════════════════════════════════════════════════════════════════════════════
# PAIR 7 — computed_metrics.tier0_streak -> site-stats-refresh's public_stats.json
#   compute.daily_metrics_compute_lambda.store_computed_metrics
#     -> web.site_stats_refresh_lambda.resolve_tier0_streak
#
# #3172: found while seeding this registry (PR #3169) — site_stats_refresh_lambda
# read `tier0_streak` off the raw `habitify` ingestion partition (which has no such
# field; it is a DERIVED value) rather than `computed_metrics`, where
# store_computed_metrics actually writes it. A permanent dead-zone read (#2804's
# class): the 4x/day refresh cron's own comment promised to keep the streak current
# intraday and never could. Root-caused and fixed on the CONSUMER side (this pair's
# producer, store_computed_metrics, was always right — it is pair 3's producer too);
# `resolve_tier0_streak` is the extracted, importable, real function the fix reads
# through, in place of the dead `habitify` lookup inline in `lambda_handler`.
# ══════════════════════════════════════════════════════════════════════════════


def _consume_tier0_streak(item):
    from web.site_stats_refresh_lambda import resolve_tier0_streak

    # existing_platform={} isolates the contract to the computed_metrics read path —
    # the fallback-to-yesterday's-value half is not what this pair is about.
    return resolve_tier0_streak(item, {})


def _agree_tier0_streak(produced, consumed):
    assert consumed == int(
        produced["tier0_streak"]
    ), "the refresh cron's resolved streak disagrees with what daily-metrics-compute actually wrote"


register(
    PairContract(
        name="computed_metrics -> site-stats-refresh tier0_streak",
        producer="compute.daily_metrics_compute_lambda::store_computed_metrics",
        consumer="web.site_stats_refresh_lambda::resolve_tier0_streak",
        partition="computed_metrics",
        produce=_produce_computed_metrics,  # the same real producer call pair 3 uses
        consume=_consume_tier0_streak,
        agree=_agree_tier0_streak,
        mutations=(
            Mutation(("tier0_streak",), "drop", why="the whole field the refresh cron exists to keep current intraday"),
            Mutation(("tier0_streak",), "rename", to="tier0_streak_count", why="a plausible drift of the exact key name the cron reads"),
            Mutation(("tier0_streak",), "retype", to="five", why="a type the cron's float() cast cannot use"),
        ),
        note=(
            "#3172 (found seeding #2847 in PR #3169). habit_scores.store_habit_scores writes the SAME concept "
            "under a different name (`t0_perfect_streak`) on a DIFFERENT partition entirely — three names/places "
            "for one number is exactly how a reader ends up dead-zone reading one of them."
        ),
    )
)


# ══════════════════════════════════════════════════════════════════════════════
# PAIR 8 — ai_analysis EXPERT# row -> the observatory card's journaling prompt
#   intelligence.ai_expert_analyzer_lambda.generate_and_cache
#     -> coach.coach_observatory_renderer.journaling_prompt_for_domain
#
# #3172: found while seeding this registry (PR #3169) — coach_observatory_renderer
# (and site_api_coach_narrative's handle_coach_analysis) read `journaling_prompt`
# off the COACH#{coach_id} OUTPUT# row. No OUTPUT# writer
# (coach_state_updater._write_output_record) has ever put that key in its item —
# `journaling_prompt` is written by the ai_expert_analyzer_lambda's EXPERT# row
# system instead (parsed off the model's own "JOURNALING PROMPT:" tag, mind-only).
# Root-caused and fixed on the CONSUMER side: the OUTPUT# system never had this
# concept to begin with, so the fix resolves it from the real producer via the
# shared domain vocabulary (DOMAIN_COACH_MAP / OPERATIONAL_SHORT_IDS) instead of a
# field that could never be there.
# ══════════════════════════════════════════════════════════════════════════════


class _EmptyReadTable(CapturingTable):
    """Captures the put_item this contract is about while answering every READ
    with nothing — `generate_and_cache`'s data-gathering is fail-soft on an empty
    window by design (every behavioral test in test_ai_expert_analyzer_behavior.py
    runs the analyzer the same way); the point of THIS contract is the tag
    extraction and the write shape, not the richness of the input data.
    """

    def get_item(self, Key, **_kw):  # noqa: N803
        return {}

    def query(self, **_kw):
        return {"Items": []}


def _produce_journaling_prompt():
    from common import retry_utils
    from intelligence import ai_expert_analyzer_lambda as az

    table = _EmptyReadTable()
    saved = (
        az.table,
        az._HAS_INTELLIGENCE_COMMON,
        az._HAS_AI_VALIDATOR,
        az._persona_core,
        az._load_canonical_facts,
        az._get_api_key,
        retry_utils.call_anthropic_raw,
    )
    az.table = table
    az._HAS_INTELLIGENCE_COMMON = False
    az._HAS_AI_VALIDATOR = False
    az._persona_core = None
    az._load_canonical_facts = dict
    az._get_api_key = lambda: "sk-test"
    # The Anthropic call IS the transport here (stubbing it is the exact "fake
    # table/s3_client that captures the item" idiom, applied to the one wire kind
    # this producer speaks over that the other 6 pairs never needed). The tag
    # extraction, gating, and DDB item assembly below all run for real.
    reply = (
        "The gap between what you log and what you notice is the whole story this month.\n\n"
        "KEY RECOMMENDATION: Write the thing down before the feeling passes.\n"
        "JOURNALING PROMPT: What did you decide not to say today?\n"
        "ELENA QUOTE: He counts what he cannot yet feel.\n"
    )
    retry_utils.call_anthropic_raw = lambda req, timeout=None: {"content": [{"type": "text", "text": reply}]}
    try:
        az.generate_and_cache("mind")  # #3172: only "mind" is ever asked for a journaling prompt
    finally:
        (
            az.table,
            az._HAS_INTELLIGENCE_COMMON,
            az._HAS_AI_VALIDATOR,
            az._persona_core,
            az._load_canonical_facts,
            az._get_api_key,
            retry_utils.call_anthropic_raw,
        ) = saved
    assert table.items, "generate_and_cache refused the write (empty/gated response?) — no payload to contract on"
    return table.items[0]


def _consume_journaling_prompt(item):
    from coach import coach_observatory_renderer as cobs

    class _Singleton:
        def get_item(self, Key, **_kw):  # noqa: N803
            return {"Item": dict(item)} if item.get("pk") == Key.get("pk") and item.get("sk") == Key.get("sk") else {}

    real_table = cobs.table
    cobs.table = _Singleton()
    try:
        return cobs.journaling_prompt_for_domain("mind")
    finally:
        cobs.table = real_table


def _agree_journaling_prompt(produced, consumed):
    assert consumed == produced["journaling_prompt"], "the card's journaling prompt disagrees with what the analyzer actually wrote"


register(
    PairContract(
        name="ai_analysis EXPERT# -> observatory card journaling prompt",
        producer="intelligence.ai_expert_analyzer_lambda::generate_and_cache",
        consumer="coach.coach_observatory_renderer::journaling_prompt_for_domain",
        partition="ai_analysis",
        produce=_produce_journaling_prompt,
        consume=_consume_journaling_prompt,
        agree=_agree_journaling_prompt,
        mutations=(
            Mutation(("journaling_prompt",), "drop", why="the whole field; a producer that dropped it must read as absent, not stale"),
            Mutation(
                ("journaling_prompt",), "rename", to="journal_prompt", why="a plausible drift of the exact key name the card indexes on"
            ),
            Mutation(("sk",), "retype", to="EXPERT#sleep", why="the expert_key-keyed row the card's domain lookup indexes on"),
        ),
        note=(
            "#3172 (found seeding #2847 in PR #3169). coach_state_updater._write_output_record's OUTPUT# item "
            "never had a journaling_prompt key at all — this was never a rename or a drop in production, it was "
            "two systems (the COACH# persona pipeline and the EXPERT# ai_analysis pipeline) sharing a reader's "
            "assumption without ever sharing a write."
        ),
    )
)


# ══════════════════════════════════════════════════════════════════════════════
# THE FLOOR — pairs this platform KNOWS must agree.
#
# Sourced from the #2813 follow-up disposition and the two contracts built this
# week (#3049 input_manifest, DIL-025 send_ledger). Every name here must be in the
# registry above; dropping an entry from the registry without dropping it here is
# the "registry quietly rotted" failure, and the sweep reds on it.
#
# This list only ever GROWS. Removing a name requires the pair to be genuinely
# gone from the platform, not merely inconvenient to test.
# ══════════════════════════════════════════════════════════════════════════════

KNOWN_MUST_AGREE_PAIRS = (
    "input_manifest -> character page projection",
    "send_ledger row -> replay guard + status page",
    "computed_metrics -> canonical facts",
    "engagement_state -> /api/presence",
    "adaptive_mode -> /api/ask grounding reads",
    "public_stats.json -> fingerprint broadcast projection",
    # #3172 — the two live mismatches found while seeding this registry (PR #3169),
    # now root-caused, fixed, and enrolled.
    "computed_metrics -> site-stats-refresh tier0_streak",
    "ai_analysis EXPERT# -> observatory card journaling prompt",
)

#: The enrollment ratchet (see the sweep's module docstring for why this, and not
#: a 299-entry exemption ledger, is the coverage instrument). Raise it in the same
#: PR that enrolls a pair; it may never be lowered.
ENROLLED_FLOOR = 8

__all__ = ["ENROLLED_FLOOR", "KNOWN_MUST_AGREE_PAIRS"]
