"""tests/test_source_registry_coverage_3669.py — no live partition is invisible to every check.

#3669. `SOURCE_REGISTRY` is the platform's derivation point for *how a source arrives, how
often, and how stale is too stale*: `freshness_checker`'s `checker_sources()` /
`stale_hours_overrides()`, the staleness alarms, `/api/source_freshness`, the coach source
inventory and the MCP operator view are all projections of it. **A partition absent from it
is invisible to every one of those checks at once** — and absence is silent by
construction, which is why this went unnoticed for months.

`scripts/check_raw_zone_drift.py` passed over the same gap and was right to: it asserts
every live `raw/` prefix is named by a `raw_layout` facet, and `labs`/`inbound_email` both
had one. **A raw-layout facet is not a registry entry.** Describing where the PDFs land
says nothing about a cadence. That asymmetry is the defect this file closes.

WHAT IS ASSERTED, AND WHERE THE NUMBERS COME FROM
──────────────────────────────────────────────────
1. `labs` is registered, and its cadence is ONE number. `cadence_months: 6` (owner ruling
   2026-09-06: *"labs i just do every 6 months or so and upload"*) drives BOTH the
   registry's `stale_hours` (computed, never typed) and `/api/status`'s manual due-date
   panel, which used to carry its own `DUE_MONTHS = {"labs": 6, …}` in the serving layer.

2. `inbound_email` is RETIRED, as a claim the world can contradict. A retirement that
   nothing can falsify is a comment; here, a retired key appearing in the live pk-family
   census fails this file.

3. THE SET is empty or dispositioned: every live `SOURCE#` partition has a registry entry,
   a `phase_taxonomy` class that makes it platform-written, or a dated
   `UNREGISTERED_PARTITIONS` reason. A planted unregistered partition reds the guard.

4. (issue 3571, box 2 — that issue stays OPEN on an owner ruling) every source whose own
   `method`/`desc` text says "manual" carries a `capture_channel`, or an explicit
   `capture_channel: None` WITH a dated written reason. Derived from the registry's text,
   never a hand-listed set.

HOW THE LIVE LEG IS REAL AT PR TIME
───────────────────────────────────
The enumeration comes from `lambdas/experiment/pk_census.py`, the sanctioned single home
for "what pk families are live" (#3860) — which answers by SCANNING DynamoDB. CI has no
AWS credentials, so the scan is captured into `deploy/generated/pk_family_census.json` by
`deploy/write_pk_family_census.py` (read-only) and graded here. That is a snapshot, and
this file says so rather than pretending otherwise:
  * the artifact must be NON-VACUOUS (an empty or truncated census would turn this guard
    green by erasing its own denominator — the #3860 vacuous-scan trap);
  * its `captured_at` must parse, must not be in the future, and must not be older than
    `MAX_CENSUS_AGE_DAYS`, so a frozen artifact eventually says so out loud instead of
    quietly grading a world that no longer exists.

SCOPE — what a green here does NOT say
──────────────────────────────────────
A partition classified EXPERIMENT_SCOPED / SYSTEM_STATE by `phase_taxonomy` is
auto-dispositioned (the platform writes it; there is no capture cadence to declare). If a
genuinely INGESTED source were ever misclassified into one of those two classes it would
pass this guard — but it would also be WIPED by the next experiment reset, which is a far
louder failure than this test. Stated, not silently relied on.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "lambdas", ROOT / "lambdas" / "web"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

from experiment import phase_taxonomy  # noqa: E402
from ingestion import source_registry as reg  # noqa: E402

CENSUS_PATH = ROOT / "deploy" / "generated" / "pk_family_census.json"
REFRESH_CMD = "python3 deploy/write_pk_family_census.py"

# The artifact is a snapshot of a live scan. Generous, because a CI failure by calendar is
# a cost — but finite, because a frozen census grading a moved world is the failure this
# whole issue is about. Six months is the same "run it quarterly-ish" horizon
# `scripts/check_raw_zone_drift.py` carries for the S3 side of the same question.
MAX_CENSUS_AGE_DAYS = 180

# The capture-channel set, MEASURED 2026-09-17 — not quoted from the facet comment, which
# still says "the three manual channels are HAE, Notion, MCP" while `progress_photos` has
# carried 'telegram' since #3757. (Issue 3571's premise quotes that stale comment; the
# facet doc is corrected in this PR.) Matthew's decision, and NOT this file's to extend:
# whether 'dropbox' joins is the open ruling on 3571. Pinned so a PR that mints a new
# channel value has to change this line — which is the review moment that decision deserves.
OWNER_RULED_CAPTURE_CHANNELS = {"hae", "notion", "mcp", "telegram"}

_ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


# ══════════════════════════════════════════════════════════════════════════════
# The census artifact — loaded once, asserted non-vacuous before anything reads it.
# ══════════════════════════════════════════════════════════════════════════════


def load_census() -> dict:
    assert CENSUS_PATH.exists(), f"{CENSUS_PATH.relative_to(ROOT)} is missing — regenerate with: {REFRESH_CMD}"
    return json.loads(CENSUS_PATH.read_text())


def live_source_families(census: dict) -> list[str]:
    """The live `SOURCE#<x>` partition names, as `<x>`. ONE implementation, shared by the
    live assertion and by its controls — a control that re-types the rule proves the copy."""
    return sorted(k[len("SOURCE#") :] for k in (census.get("families") or {}) if k.startswith("SOURCE#"))


CENSUS = load_census()
LIVE_SOURCES = live_source_families(CENSUS)


class TestTheCensusArtifactIsNotVacuous:
    """A guard whose denominator can silently empty is a check that cannot fail."""

    def test_the_artifact_declares_its_provenance(self):
        meta = CENSUS["_meta"]
        assert "pk_census" in meta["generated_by"], "the artifact no longer names its single-home derivation (#3860)"
        assert "never hand-edit" in meta["generated_by"]
        assert meta["table"] and meta["region"]

    def test_the_census_is_large_enough_to_be_a_real_scan(self):
        meta = CENSUS["_meta"]
        assert meta["family_count"] == len(CENSUS["families"]), "the stated family_count disagrees with the families dict"
        assert meta["family_count"] >= 60, f"only {meta['family_count']} pk families — a truncated scan, not the live table"
        assert meta["item_count"] >= 10_000, f"only {meta['item_count']} items scanned — a truncated scan"
        assert len(LIVE_SOURCES) >= 50, f"only {len(LIVE_SOURCES)} live SOURCE# families — the enumeration is not covering the table"

    def test_the_census_contains_partitions_that_certainly_exist(self):
        """A census missing whoop is not a census. Cheap, blunt, and it catches the class of
        breakage (wrong table, wrong key shape) that would otherwise read as 'all clear'."""
        for certain in ("whoop", "withings", "apple_health", "hevy"):
            assert certain in LIVE_SOURCES, f"{certain!r} absent from the census — the scan or the artifact is wrong"

    def test_the_capture_date_is_parseable_recent_and_not_from_the_future(self):
        captured = datetime.strptime(CENSUS["_meta"]["captured_at"], "%Y-%m-%d").replace(tzinfo=timezone.utc).date()
        today = datetime.now(timezone.utc).date()
        assert captured <= today, f"census captured_at {captured} is in the future — the artifact was hand-edited"
        age = (today - captured).days
        assert age <= MAX_CENSUS_AGE_DAYS, (
            f"the pk-family census is {age} days old (captured {captured}, ceiling {MAX_CENSUS_AGE_DAYS}d). "
            f"It is a snapshot of a live scan and this guard is grading a world that may have moved. Refresh "
            f"(read-only, no AWS write): {REFRESH_CMD}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Box 1 — labs is registered, and its cadence is ONE number.
# ══════════════════════════════════════════════════════════════════════════════


def cadence_disagreements(panel_due_months: dict, registry=None) -> list[str]:
    """Sources where the served due-date panel and the registry disagree about the cadence.

    THE rule, as a function, so the live assertion and the must-fail control run the same
    code. Returns one human-readable line per disagreement; empty means they cannot
    disagree.
    """
    registry = reg.SOURCE_REGISTRY if registry is None else registry
    out = []
    for key, row in registry.items():
        months = row.get("cadence_months")
        if months is None:
            continue
        served = panel_due_months.get(key)
        if served != months:
            out.append(f"{key}: /api/status panel says {served!r} months, registry cadence_months says {months!r}")
        derived = row.get("stale_hours")
        expect = int(months) * reg.DAYS_PER_CADENCE_MONTH * 24
        if derived != expect:
            out.append(f"{key}: stale_hours {derived!r} != cadence_months {months!r} ({expect}h) — the two drifted")
    return out


class TestLabsIsRegisteredWithOneCadence:
    def test_labs_has_a_registry_entry_at_all(self):
        assert "labs" in reg.SOURCE_REGISTRY, "labs is absent from SOURCE_REGISTRY — invisible to every derived check (#3669)"
        row = reg.SOURCE_REGISTRY["labs"]
        assert row["behavioral"] is True, "a lab draw happens when he books one — staleness must never page"
        assert re.search(r"manual", f"{row['method']} {row['desc']}", re.IGNORECASE), "the method must say how it arrives: by hand"
        assert row["posture"] == "load-bearing"
        assert row["raw_layout"]["prefix"] == "raw/matthew/labs", "the entry must own the raw prefix it actually writes to"

    def test_the_cadence_is_the_owner_ruling(self):
        """2026-09-06: 'labs i just do every 6 months or so and upload.'"""
        assert reg.SOURCE_REGISTRY["labs"]["cadence_months"] == 6
        assert reg.due_months()["labs"] == 6

    def test_stale_hours_is_derived_from_the_cadence_not_typed_beside_it(self):
        assert reg.SOURCE_REGISTRY["labs"]["stale_hours"] == 6 * reg.DAYS_PER_CADENCE_MONTH * 24 == 4320

    def test_the_derivation_overwrites_a_hand_typed_disagreement(self):
        """MUST-FAIL control for the derivation itself: a row that types a WRONG stale_hours
        next to a cadence must not keep it. Without this, `_derive_cadence_stale_hours` is
        indistinguishable from a function that never runs."""
        reg.SOURCE_REGISTRY["__probe_cadence__"] = {"cadence_months": 3, "stale_hours": 1}
        try:
            reg._derive_cadence_stale_hours()
            assert reg.SOURCE_REGISTRY["__probe_cadence__"]["stale_hours"] == 3 * reg.DAYS_PER_CADENCE_MONTH * 24
        finally:
            del reg.SOURCE_REGISTRY["__probe_cadence__"]
            reg._derive_cadence_stale_hours()

    def test_the_status_panel_and_the_registry_cannot_disagree(self):
        from web import site_api_status as sas

        assert sas.DUE_MONTHS["labs"] == reg.SOURCE_REGISTRY["labs"]["cadence_months"] == 6
        assert not cadence_disagreements(sas.DUE_MONTHS)

    def test_the_serving_layer_no_longer_restates_a_registered_cadence(self):
        """The literal that remains in `site_api_status.py` must hold only the rows the
        registry does NOT declare — otherwise the derivation is decoration over a copy."""
        from web import site_api_status as sas

        assert "labs" not in sas._DUE_MONTHS_UNREGISTERED, "labs is back in the serving-layer literal — that is the #3669 drift"
        # CODE lines only. The first draft of this assertion matched the COMMENT that
        # explains the removal and reported the defect it was written to detect — the
        # text-match-reads-its-own-explanation class, caught here by running it.
        src = (ROOT / "lambdas" / "web" / "site_api_status.py").read_text()
        code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
        assert 'DUE_MONTHS = {"labs"' not in code, "the inline DUE_MONTHS literal is back inside the render loop"
        assert "due_months()" in code, "the panel no longer derives its cadences from the registry"

    def test_the_positive_control_a_disagreement_is_reported(self):
        """Plant the exact pre-#3669 state — a panel that says something the registry does
        not — and watch the rule name it. Without this, an empty result proves nothing."""
        found = cadence_disagreements({**{k: v for k, v in reg.due_months().items()}, "labs": 3})
        assert found and found[0].startswith("labs: /api/status panel says 3 months"), found
        # NEGATIVE CONTROL: the same call over the real panel is clean.
        assert cadence_disagreements(reg.due_months()) == []

    def test_a_lagging_cadence_is_narrated_rather_than_read_as_a_broken_pipe(self):
        """#3516's facet now answers for labs: a 5-month-old panel is the designed cadence."""
        facet = reg.availability_facet("labs")
        assert facet["status"] == reg.AVAILABILITY_LAGGING
        assert facet["lag_hours"] == 4320
        assert "labs" in reg.caveated_source_ids()

    def test_labs_is_deliberately_off_the_daily_freshness_surfaces(self):
        """Registered is not the same as monitored-daily, and the reason is written in the
        entry: freshness_checker's early-warning tier is a GLOBAL 24h constant, so a
        ~4,000-hour healthy state would sit permanently yellow and put a permanent +1 floor
        under WarningSourceCount — an early-warning count that can never read 0."""
        assert "labs" not in reg.checker_sources()
        assert "labs" not in reg.public_board_sources()
        assert "labs" in reg.mcp_source_ids(), "the operator must still be able to query the partition"


