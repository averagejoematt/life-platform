"""tests/test_integrator_public_register_3018.py — #3018: the integrator (board chair)
gets a public-audience register at the PRODUCER, closing the gap #3015 correctly left
open at the read-side chokepoint.

THE SHAPE (mirrors #2972's producer-side fix for the domain coaches' `public_summary`,
via `coach_extraction_prompt` task 12 / `coach_derived_prose.DERIVED_PROSE_FIELDS`):

  * `ai_expert_analyzer_lambda.generate_synthesis` now also asks for `public_summary` in
    the SAME model call as `weekly_priority` (`integrator_prompts.build_synthesis_prompt`),
    grounded jointly with it (`integrator_prompts.gate_json_record`'s tuple-key mode — the
    "guard the SET, not the instance" idiom) and write-guarded through
    `coach.audience_guard.reader_safe` before it ever reaches DynamoDB;
  * `site_api_coach_stance._integrator_digest` — the ONE chokepoint all four public
    consumers share (`/api/coaching-dashboard`, `/api/weekly_priority`,
    `/api/coach_analysis`, `/api/coach_team`) — now PREFERS the guarded public register
    over the owner-directed `analysis` text, re-checking `public_summary` at read time too
    (a belt for rows written before this producer existed) and applying the same guard to
    `cross_domain_notes` (the issue's named adjacent risk);
  * honest-empty survives throughout: no public register yet, or a guard-rejected one,
    still renders nothing — never the owner-directed channel.

Offline: FakeTable/FakeModel doubles for the producer (no AWS, no Bedrock); FakeDdbTable
for the server side (`web.fakes`) — no network anywhere in this file.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "intelligence"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_import_err = None
try:
    import ai_expert_analyzer_lambda as az
    from coach import audience_guard
    from common import retry_utils
    from fakes import FakeDdbTable
    from web import site_api_coach_stance as S
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    az = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"module unavailable: {_import_err}")  # type: ignore

FABRICATED = "You averaged 8412 steps across the week."
CLEAN_PRIORITY = "Hold the evening walk and let the pattern speak for itself."

# Owner-directed (the fixture must be the wire — the real #2972/#3015 finding shape).
# No figures, deliberately — these fixtures exercise the AUDIENCE guard, not the
# ADR-104 grounding gate (that gets its own dedicated fabricated-number fixtures below).
OWNER_DIRECTED = "You've held the evening walk steady this week, Matthew — keep the pull-day template when you're back in the gym."

# Honest public register: first person for the lead, strictly third person for Matthew.
PUBLIC_OK = "Matthew held the evening walk steady this week. I've asked him to keep the pull-day template going."


# ═══════════════════════════════════════════════════════════════════════════
# THE PRODUCER — ai_expert_analyzer_lambda.generate_synthesis
# ═══════════════════════════════════════════════════════════════════════════


class FakeTable:
    def __init__(self):
        self.items: dict = {}
        self.writes: list = []

    def put_item(self, Item):
        self.writes.append(Item)
        self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, **kwargs):
        return {"Items": []}


class FakeModel:
    """Queued replies in order (the last repeats); records every request body."""

    def __init__(self, *replies):
        self.replies = list(replies) or [""]
        self.requests: list = []

    def __call__(self, req, timeout=None):
        self.requests.append(json.loads(req.data.decode()))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return {"content": [{"type": "text", "text": reply}]}

    @property
    def calls(self):
        return len(self.requests)


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(az, "table", t)
    return t


@pytest.fixture
def model(monkeypatch):
    def _install(*replies):
        m = FakeModel(*replies)
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", m)
        monkeypatch.setattr(az, "_get_api_key", lambda: "sk-test")
        return m

    return _install


@pytest.fixture(autouse=True)
def hermetic(monkeypatch):
    az._CANON_FACTS_CACHE.clear()
    monkeypatch.setattr(az, "_load_canonical_facts", lambda: {})
    monkeypatch.setattr(az, "_load_engagement_signal", lambda: {})
    monkeypatch.setattr(az, "_presence_block", lambda: "")
    yield
    az._CANON_FACTS_CACHE.clear()


def _synth(priority, public_summary=None, **extra):
    body = {"weekly_priority": priority, "cross_domain_notes": {}, "disagreements": []}
    if public_summary is not None:
        body["public_summary"] = public_summary
    body.update(extra)
    return json.dumps(body)


class TestProducerEmitsPublicRegister:
    def test_public_summary_is_in_the_synthesis_prompt_contract(self):
        prompt = az.build_synthesis_prompt("coach sections", "{}", "", "")
        assert "public_summary" in prompt
        assert "THIRD person" in prompt or "third person" in prompt.lower()

    def test_a_clean_public_summary_is_written_alongside_the_weekly_priority(self, table, model):
        model(_synth(CLEAN_PRIORITY, PUBLIC_OK))
        out = az.generate_synthesis({"sleep": "s", "training": "t"})
        assert out is not None
        row = table.items[(az.CACHE_PK, "EXPERT#integrator")]
        assert row["analysis"] == CLEAN_PRIORITY
        assert row["public_summary"] == PUBLIC_OK

    def test_no_public_summary_from_the_model_writes_none_not_a_crash(self, table, model):
        """The synthesis contract predates #3018 in older cached prompts/replays —
        a reply with no public_summary key must degrade honestly, never KeyError."""
        model(_synth(CLEAN_PRIORITY))
        out = az.generate_synthesis({"sleep": "s", "training": "t"})
        assert out is not None
        row = table.items[(az.CACHE_PK, "EXPERT#integrator")]
        assert row["analysis"] == CLEAN_PRIORITY
        assert row["public_summary"] is None


class TestWriteGuardRejectsOwnerDirectedPublicText:
    def test_owner_directed_public_summary_is_held_at_write_time(self, table, model):
        """The write-side seam (#2972's shape): a producer that drifts into second
        person must never persist to the public field — reader_safe holds it, and
        the honest-empty degradation is None, never the owner-directed text itself."""
        model(_synth(CLEAN_PRIORITY, OWNER_DIRECTED))
        out = az.generate_synthesis({"sleep": "s", "training": "t"})
        assert out is not None
        row = table.items[(az.CACHE_PK, "EXPERT#integrator")]
        assert row["analysis"] == CLEAN_PRIORITY, "the owner-directed public candidate must not block the owner channel"
        assert row["public_summary"] is None, "an owner-directed public_summary must never reach DynamoDB"


class TestGroundingGuardsTheSetNotTheInstance:
    """#3018's ADR-104 wiring: public_summary is produced by the SAME synthesis call as
    weekly_priority and is graded WITH it (integrator_prompts.gate_json_record's tuple-key
    mode) — the coach_derived_prose.DERIVED_PROSE_FIELDS idiom mirrored at this producer."""

    def test_a_fabricated_number_in_public_summary_alone_holds_the_whole_synthesis(self, table, model):
        table.items[(az.CACHE_PK, "EXPERT#integrator")] = {
            "pk": az.CACHE_PK,
            "sk": "EXPERT#integrator",
            "analysis": "Yesterday's read.",
        }
        fabricated_public = "Matthew averaged 8412 steps this week, and I've asked him to keep it up."
        m = model(
            _synth(CLEAN_PRIORITY, fabricated_public),
            _synth("Recovery climbed 41 points this week.", "Matthew's recovery climbed 41 points this week."),
        )
        assert az.generate_synthesis({"sleep": "s", "training": "t"}) is None
        assert m.calls >= 2, "one corrective rewrite must be attempted before the set holds"
        assert table.writes == [], "a held synthesis writes nothing — not even a clean weekly_priority"
        assert table.items[(az.CACHE_PK, "EXPERT#integrator")]["analysis"] == "Yesterday's read."

    def test_a_corrected_rewrite_publishes_both_fields_from_the_reparsed_record(self, table, model):
        fabricated_public = "Matthew averaged 8412 steps this week."
        fixed = json.dumps(
            {
                "weekly_priority": CLEAN_PRIORITY,
                "public_summary": PUBLIC_OK,
                "cross_domain_notes": {"sleep": "steady"},
                "disagreements": [],
            }
        )
        model(_synth(CLEAN_PRIORITY, fabricated_public), fixed)
        out = az.generate_synthesis({"sleep": "s", "training": "t"})
        assert out is not None
        assert out["weekly_priority"] == CLEAN_PRIORITY
        assert out["public_summary"] == PUBLIC_OK
        assert out["cross_domain_notes"] == {"sleep": "steady"}


# ═══════════════════════════════════════════════════════════════════════════
# THE SERVER — site_api_coach_stance._integrator_digest, the one chokepoint
# ═══════════════════════════════════════════════════════════════════════════


def _integrator_row(**fields):
    row = {"pk": "USER#matthew#SOURCE#ai_analysis", "sk": "EXPERT#integrator", "generated_at": "2026-08-24T17:00:00Z"}
    row.update(fields)
    return row


def _digest(row):
    fake = FakeDdbTable(rows=[row])
    return S._integrator_digest(_g={"table": fake})


class TestServerPrefersThePublicRegister:
    def test_a_clean_public_summary_is_served_in_the_analysis_slot(self):
        """Every one of the four public consumers reads `analysis` — serving the
        guarded public register through that same slot means no per-caller change
        is needed on /api/coaching-dashboard, /api/weekly_priority, /api/coach_analysis,
        or /api/coach_team (#3018's chokepoint, same shape as #2972)."""
        item = _digest(_integrator_row(analysis=OWNER_DIRECTED, public_summary=PUBLIC_OK))
        assert item["analysis"] == PUBLIC_OK

    def test_owner_directed_public_summary_is_re_checked_and_falls_back(self):
        """Belt for rows written before this producer existed / a producer drift:
        an owner-directed public_summary is re-guarded at read time, falling back to
        the pre-#3018 analysis-is-clean check rather than serving it."""
        item = _digest(_integrator_row(analysis=OWNER_DIRECTED, public_summary=OWNER_DIRECTED))
        assert item["analysis"] is None

    def test_honest_empty_when_no_public_register_exists_yet(self):
        """#3018 acceptance: the first real public_summary generates on the NEXT
        weekly run. Until then, a row with no public_summary key at all degrades
        exactly as #3015 shipped it — owner-directed analysis withheld, honest None."""
        item = _digest(_integrator_row(analysis=OWNER_DIRECTED))
        assert "public_summary" not in _integrator_row(analysis=OWNER_DIRECTED)  # precondition
        assert item["analysis"] is None

    def test_clean_analysis_still_serves_when_no_public_summary_exists(self):
        """Unchanged #3015 behavior: analysis that happens to pass the guard on its
        own (no public register yet) still serves — this is not a regression target,
        just documented so the split stays deliberate."""
        item = _digest(_integrator_row(analysis=PUBLIC_OK))
        assert item["analysis"] == PUBLIC_OK


class TestCrossDomainNotesGuard:
    """#3018's named adjacent risk: cross_domain_notes are per-domain sentences from
    the SAME synthesis call, served on the SAME public endpoints as `analysis`, but
    were never guarded. Routed through the same chokepoint in this PR."""

    def test_an_owner_directed_domain_note_is_dropped(self):
        item = _digest(
            _integrator_row(
                analysis=PUBLIC_OK,
                cross_domain_notes={
                    "sleep": "Matthew's sleep debt kept training quality low this week.",
                    "nutrition": OWNER_DIRECTED,
                },
            )
        )
        assert "sleep" in item["cross_domain_notes"]
        assert "nutrition" not in item["cross_domain_notes"]

    def test_clean_domain_notes_all_survive(self):
        notes = {"sleep": "Matthew's sleep debt kept training quality low.", "training": "His sessions stayed consistent."}
        item = _digest(_integrator_row(analysis=PUBLIC_OK, cross_domain_notes=notes))
        assert item["cross_domain_notes"] == notes


class TestTheGuardItself:
    """Fixture-is-the-wire: the exact fabricated finding-shaped text used above is
    genuinely owner-directed, and the honest public rewrite genuinely is not."""

    def test_owner_directed_fixture_is_flagged(self):
        assert audience_guard.is_owner_directed(OWNER_DIRECTED)

    def test_public_fixture_passes(self):
        assert not audience_guard.is_owner_directed(PUBLIC_OK)
