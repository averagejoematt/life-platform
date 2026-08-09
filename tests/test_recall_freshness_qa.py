"""tests/test_recall_freshness_qa.py — the sensor on the recall writer.

#1384's corpus had no automated writer and no detector. When the hand-run backfill stopped
(2026-07-25), the index simply stopped growing: a reader-visible chronicle week published
unindexed and nothing anywhere said so for 18 days. A retrieval index does not error when it goes
stale — it returns fewer precedents, which is exactly what "there is no precedent" looks
like. ADR-104 calls that manufactured absence.

`recall_indexer` is the mechanism; this is the proof it stayed connected. What is pinned:

  DETECTION — a published installment with no embedding row fails the check BY NAME.
  HOLES     — a gap BEHIND an indexed newest week is still caught. This is the one that
              matters: the obvious implementation (compare newest-to-newest) passes the
              moment the latest week indexes, hiding every older miss behind it.
  HONESTY   — a budget-paused tier reports ⏸, not red. The corpus is *supposed* to stop
              advancing there, and a gate that reds on honest data teaches people to
              ignore it.
  SCOPE     — drafts and phase-invisible installments are not required to be indexed;
              demanding them would red the check on correct behaviour.
  WIRING    — the check is actually in the nightly sweep's run list.

Hermetic — no AWS, no Bedrock, no network, no wall clock.

Run with:   python3 -m pytest tests/test_recall_freshness_qa.py -v
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import pytest  # noqa: E402
from operational import recall_freshness_qa as rf  # noqa: E402

W1, W2, W3 = "2026-08-03", "2026-08-10", "2026-08-17"


def condition_values(cond):
    """Every literal string inside a boto3 KeyConditionExpression, recursively.

    A test double MUST dispatch on the actual key, not on `repr(cond)` — boto3 conditions
    repr as `<boto3.dynamodb.conditions.And object at 0x...>`, so a repr substring check
    silently never matches and the fake answers every query from one branch. That is how
    the first draft of these tests passed while exercising nothing.
    """
    out = []
    try:
        values = cond.get_expression()["values"]
    except Exception:  # noqa: BLE001 — a plain value, not a condition
        return [cond] if isinstance(cond, str) else []
    for v in values:
        if isinstance(v, str):
            out.append(v)
        else:
            out.extend(condition_values(v))
    return out


def _inst(date, *, status="published", phase="experiment"):
    return {"pk": "USER#matthew#SOURCE#chronicle", "sk": f"DATE#{date}", "date": date, "status": status, "phase": phase}


# ── DETECTION ───────────────────────────────────────────────────────────────
def test_a_fully_indexed_corpus_is_green():
    state, msg = rf.assess([W1, W2], [W1, W2])
    assert state == rf.OK
    assert "2 published installment(s)" in msg


def test_an_unindexed_week_fails_and_names_the_date():
    """A count sends someone to query the table; a date does not."""
    state, msg = rf.assess([W1, W2], [W1])
    assert state == rf.FAIL
    assert W2 in msg


def test_the_live_2026_08_08_gap_reproduces():
    """The exact measured state that motivated this: the writer stopped after one week
    and the two installments published since were invisible to recall."""
    state, msg = rf.assess([W1, W2, W3], [W1])
    assert state == rf.FAIL
    assert W2 in msg and W3 in msg
    assert W1 not in msg


# ── HOLES (the property a newest-vs-newest check would miss) ────────────────
def test_a_hole_behind_an_indexed_newest_week_is_still_caught():
    """THE load-bearing case. If the check compared only the newest dates, this passes —
    W3 is indexed, so 'newest embedded >= newest published' holds — while W2 is missing.
    That is precisely the shape an intermittently-failing writer leaves behind, and it is
    the shape that would survive undetected the longest.
    """
    state, msg = rf.assess([W1, W2, W3], [W1, W3])
    assert state == rf.FAIL
    assert W2 in msg


def test_missing_dates_is_set_arithmetic_not_a_watermark():
    assert rf.missing_dates([W1, W2, W3], [W1, W3]) == [W2]
    assert rf.missing_dates([W1, W2], [W1, W2, W3]) == []  # extra corpus rows are not a fault
    assert rf.missing_dates([], [W1]) == []


def test_many_gaps_are_elided_but_counted_honestly():
    published = [f"2026-0{m}-01" for m in range(1, 10)]
    state, msg = rf.assess(published, [])
    assert state == rf.FAIL
    assert "9 published installment(s) MISSING" in msg
    assert "+3 more" in msg


# ── HONESTY ─────────────────────────────────────────────────────────────────
def test_no_published_installments_is_not_a_failure():
    """Genesis week, or the morning after a reset: an empty corpus is the correct state."""
    state, msg = rf.assess([], [])
    assert state == rf.OK
    assert "nothing to index" in msg


def test_a_budget_pause_reports_paused_not_red():
    """Band 2 (ADR-125): the corpus is SUPPOSED to stop advancing at a paused tier."""
    state, msg = rf.assess([W1, W2], [W1], indexing_paused=True)
    assert state == rf.PAUSED
    assert "budget-paused" in msg


def test_a_pause_never_hides_a_green_corpus():
    """The pause branch must not swallow the ordinary result — a paused tier with a
    complete corpus is still green, not perpetually ⏸."""
    assert rf.assess([W1], [W1], indexing_paused=True)[0] == rf.OK


# ── SCOPE ───────────────────────────────────────────────────────────────────
def test_drafts_are_not_required_to_be_indexed():
    """`recall_indexer` deliberately refuses drafts, so requiring them here would red the
    check on correct behaviour — the accuracy-gate-on-honest-data trap."""
    assert rf.published_installment_dates([_inst(W1), _inst(W2, status="draft")]) == [W1]


def test_phase_invisible_installments_are_not_required():
    """A wiped prior-cycle installment has no reader page. It legitimately stays in the
    corpus for cross-cycle recall, but a MISSING one is not a defect."""
    got = rf.published_installment_dates([_inst(W1), _inst("2026-03-04", phase="pilot")])
    assert got == [W1]


# ── WIRING ──────────────────────────────────────────────────────────────────
def test_the_check_is_registered_in_the_nightly_sweep():
    """The failure this whole file exists to prevent is a correct check nobody runs."""
    import importlib.util

    path = os.path.join(_REPO, "lambdas", "operational", "qa_smoke_lambda.py")
    spec = importlib.util.spec_from_file_location("qa_smoke_lambda", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert "recall_freshness" in {label for label, _fn in mod.check_steps()}


def test_the_check_reports_content_truth_not_deploy_health():
    """Partition decides whether a red may trigger ci-cd's fleet auto-rollback. A stale
    narrative index must never roll back the fleet."""
    from operational.qa_check import CONTENT_TRUTH, Check

    class _T:
        def query(self, **kwargs):
            return {"Items": [_inst(W1)]}

    (c,) = rf.checks(_T(), "USER#matthew#SOURCE#chronicle", Check, CONTENT_TRUTH)
    assert c.partition == CONTENT_TRUTH


def test_an_unreadable_table_warns_rather_than_accusing():
    """A throttled query is not evidence that the writer is broken."""
    from operational.qa_check import CONTENT_TRUTH, Check

    class _Broken:
        def query(self, **kwargs):
            raise RuntimeError("throttled")

    (c,) = rf.checks(_Broken(), "USER#matthew#SOURCE#chronicle", Check, CONTENT_TRUTH)
    assert c.passed is None  # yellow
    assert "could not assess" in c.message


def test_end_to_end_against_a_fake_table():
    """The assembled path: chronicle partition + recall partition → one red naming W2."""
    from ai import semantic_recall as sr
    from operational.qa_check import CONTENT_TRUTH, Check

    class _T:
        def query(self, **kwargs):
            if sr.RECALL_PK in condition_values(kwargs.get("KeyConditionExpression")):
                return {"Items": [{"kind": sr.KIND_CHRONICLE, "doc_date": W1}]}
            return {"Items": [_inst(W1), _inst(W2)]}

    (c,) = rf.checks(_T(), "USER#matthew#SOURCE#chronicle", Check, CONTENT_TRUTH)
    assert c.passed is False
    assert W2 in c.message


@pytest.mark.parametrize("state", [rf.OK, rf.FAIL, rf.PAUSED])
def test_every_state_maps_to_a_check_verb(state):
    """The dispatch dict in `checks()` must cover the assessor's whole vocabulary — a
    missing key would raise inside the sweep instead of reporting."""
    from operational.qa_check import CONTENT_TRUTH, Check

    verbs = {rf.OK: "ok", rf.FAIL: "fail", rf.PAUSED: "pause"}
    assert hasattr(Check("t", "t", CONTENT_TRUTH), verbs[state])


# ── the sk / `date`-attribute divergence (found against the live table) ─────
def test_the_check_keys_on_the_sort_key_not_the_date_attribute():
    """A reset's carry-forward re-stamps the `date` ATTRIBUTE and leaves the sk alone, so
    the two disagree on real records — live at the time of writing, `DATE#2026-07-21`
    carried `date = 2026-08-02`.

    The corpus sk is built from the SK date, so keying this check on `date` reports an
    installment that IS indexed as missing. The first live run of this check did exactly
    that: it named "2026-08-02, 2026-08-02" — one week counted twice, and an indexed week
    accused — where the true answer is the single reader-visible 2026-08-02.
    """
    carried = {"pk": "USER#matthew#SOURCE#chronicle", "sk": f"DATE#{W1}", "date": W3, "status": "published", "phase": "experiment"}
    assert rf.published_installment_dates([carried]) == [W1]
    # And with W1 indexed, the check is GREEN — not red about a W3 that was never a key.
    assert rf.assess(rf.published_installment_dates([carried]), [W1])[0] == rf.OK


def test_two_records_claiming_one_date_are_not_reported_twice():
    """The duplicate half of the same defect: distinct installments must stay distinct."""
    a = {"pk": "p", "sk": f"DATE#{W1}", "date": W3, "status": "published", "phase": "experiment"}
    b = {"pk": "p", "sk": f"DATE#{W2}", "date": W3, "status": "published", "phase": "experiment"}
    assert rf.published_installment_dates([a, b]) == [W1, W2]


# ── LINK PARITY (#2366) — the sensor owns link CORRECTNESS, not just existence ──
LIVE_LINK = "/journal/posts/week-01/"
DEAD_LINK = "/chronicle/week-0/"  # #1827's retired scheme — the form on all 17 live rows


def test_a_stored_dead_link_reds_the_qa_and_names_the_repair():
    """The mutation proof, half one: a row that EXISTS but carries a rotted link must
    flag. Existence-only was green on exactly this state for the whole life of #1827."""
    state, msg = rf.assess([W1], [W1], expected_links={W1: LIVE_LINK}, stored_links={W1: DEAD_LINK})
    assert state == rf.FAIL
    assert W1 in msg
    assert "backfill_recall_embeddings.py --apply" in msg  # the report carries its own repair