# ══════════════════════════════════════════════════════════════════════════════
# Box 2 — inbound_email is retired, and the retirement is falsifiable.
# ══════════════════════════════════════════════════════════════════════════════


def retired_sources_that_are_actually_live(live_sources, retired=None) -> list[str]:
    """Retired keys the live census still shows writing. ONE implementation for the live
    assertion and the control."""
    retired = reg.RETIRED_SOURCES if retired is None else retired
    return sorted(set(retired) & set(live_sources))


class TestInboundEmailIsRetiredExplicitly:
    def test_it_is_retired_rather_than_registered(self):
        assert "inbound_email" not in reg.SOURCE_REGISTRY, "a dead prefix must not be given a cadence it cannot keep"
        assert "inbound_email" in reg.RETIRED_SOURCES

    def test_the_retirement_carries_a_date_the_evidence_and_the_owner_ruling(self):
        entry = reg.RETIRED_SOURCES["inbound_email"]
        assert _ISO_DATE.fullmatch(entry["dated"]), f"undated retirement: {entry['dated']!r}"
        assert "i dont know what that is" in entry["owner_ruling"], "the owner's own words are the ruling of record"
        reason = entry["reason"]
        assert "ZERO DynamoDB rows" in reason and "AMAZON_SES_SETUP_NOTIFICATION" in reason, reason
        assert len(reason) > 200, "a retirement reason has to carry its evidence, not just an assertion"
        assert entry["raw_prefixes"] == ("raw/inbound_email", "raw/matthew/inbound_email")
        assert "delete-protected" in entry["s3_disposition"], "raw/* cannot be deleted — say what the tombstone actually is"

    def test_the_live_census_does_not_contradict_the_retirement(self):
        """THE falsifiable half. If `inbound_email` ever writes a DDB row again, this fails
        and the retirement has to be re-argued rather than quietly outlived."""
        assert retired_sources_that_are_actually_live(LIVE_SOURCES) == []

    def test_the_positive_control_a_retirement_the_world_contradicts_is_reported(self):
        assert retired_sources_that_are_actually_live([*LIVE_SOURCES, "inbound_email"]) == ["inbound_email"]

    def test_the_parser_reference_is_reconciled_not_orphaned(self):
        """`insight_email_parser_lambda` still builds `raw/inbound_email/{messageId}` — on
        purpose: that is the LANDING KEY of a live reply loop whose output goes to
        SOURCE#insights. The retirement is of the idea that it is a data source. The code
        must say so at the line, or the next reader files this issue again."""
        src = (ROOT / "lambdas" / "emails" / "insight_email_parser_lambda.py").read_text()
        idx = src.index('key = f"raw/inbound_email/{message_id}"')
        window = src[max(0, idx - 1200) : idx]
        assert "RETIRED_SOURCES" in window, "the surviving reference does not point at its disposition"
        assert "SOURCE#insights" in window, "the reference must name the partition that is actually healthy"

    def test_the_retired_prefixes_are_still_explained_to_the_raw_zone_walker(self):
        """Retiring a source must not blind `scripts/check_raw_zone_drift.py`: the 8 objects
        are undeletable, so their prefixes must stay named."""
        for prefix in reg.RETIRED_SOURCES["inbound_email"]["raw_prefixes"]:
            assert prefix in reg.NON_INGESTION_RAW_PREFIXES
            assert "RETIRED" in reg.NON_INGESTION_RAW_PREFIXES[prefix]["note"]


