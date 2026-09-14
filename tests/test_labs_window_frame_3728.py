#!/usr/bin/env python3
"""tests/test_labs_window_frame_3728.py — the labs window frame (#3728).

Live on 2026-09-12, two public surfaces disagreed about whether Matthew had ever
had bloodwork:

    /api/coaching-dashboard  coaches[labs].position_summary:
        "I have zero lab draws to interpret yet, so April 3rd is my fixed anchor..."
    /api/labs                labs.total_draws: 8, latest_draw_date: 2026-04-03

The filed diagnosis — "a cycle-scoped claim beside a lifetime-scoped count" — was
wrong, and the fix it implies would not have worked. FOUR inputs reach the analyzer
carrying THREE windows:

    A  labs fact block          lifetime   "total_draws: 8, draw_date: 2026-04-03"
    B  labs_context prompt      lifetime   "8 total blood draws ... do NOT call these
                                            draws during the experiment"
    C  data inventory/maturity  ROLLING 90 DAYS  -> "- labs: not available"
                                                 -> "You have 0 blood draws of data"
    D  experiment phase block   cycle      "NUMBERS THAT CANNOT EXIST YET"

C is the defect, and its window is a third one nobody named: not the cycle, not
lifetime, but `build_data_inventory`'s rolling 90 days. All 8 draws are 2026-04-03,
outside it, so `exists` was False and `days_of_data` 0 — which overrode B's explicit
instruction and forced ORIENTATION_VOICE. The model then reconciled A's date against
C's zero the only way both could be true: it narrated a COMPLETED panel as an
upcoming appointment, live on the dashboard —

    "if you're planning labs before April 3rd, schedule the draw now"

That is why the check's own stated remedy ("regenerate the coach analysis") was
inert: regeneration reproduces the same contradictory inputs. It regenerated the
same day and said it again.

Measured live before the fix: labs 8 lifetime / 0 in window; dexa 2 lifetime / 0 in
window. The second one is not cosmetic — the physical coach's composite
`requires_dexa` branch read that same False and pinned it to orientation
permanently.

What this file holds, all mutation-proved:

  * the episodic registry and the window it selects (revert `inventory_window_start`
    to an unconditional 90 days and the reproduction tests red)
  * `out_of_window` as a distinct third state, and the preamble sentence that
    renders it (delete the `elif` and the preamble test reds)
  * the assessor comparing like with like, in BOTH directions
  * `/api/labs` carrying its own denominator

Nothing here reaches DynamoDB, S3 or the network.
"""

import os
import sys
from datetime import datetime

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

import intelligence.intelligence_common as ic  # noqa: E402
from intelligence import inventory_window as iw  # noqa: E402 — the registry's owning module
from operational import qa_check_coach_labs as qa  # noqa: E402
from pacific_clock import freeze_pacific  # noqa: E402
from web.site_api_phase_frame import archival_frame, lifetime_scope  # noqa: E402

# The live sentence, verbatim from /api/coaching-dashboard on 2026-09-12.
LIVE_LABS_SUMMARY = (
    "I have zero lab draws to interpret yet, so April 3rd is my fixed anchor. "
    "I'm establishing a rigorous fasting protocol: he must fast for a minimum of "
    "10 hours before the draw (water only, no black coffee)."
)


def _freeze(monkeypatch, iso="2026-09-12T12:00:00+00:00"):
    fixed = datetime.fromisoformat(iso)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)

    monkeypatch.setattr(ic, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, ic, _FrozenDatetime)
    return fixed


def _condition_values(cond):
    values = []

    def walk(node):
        for v in getattr(node, "_values", ()):
            if hasattr(v, "_values"):
                walk(v)
            elif not hasattr(v, "name"):
                values.append(v)

    walk(cond)
    return values