def test_the_same_row_with_the_resolving_link_is_green():
    """Half two: the identical fixture with the derived link must NOT flag — a parity
    check that reds on correct rows would teach its reader to ignore it."""
    state, msg = rf.assess([W1], [W1], expected_links={W1: LIVE_LINK}, stored_links={W1: LIVE_LINK})
    assert state == rf.OK
    assert "links matching" in msg


def test_a_wiped_installments_stored_link_must_be_absent_not_stale():
    """Honest absence is a value too: a phase-wiped installment derives NO link, so a
    stored leftover URL is rot, not a bonus."""
    state, _ = rf.assess([W1], [W1], expected_links={W1: ""}, stored_links={W1: DEAD_LINK})
    assert state == rf.FAIL


def test_a_missing_row_is_reported_once_as_missing_not_twice():
    """`missing_dates` owns absence; `link_mismatches` must not turn one gap into two."""
    assert rf.link_mismatches({W1: LIVE_LINK}, {}) == []
    state, msg = rf.assess([W1], [], expected_links={W1: LIVE_LINK}, stored_links={})
    assert state == rf.FAIL
    assert "MISSING" in msg
    assert "diverge" not in msg


def test_a_budget_pause_does_not_excuse_a_rotted_link():
    """Band 2 excuses a corpus that stopped ADVANCING — the embed spend. A wrong stored
    link is not a budget consequence and both repair paths are free, so parity stays a
    FAIL at any tier."""
    state, _ = rf.assess([W1], [W1], expected_links={W1: LIVE_LINK}, stored_links={W1: DEAD_LINK}, indexing_paused=True)
    assert state == rf.FAIL