# ══════════════════════════════════════════════════════════════════════════════
# Box 3 — THE SET: every live SOURCE# partition is registered or dispositioned.
# ══════════════════════════════════════════════════════════════════════════════

PLANTED = "__planted_unregistered_partition_3669__"


class TestEveryLivePartitionIsDispositioned:
    def test_the_set_is_empty(self):
        undisposed = reg.unregistered_source_partitions(LIVE_SOURCES)
        assert not undisposed, (
            f"{len(undisposed)} live SOURCE# partition(s) have NO disposition: {undisposed}. Each is invisible to "
            "every freshness, staleness and coach-inventory check at once. Give it a SOURCE_REGISTRY entry (a "
            "cadence a check can enforce) or a dated UNREGISTERED_PARTITIONS reason naming what writes it."
        )

    def test_a_planted_unregistered_partition_reds_the_guard(self):
        """THE MUST-FAIL CONTROL the acceptance names. Without it, 'the set is empty' and
        'the rule matched nothing' are the same green."""
        found = reg.unregistered_source_partitions([*LIVE_SOURCES, PLANTED])
        assert found == [PLANTED], found

    def test_a_planted_platform_written_partition_is_not_flagged(self):
        """NEGATIVE CONTROL: the auto-disposition is real, not an accident of the data —
        a new partition the taxonomy calls platform-written passes without an exemption."""
        assert reg.unregistered_source_partitions([PLANTED], class_of=lambda _n: "experiment_scoped") == []
        assert reg.unregistered_source_partitions([PLANTED], class_of=lambda _n: "raw_timeseries") == [PLANTED]

    def test_the_auto_disposition_reads_the_real_taxonomy(self):
        """The default `class_of` must be phase_taxonomy itself — not a copy of its answers."""
        assert phase_taxonomy.SOURCE_CLASS["adaptive_mode"] in reg.PLATFORM_WRITTEN_TAXONOMY_CLASS_IDS
        assert phase_taxonomy.SOURCE_CLASS["whoop"] not in reg.PLATFORM_WRITTEN_TAXONOMY_CLASS_IDS
        assert reg.unregistered_source_partitions(["adaptive_mode"]) == []

    def test_dexa_and_genome_got_their_disposition_in_the_same_pass(self):
        """Named in the issue's own Set so the next pass does not rediscover them."""
        for key in ("dexa", "genome"):
            assert key in reg.UNREGISTERED_PARTITIONS, f"{key} is still undispositioned"
            assert key in LIVE_SOURCES, f"{key} is not live — the exemption describes nothing"
        assert "12-month" in reg.UNREGISTERED_PARTITIONS["dexa"]["reason"]
        assert "ONE-OFF import" in reg.UNREGISTERED_PARTITIONS["genome"]["reason"]

    def test_every_exemption_is_dated_reasoned_and_names_a_writer(self):
        for key, entry in reg.UNREGISTERED_PARTITIONS.items():
            assert _ISO_DATE.fullmatch(entry["dated"]), f"{key}: undated exemption {entry['dated']!r}"
            assert datetime.strptime(entry["dated"], "%Y-%m-%d").date() <= date.today(), f"{key}: dated in the future"
            reason = entry["reason"]
            assert len(reason) >= 120, f"{key}: the reason is too short to be one ({reason!r})"
            assert re.search(r"(\.py\b|written by|no writer|frozen|hand-entered|imported once)", reason, re.IGNORECASE), (
                f"{key}: the reason does not say WHAT WRITES IT — 'I could not find a writer' is not evidence "
                "there isn't one (the #3563 lesson)"
            )

    def test_no_exemption_describes_a_partition_that_is_not_there(self):
        """A dated exemption for a partition the census cannot see is fiction accumulating.
        Shrink it in the same pass that notices."""
        fictional = sorted(set(reg.UNREGISTERED_PARTITIONS) - set(LIVE_SOURCES))
        assert not fictional, f"exemptions for partitions absent from the live census: {fictional} — remove them ({REFRESH_CMD})"

    def test_the_issue_set_query_is_recorded_honestly(self):
        """#3669's own `## Set` block named 4 members. The live census says otherwise, and
        the registry comment has to carry the real number — a guard whose issue under-counts
        its own set teaches the next reader the wrong denominator."""
        unregistered = [s for s in LIVE_SOURCES if s not in reg.SOURCE_REGISTRY]
        src = (ROOT / "lambdas" / "ingestion" / "source_registry.py").read_text()
        assert str(len(LIVE_SOURCES)) in src and str(len(unregistered)) in src, (
            f"the UNREGISTERED_PARTITIONS header must state the MEASURED set ({len(LIVE_SOURCES)} live SOURCE# "
            f"families, {len(unregistered)} with no registry entry), not the audit's 4"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Issue 3571, box 2 — a manual source answers the capture-channel question.
# That issue stays OPEN: whether 'dropbox' joins the #746 channel set is an OWNER ruling.
# ══════════════════════════════════════════════════════════════════════════════


def manual_sources_missing_a_capture_answer(registry=None) -> list[str]:
    """Sources whose own text says 'manual' but that answer the capture-channel question
    with neither a channel nor an explicit, DATED None. ONE implementation for the live
    assertion and the control."""
    registry = reg.SOURCE_REGISTRY if registry is None else registry
    bad = []
    for key in reg.manual_method_source_ids():
        entry = registry.get(key, {})
        if entry.get("capture_channel"):
            continue
        if "capture_channel" not in entry:
            bad.append(f"{key}: no capture_channel key at all (reads identically to nobody having looked)")
            continue
        reason = str(entry.get("capture_channel_reason") or "")
        if not _ISO_DATE.search(reason):
            bad.append(f"{key}: capture_channel is None with no DATED reason ({reason[:60]!r})")
        elif len(reason) < 80:
            bad.append(f"{key}: the reason is too short to be one ({reason!r})")
    return sorted(bad)


class TestManualSourcesAnswerTheCaptureChannelQuestion:
    def test_the_denominator_is_derived_from_the_registry_text(self):
        manual = reg.manual_method_source_ids()
        assert "macrofactor" in manual, "the #3571 specimen must be in its own denominator"
        assert "labs" in manual, "#3669's new manual-upload source must be in it too"
        assert len(manual) >= 6, f"the derivation found only {manual} — it is not reading the registry's text"
        # Derived, not listed: a source that stops calling itself manual leaves the set.
        assert "whoop" not in manual and "weather" not in manual

    def test_every_manual_source_answers(self):
        missing = manual_sources_missing_a_capture_answer()
        assert not missing, (
            "manual-by-method source(s) with no capture-channel answer: " + "; ".join(missing) + ". Give it a #746 "
            "channel, or an explicit `capture_channel: None` with a dated `capture_channel_reason` (issue 3571)."
        )

    def test_the_positive_control_the_pre_fix_state_is_reported(self):
        """Plant the EXACT state issue 3571 found — macrofactor with no capture_channel key
        — and watch the rule name it."""
        mutated = {k: dict(v) for k, v in reg.SOURCE_REGISTRY.items()}
        mutated["macrofactor"].pop("capture_channel", None)
        mutated["macrofactor"].pop("capture_channel_reason", None)
        found = manual_sources_missing_a_capture_answer(mutated)
        assert found == ["macrofactor: no capture_channel key at all (reads identically to nobody having looked)"], found
        # A None with an UNDATED reason is equally unacceptable — the second failure mode.
        mutated["macrofactor"]["capture_channel"] = None
        mutated["macrofactor"]["capture_channel_reason"] = "pending"
        assert manual_sources_missing_a_capture_answer(mutated) == ["macrofactor: capture_channel is None with no DATED reason ('pending')"]

    def test_macrofactor_records_the_open_owner_ruling_without_pre_empting_it(self):
        entry = reg.SOURCE_REGISTRY["macrofactor"]
        assert "capture_channel" in entry and entry["capture_channel"] is None
        assert "3571" in entry["capture_channel_reason"], "the reason must name the ruling it is waiting on"
        assert "dropbox" not in (entry.get("capture_channel") or ""), "the owner's ruling is not this repo's to make"

    def test_no_new_capture_channel_value_was_invented(self):
        """The #746 set is Matthew's decision. A PR that adds a value has to change this
        line — which is the review moment that decision deserves."""
        live = {v.get("capture_channel") for v in reg.SOURCE_REGISTRY.values() if v.get("capture_channel")}
        assert live <= OWNER_RULED_CAPTURE_CHANNELS, f"unsanctioned capture_channel value(s): {live - OWNER_RULED_CAPTURE_CHANNELS}"

    def test_the_nudge_eligible_set_did_not_change(self):
        """3571 box 3 is explicitly conditional ('if added'). Recording an explicit None must
        change no reader-facing behaviour — macrofactor is still not nudge-eligible."""
        assert "macrofactor" not in reg.manual_capture_sources()
        assert "labs" not in reg.manual_capture_sources()
        assert set(reg.manual_capture_sources()) == {"apple_health", "measurements", "progress_photos", "food_delivery", "notion"}


# ══════════════════════════════════════════════════════════════════════════════
# The writer script — the artifact's own single home.
# ══════════════════════════════════════════════════════════════════════════════


class TestTheCensusWriterDelegates:
    def test_it_owns_no_scan_logic_of_its_own(self):
        """The #3860 ruling: ONE home for the pk-family derivation. A writer that re-rolled
        `table.scan` beside `pk_census` would be the same drift with an import in front."""
        src = (ROOT / "deploy" / "write_pk_family_census.py").read_text()
        tree = ast.parse(src)
        calls = {
            f"{node.func.value.id}.{node.func.attr}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
        }
        assert "table.scan" not in calls, "the writer re-implemented the scan instead of calling pk_census"
        assert "pk_census.scan_pk_sk_pages" in src and "pk_census.pk_family" in src

    def test_it_refuses_an_empty_census(self):
        """The vacuous-scan trap, at the point of capture: writing an empty artifact would
        turn every assertion in this file green by erasing the denominator."""
        sys.path.insert(0, str(ROOT / "deploy"))
        import write_pk_family_census as writer

        class _EmptyTable:
            def scan(self, **_kw):
                return {"Items": []}

        with pytest.raises(Exception) as exc:
            writer.capture(table=_EmptyTable())
        assert "vacuous-scan trap" in str(exc.value)

    def test_it_counts_families_from_real_shaped_pages(self):
        sys.path.insert(0, str(ROOT / "deploy"))
        import write_pk_family_census as writer

        class _Table:
            def __init__(self):
                self.calls = 0

            def scan(self, **_kw):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "Items": [
                            {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-09-01"},
                            {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-09-02"},
                            {"pk": "COACH#nutrition", "sk": "STATE#1"},
                        ],
                        "LastEvaluatedKey": {"pk": "x"},
                    }
                return {"Items": [{"pk": "USER#matthew#SOURCE#labs", "sk": "DATE#2026-04-03"}]}

        payload = writer.capture(table=_Table())
        assert payload["families"] == {"COACH": 1, "SOURCE#labs": 1, "SOURCE#whoop": 2}
        assert payload["_meta"]["item_count"] == 4 and payload["_meta"]["family_count"] == 3