class RecordingTable:
    """Bounded fake. `counts` maps partition -> the Count returned for its
    windowed COUNT query; `latest` maps partition -> the sk the unwindowed
    Limit:1 probe returns. Every query is recorded for the window assertions."""

    def __init__(self, counts=None, latest=None):
        self.counts = dict(counts or {})
        self.latest = dict(latest or {})
        self.queries = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        vals = _condition_values(kwargs.get("KeyConditionExpression"))
        pk = vals[0] if vals else ""
        partition = pk.split("#SOURCE#", 1)[1] if "#SOURCE#" in pk else ""
        if kwargs.get("Limit") == 1:
            sk = self.latest.get(partition)
            return {"Items": [{"sk": sk}] if sk else [], "Count": 1 if sk else 0}
        n = self.counts.get(partition, 0)
        if kwargs.get("Select") == "COUNT":
            return {"Count": n, "Items": []}
        return {"Items": [{"sk": f"DATE#2026-09-1{i}"} for i in range(min(n, 9))], "Count": n}

    def window_low_for(self, partition):
        """The `DATE#` lower bound the windowed COUNT query used."""
        for kwargs in self.queries:
            vals = _condition_values(kwargs.get("KeyConditionExpression"))
            if not vals or "#SOURCE#" not in vals[0]:
                continue
            if vals[0].split("#SOURCE#", 1)[1] != partition or kwargs.get("Limit") == 1:
                continue
            lows = [v for v in vals[1:] if isinstance(v, str) and v.startswith("DATE#")]
            if lows:
                return lows[0]
        return None


# ══════════════════════════════════════════════════════════════════════════════
# THE WINDOW REGISTRY
# ══════════════════════════════════════════════════════════════════════════════


class TestTheEpisodicRegistry:
    def test_labs_and_dexa_are_the_episodic_partitions(self):
        """Both were measured live with real history and ZERO records inside the
        90-day window. Naming them here is what stops the count being taken over
        a denominator their cadence cannot fill."""
        assert "labs" in iw._EPISODIC_PARTITIONS
        assert "dexa" in iw._EPISODIC_PARTITIONS

    def test_an_episodic_partition_counts_over_all_history(self, monkeypatch):
        now = _freeze(monkeypatch)
        assert iw.inventory_window_start("labs", now) == "0000-00-00"
        assert iw.inventory_window_start("dexa", now) == "0000-00-00"

    def test_a_daily_partition_keeps_the_ninety_day_window(self, monkeypatch):
        """The 90-day bound is RIGHT for a nightly stream — the fix must not
        widen every source into a lifetime count.

        The frozen instant is passed EXPLICITLY. `_freeze` rebinds the clock on
        `intelligence_common`, and since the registry moved to `inventory_window` a
        bare call here would read the real wall clock and combine it with a fixture
        date — the exact thing this repo's test discipline forbids, and it is why
        this assertion started failing the day after it was written.
        """
        now = _freeze(monkeypatch)
        assert iw.inventory_window_start("whoop", now) == "2026-06-14"
        assert iw.inventory_window_start("macrofactor", now) == "2026-06-14"

    def test_the_episodic_floor_sorts_below_every_real_date_key(self):
        """`"0000-00-00"` is the all-history lower bound only if it orders below
        any `DATE#` a writer can produce — including the 2019 bulk import."""
        assert iw.inventory_window_start("labs", datetime(2026, 9, 12)) < "2019-01-01"

    def test_every_episodic_partition_is_actually_inventoried(self):
        """A registry entry naming a partition no source reads is a rule that
        can never fire — the shape #3629's ratchet exists to catch."""
        inventoried = {p for _l, p in ic._INVENTORY_SOURCES}
        assert iw._EPISODIC_PARTITIONS <= inventoried


# ══════════════════════════════════════════════════════════════════════════════
# THE REPRODUCTION — the live numbers, through the real function
# ══════════════════════════════════════════════════════════════════════════════