def test_gaps_and_mismatches_are_both_named_in_one_report():
    state, msg = rf.assess([W1, W2], [W1], expected_links={W1: LIVE_LINK, W2: LIVE_LINK}, stored_links={W1: DEAD_LINK})
    assert state == rf.FAIL
    assert W2 in msg and "MISSING" in msg
    assert W1 in msg and "diverge" in msg


def test_assess_without_link_inputs_still_assesses_existence():
    """The pure core stays callable the old way — parity is additive, not a rewrite."""
    assert rf.assess([W1], [W1])[0] == rf.OK
    assert rf.assess([W1, W2], [W1])[0] == rf.FAIL


def test_expectation_scope_matches_the_existence_scope():
    """Drafts and phase-invisible installments are exempt from BOTH sides — demanding a
    link for a row the writer refuses to create would red the check on correct
    behaviour."""
    insts = [_inst(W1), _inst(W2, status="draft"), _inst("2026-03-04", phase="pilot")]
    assert sorted(rf.published_link_expectations(insts)) == rf.published_installment_dates(insts)


def test_expected_links_are_the_writers_own_derivation():
    """Parity by construction: the sensor's expected value is the exact expression
    `recall_indexer.chronicle_doc` stores, keyed the same way — the two cannot drift
    apart without this test failing."""
    from ai.recall_indexer import published_post_links

    insts = [_inst(W1), _inst(W2)]
    links = published_post_links(insts)
    assert rf.published_link_expectations(insts) == {
        W1: links[(W1, f"DATE#{W1}")],
        W2: links[(W2, f"DATE#{W2}")],
    }


def test_end_to_end_a_dead_link_row_flags_and_a_resolving_row_does_not():
    """The assembled mutation pair through `checks()` itself, with the good link DERIVED
    from the current scheme rather than hardcoded — so this test keeps proving parity
    even if the scheme changes again."""
    from ai import semantic_recall as sr
    from ai.recall_indexer import published_post_links
    from operational.qa_check import CONTENT_TRUTH, Check

    def run(stored_link):
        class _T:
            def query(self, **kwargs):
                if sr.RECALL_PK in condition_values(kwargs.get("KeyConditionExpression")):
                    return {"Items": [{"kind": sr.KIND_CHRONICLE, "doc_date": W1, "link": stored_link}]}
                return {"Items": [_inst(W1)]}

        (c,) = rf.checks(_T(), "USER#matthew#SOURCE#chronicle", Check, CONTENT_TRUTH)
        return c

    dead = run(DEAD_LINK)
    assert dead.passed is False
    assert W1 in dead.message

    good = run(published_post_links([_inst(W1)])[(W1, f"DATE#{W1}")])
    assert good.passed is True