class TestTheLiveDefectReproduced:
    """Live 2026-09-12: labs 8 draws, newest 2026-04-03, none in the 90d window."""

    def _inventory(self, monkeypatch):
        _freeze(monkeypatch)
        table = RecordingTable(
            counts={"labs": 8, "dexa": 2, "withings": 90, "whoop": 90},
            latest={"labs": "DATE#2026-04-03", "dexa": "DATE#2026-03-30", "withings": "DATE#2026-09-12"},
        )
        monkeypatch.setattr(ic, "table", table)
        return ic.build_data_inventory(), table

    def test_the_labs_count_is_taken_over_all_history_not_the_window(self, monkeypatch):
        """MUTATION-PROOF: restore `d90 = pacific_now() - 90d` for every
        partition and this asserts 2026-06-14, the pre-fix value."""
        _inv, table = self._inventory(monkeypatch)
        assert table.window_low_for("labs") == "DATE#0000-00-00"

    def test_a_daily_source_is_still_windowed(self, monkeypatch):
        _inv, table = self._inventory(monkeypatch)
        assert table.window_low_for("withings") == "DATE#2026-06-14"

    def test_labs_reads_as_present_with_its_eight_draws(self, monkeypatch):
        """Pre-fix this was `exists: False, days_of_data: 0` — the input that
        produced "You have 0 blood draws of data" beside a fact block naming 8."""
        inv, _t = self._inventory(monkeypatch)
        assert inv["labs"]["exists"] is True
        assert inv["labs"]["days_of_data"] == 8

    def test_the_labs_coach_is_no_longer_told_it_has_zero_draws(self, monkeypatch):
        """The whole point. ORIENTATION_VOICE interpolates `days` verbatim."""
        inv, _t = self._inventory(monkeypatch)
        maturity = ic.build_data_maturity(inv)
        assert maturity["labs"]["days"] == 8
        assert maturity["labs"]["phase"] != "orientation"

    def test_the_physical_coach_escapes_the_dexa_pin(self, monkeypatch):
        """dexa's 2 scans were 5 months old, so `has_dexa` was False and the
        composite branch fell through to orientation no matter how much weight
        data existed. Same cause, second coach."""
        inv, _t = self._inventory(monkeypatch)
        assert inv["dexa"]["exists"] is True
        assert ic.build_data_maturity(inv)["physical"]["phase"] == "established"

    def test_a_genuinely_empty_partition_is_still_absent(self, monkeypatch):
        """The negative control: state_of_mind held no rows at all live, and
        must not be dressed up as present by any of this."""
        inv, _t = self._inventory(monkeypatch)
        assert inv["state_of_mind"]["exists"] is False
        assert inv["state_of_mind"]["out_of_window"] is False


# ══════════════════════════════════════════════════════════════════════════════
# THE THIRD STATE
# ══════════════════════════════════════════════════════════════════════════════


class TestOutOfWindowIsItsOwnState:
    def _inv(self, monkeypatch, counts, latest):
        _freeze(monkeypatch)
        monkeypatch.setattr(ic, "table", RecordingTable(counts=counts, latest=latest))
        return ic.build_data_inventory()

    def test_history_outside_the_window_is_flagged_not_erased(self, monkeypatch):
        """garmin is PAUSED (ADR-074): real history, nothing recent. Pre-fix it
        rendered identically to a source that never existed."""
        inv = self._inv(monkeypatch, {"garmin": 0}, {"garmin": "DATE#2026-05-01"})
        assert inv["garmin"]["exists"] is False
        assert inv["garmin"]["out_of_window"] is True
        assert inv["garmin"]["latest"] == "2026-05-01"

    def test_a_source_with_no_records_at_all_is_not_out_of_window(self, monkeypatch):
        inv = self._inv(monkeypatch, {"garmin": 0}, {})
        assert inv["garmin"]["out_of_window"] is False

    def test_a_live_source_is_not_out_of_window(self, monkeypatch):
        inv = self._inv(monkeypatch, {"whoop": 90}, {"whoop": "DATE#2026-09-12"})
        assert inv["whoop"]["out_of_window"] is False

    def test_a_failed_read_never_claims_history_it_could_not_see(self, monkeypatch):
        """A read failure is UNKNOWN. It degrades to absent as it always has —
        it must not borrow the new state to imply data exists."""
        _freeze(monkeypatch)

        class Exploding(RecordingTable):
            def query(self, **kwargs):
                raise RuntimeError("ddb down")

        monkeypatch.setattr(ic, "table", Exploding())
        inv = ic.build_data_inventory()
        assert inv["labs"]["exists"] is False
        assert inv["labs"]["out_of_window"] is False


class TestThePreambleNamesTheThirdState:
    """MUTATION-PROOF: delete the `elif info.get("out_of_window")` branch in
    `build_coach_preamble` and every test here reds."""

    def _preamble(self, monkeypatch, inventory):
        _freeze(monkeypatch)
        monkeypatch.setattr(ic, "table", RecordingTable())
        return ic.build_coach_preamble(
            coach_name="Dr. James Okafor",
            domain="labs",
            goals={"targets": {}},
            inventory=inventory,
            maturity={"labs": {"phase": "established", "days": 8, "threshold": 1, "unit": "blood draws"}},
        )

    def _out_of_window_inv(self):
        return {"garmin": {"exists": False, "latest": "2026-05-01", "records": 0, "out_of_window": True, "window_days": 90}}

    def test_it_is_never_reported_as_not_available(self, monkeypatch):
        text = self._preamble(monkeypatch, self._out_of_window_inv())
        assert "garmin: not available" not in text

    def test_it_names_the_window_and_the_last_record(self, monkeypatch):
        text = self._preamble(monkeypatch, self._out_of_window_inv())
        assert "OUT OF WINDOW" in text
        assert "2026-05-01" in text
        assert "last 90 days" in text

    def test_it_forbids_both_failure_modes_by_name(self, monkeypatch):
        """The two things the model actually did: called a present source empty,
        and called a past record upcoming."""
        text = self._preamble(monkeypatch, self._out_of_window_inv())
        assert "NOT empty" in text
        assert "upcoming" in text

    def test_a_genuinely_absent_source_still_reads_not_available(self, monkeypatch):
        """Negative control — the new branch must not swallow the old one."""
        text = self._preamble(monkeypatch, {"garmin": {"exists": False, "latest": None, "records": 0, "out_of_window": False}})
        assert "garmin: not available" in text

    def test_an_inventory_written_before_the_fix_still_renders(self, monkeypatch):
        """`out_of_window` absent entirely — an older caller or a stored dict."""
        text = self._preamble(monkeypatch, {"garmin": {"exists": False, "latest": None, "records": 0}})
        assert "garmin: not available" in text


# ══════════════════════════════════════════════════════════════════════════════
# THE CHECK — comparing like with like, in both directions
# ══════════════════════════════════════════════════════════════════════════════


def _coach(text, cid="labs"):
    return [{"coach_id": cid, "position_summary": text}]


class TestTheAssessorComparesLikeWithLike:
    def test_the_live_unframed_sentence_still_fails(self, monkeypatch):
        """The founding case (#1993) must not be relaxed by the framing work."""
        ok, msg = qa.assess_coach_labs_truth({"total_draws": 8}, _coach(LIVE_LABS_SUMMARY))
        assert ok is False
        assert "labs" in msg and "total_draws=8" in msg

    def test_the_failure_message_no_longer_prescribes_the_inert_remedy(self):
        """ "Regenerate the coach analysis" was measured ineffective — it
        regenerated the same day and produced the same sentence."""
        _ok, msg = qa.assess_coach_labs_truth({"total_draws": 8}, _coach(LIVE_LABS_SUMMARY))
        assert "regenerate the coach analysis" not in msg.lower()
        assert "window" in msg.lower()

    @pytest.mark.parametrize(
        "text",
        [
            "I have zero lab draws this cycle, so the April 3rd panel is my baseline.",
            "There are zero draws since the restart; everything I read predates it.",
            "Zero blood results in this cycle — the last panel was April 3rd.",
            "This cycle has produced zero lab draws so far.",
        ],
    )
    def test_a_zero_claim_that_names_its_window_is_not_a_contradiction(self, text):
        """Two true statements about two windows. Pre-fix these all FAILED, which
        is why the check would have fired every night of a young cycle even on
        honest prose."""
        ok, _msg = qa.assess_coach_labs_truth({"total_draws": 8}, _coach(text))
        assert ok is True

    def test_one_unframed_claim_among_framed_ones_still_fails(self):
        """The qualifier must attach to the claim, not to the paragraph."""
        text = "Zero lab draws this cycle. And frankly I have zero blood results to interpret at all."
        ok, _msg = qa.assess_coach_labs_truth({"total_draws": 8}, _coach(text))
        assert ok is False

    def test_an_invented_draw_count_against_an_empty_store_fails(self):
        """THE NEWLY GUARDED DIRECTION. Pre-fix this returned True
        unconditionally — the honest-looking half of the class was never
        asserted on at all."""
        ok, msg = qa.assess_coach_labs_truth({"total_draws": 0}, _coach("His 8 blood draws show a clear trend."))
        assert ok is False
        assert "empty store" in msg

    def test_an_empty_store_with_no_positive_claim_passes(self):
        ok, _msg = qa.assess_coach_labs_truth({"total_draws": 0}, _coach("No bloodwork yet; I'll start when a panel lands."))
        assert ok is True

    def test_a_zero_count_claim_against_an_empty_store_is_not_an_invention(self):
        """ "0 blood draws" beside an empty store is simply true."""
        ok, _msg = qa.assess_coach_labs_truth({"total_draws": 0}, _coach("He has 0 blood draws on record."))
        assert ok is True

    def test_a_dark_endpoint_says_so_rather_than_reporting_a_pass(self):
        """A comparison that could not be made is not a clean comparison."""
        ok, msg = qa.assess_coach_labs_truth({}, _coach(LIVE_LABS_SUMMARY))
        assert ok is True
        assert "nothing to compare" in msg.lower()

    @pytest.mark.parametrize(
        "text",
        [
            # VERBATIM from /api/coaching-dashboard, 2026-09-13T17:07:01Z — the
            # regeneration that made the zero-claim regex go quiet.
            "I'm tracking three commitments from our April planning session: scheduling the draw, "
            "executing the fasting protocol, and entering results into the system.",
            # VERBATIM, 2026-09-12 recent_outputs.
            "Execute the fasting protocol precisely: 10+ hours fasting (water only), document the exact "
            "window, and schedule the draw at least 48 hours after your last hard training session.",
            # VERBATIM, 2026-09-13 recent_outputs — the plainest one.
            "Report any unusual fatigue or cold sensitivity before the April draw to establish a " "symptom baseline.",
        ],
    )
    def test_a_past_draw_narrated_as_an_upcoming_appointment_fails(self, text):
        """THE ARM THAT SURVIVED THE DEFECT'S CHANGE OF WORDING.

        On 2026-09-13 the analysis regenerated, stopped saying "zero lab draws", and the
        `_ZERO_LABS_CLAIM` regex found nothing — while telling Matthew in September to
        prepare for a panel drawn on 2026-04-03. A reader was being told to book an
        appointment that had already happened five months earlier, and the check reported
        green. Assert the FACT (the newest draw is in the past), not the wording.
        """
        ok, msg = qa.assess_coach_labs_truth({"total_draws": 8, "latest_draw_date": "2026-04-03"}, _coach(text))
        assert ok is False
        assert "2026-04-03" in msg

    @pytest.mark.parametrize(
        "text",
        [
            "Let's schedule the NEXT panel for October once his lipids have had 12 weeks to move.",
            "I'd book a follow-up draw before drawing any conclusion about the trend.",
            "An upcoming panel should include fasting insulin, which April's did not.",
            "His HbA1c before the April draw was 5.9.",
            "Since the April draw his weight is down 7 lb.",
        ],
    )
    def test_naming_a_future_panel_or_describing_a_past_one_still_passes(self, text):
        """The check must not make honest prose unsayable. Arranging the NEXT panel is
        exactly what a labs coach should do, and describing history relative to a past
        draw ("before the April draw his HbA1c was…") is ordinary past tense."""
        ok, _msg = qa.assess_coach_labs_truth({"total_draws": 8, "latest_draw_date": "2026-04-03"}, _coach(text))
        assert ok is True

    def test_the_weekly_priority_text_is_still_scanned(self):
        ok, msg = qa.assess_coach_labs_truth({"total_draws": 8}, [], weekly_priority_text=LIVE_LABS_SUMMARY)
        assert ok is False
        assert "weekly_priority" in msg


# ══════════════════════════════════════════════════════════════════════════════
# /api/labs CARRIES ITS OWN DENOMINATOR
# ══════════════════════════════════════════════════════════════════════════════


class TestTheServedCountNamesItsScope:
    def test_the_scope_word_is_the_shared_one(self):
        """#2957's vocabulary, not a second string that can drift to "career"."""
        assert lifetime_scope() == "all cycles"

    def test_a_pre_genesis_draw_gets_an_archival_frame(self):
        frame = archival_frame("2026-04-03", "2026-09-06")
        assert frame["pre_cycle"] is True
        assert frame["days_before"] == 156

    def test_an_in_cycle_draw_gets_no_badge(self):
        """An always-on badge trains the reader to ignore it."""
        assert archival_frame("2026-09-10", "2026-09-06") is None

    def test_the_writer_emits_every_scope_field(self):
        """Reader/writer field-name match, asserted against the real source —
        the class this repo has hit six times."""
        src = open(os.path.join(ROOT, "lambdas", "content", "labs_scope.py")).read()
        for field in ("total_draws_scope", "draws_this_cycle", "cycle_genesis", "latest_draw_archival"):
            assert f'"{field}"' in src, field

    def test_the_cycle_count_is_an_explicit_date_comparison(self):
        """`cycle_read_floor` is a NO-OP for a CROSS_PHASE partition by design,
        so no taxonomy helper can produce this number — it has to compare
        against EXPERIMENT_START_DATE directly, and must keep doing so."""
        src = open(os.path.join(ROOT, "lambdas", "content", "labs_scope.py")).read()
        block = src[src.index("def count_draws_this_cycle") : src.index("def scope_fields")]
        assert "EXPERIMENT_START_DATE" in block

    def test_the_front_end_reads_the_fields_the_writer_writes(self):
        js = open(os.path.join(ROOT, "site", "assets", "js", "evidence_body.js")).read()
        assert "total_draws_scope" in js
        assert "draws_this_cycle" in js
        assert "latest_draw_archival" in js
