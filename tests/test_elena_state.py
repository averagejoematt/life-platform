"""tests/test_elena_state.py — #537: Elena Voss gets a mind.

Pins the PERSONA#elena memory contract:

  E1  the stance sanitizer: no prior stance => no evolution claim; a change
      claim without receipts is narrative invention and gets dropped
  E2  the raw-vitals guard flags fabricated physiological numbers
  E3  apply_extraction is deterministic: callback due-windows clamp to N+1..N+6,
      paid/resolved slugs must come from CURRENT STATE (an invented slug is a
      no-op), motifs merge with counts
  E4  the updater only learns from PUBLISHED installments — a draft or a
      rejected draft can never poison her memory
  E5  both publish paths invoke the updater; draft-time paths don't
  E6  the chronicle prompt gains her notebook (threads with aging, promises
      due as obligations, motifs, receipts-gated stance)
  E7  the chronicle body joins the ADR-104 grounded-generation gate
  E8  the between-chronicle email + podcast host read the same state
"""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHRONICLE_SRC = open(os.path.join(ROOT, "lambdas/emails/wednesday_chronicle_lambda.py")).read()
APPROVE_SRC = open(os.path.join(ROOT, "lambdas/emails/chronicle_approve_lambda.py")).read()
BETWEEN_SRC = open(os.path.join(ROOT, "lambdas/emails/between_chronicle_lambda.py")).read()
PODCAST_SRC = open(os.path.join(ROOT, "lambdas/emails/coach_panel_podcast_lambda.py")).read()
UPDATER_SRC = open(os.path.join(ROOT, "lambdas/emails/elena_state_updater.py")).read()


def _updater():
    with mock.patch("boto3.resource"):
        import importlib

        import emails.elena_state_updater as esu

        importlib.reload(esu)
        return esu


class FakeTable:
    def __init__(self):
        self.puts = []
        self.updates = []

    def put_item(self, Item):
        self.puts.append(Item)

    def update_item(self, **kwargs):
        self.updates.append(kwargs)

    def get_item(self, Key):
        return {}

    def query(self, **kwargs):
        return {"Items": []}


# ── E1: the sanitize discipline ───────────────────────────────────────────────


def test_no_prior_stance_means_no_evolution_claim():
    esu = _updater()
    stance = {"how_my_stance_changed": "I've completely changed my mind", "receipts": ["quote"]}
    esu._sanitize_stance(stance, None)
    assert stance["how_my_stance_changed"] == ""
    assert stance["receipts"] == []


def test_change_claim_without_receipts_is_dropped():
    esu = _updater()
    stance = {"how_my_stance_changed": "I no longer trust the readiness score", "receipts": []}
    esu._sanitize_stance(stance, {"headline_stance": "prior"})
    assert stance["how_my_stance_changed"] == ""


def test_change_claim_with_receipts_is_kept():
    esu = _updater()
    stance = {
        "how_my_stance_changed": "I've come around on the readiness score",
        "receipts": ["'the score called Tuesday's crash before he felt it'"],
    }
    esu._sanitize_stance(stance, {"headline_stance": "prior"})
    assert stance["how_my_stance_changed"]
    assert stance["receipts"]


# ── E2: raw-vitals guard ──────────────────────────────────────────────────────


def test_vital_hits_flags_fabricated_numbers():
    esu = _updater()
    assert esu._vital_hits({"headline_stance": "His HRV hit 58 ms this week"}) > 0
    assert esu._vital_hits({"headline_stance": "recovery sat at 64%"}) > 0
    assert esu._vital_hits({"headline_stance": "the pattern is climbing, not the number"}) == 0


# ── E3: deterministic application ────────────────────────────────────────────


def _base_state():
    return {
        "open_threads": [{"sk": "THREAD#2026-06-24#sleep-debt", "slug": "sleep-debt", "summary": "s", "opened_week": 3}],
        "pending_callbacks": [
            {"sk": "CALLBACK#2026-06-24#bloodwork", "slug": "bloodwork", "promise": "p", "made_in_week": 3, "due_by_week": 6}
        ],
        "motifs": [{"phrase": "the machine hums", "first_week": 2, "count": 1}],
        "stance": {"headline_stance": "prior"},
    }


def test_callback_due_window_clamps():
    esu = _updater()
    fake = FakeTable()
    esu.table = fake
    extraction = {
        "callbacks_made": [
            {"slug": "too-soon", "promise": "a", "due_in_weeks": 0},
            {"slug": "too-late", "promise": "b", "due_in_weeks": 40},
            {"slug": "default-due", "promise": "c", "due_in_weeks": None},
        ]
    }
    esu.apply_extraction(extraction, "2026-07-01", 5, _base_state())
    cbs = {i["slug"]: i for i in fake.puts if str(i.get("sk", "")).startswith("CALLBACK#")}
    assert cbs["too-soon"]["due_by_week"] == 5 + 1
    assert cbs["too-late"]["due_by_week"] == 5 + 6
    assert cbs["default-due"]["due_by_week"] == 5 + 3


def test_invented_slugs_are_noops():
    """callbacks_paid / threads_resolved may only reference CURRENT STATE slugs —
    the LLM can't invent a payoff for a promise that was never made."""
    esu = _updater()
    fake = FakeTable()
    esu.table = fake
    extraction = {
        "callbacks_paid": [{"slug": "never-made", "payoff_note": "x"}],
        "threads_resolved": [{"slug": "never-opened", "resolution": "y"}],
    }
    summary = esu.apply_extraction(extraction, "2026-07-01", 5, _base_state())
    assert summary["callbacks_paid"] == 0
    assert summary["threads_resolved"] == 0
    assert fake.updates == []


def test_real_slugs_are_paid_and_resolved():
    esu = _updater()
    fake = FakeTable()
    esu.table = fake
    extraction = {
        "callbacks_paid": [{"slug": "bloodwork", "payoff_note": "labs landed"}],
        "threads_resolved": [{"slug": "sleep-debt", "resolution": "closed"}],
        "threads_advanced": ["sleep-debt"],
    }
    summary = esu.apply_extraction(extraction, "2026-07-01", 5, _base_state())
    assert summary["callbacks_paid"] == 1
    assert summary["threads_resolved"] == 1
    # updates targeted the stored sk, not a re-derived one
    touched = {u["Key"]["sk"] for u in fake.updates}
    assert "CALLBACK#2026-06-24#bloodwork" in touched
    assert "THREAD#2026-06-24#sleep-debt" in touched


def test_motifs_merge_with_counts():
    esu = _updater()
    fake = FakeTable()
    esu.table = fake
    esu.apply_extraction({"motifs": ["the machine hums", "a new refrain"]}, "2026-07-01", 5, _base_state())
    motif_item = next(i for i in fake.puts if i.get("sk") == "MOTIF#state")
    by_phrase = {m["phrase"]: m for m in motif_item["motifs"]}
    assert by_phrase["the machine hums"]["count"] == 2  # repeat bumped
    assert by_phrase["a new refrain"]["count"] == 1


def test_stance_written_with_receipts_and_flag():
    esu = _updater()
    fake = FakeTable()
    esu.table = fake
    extraction = {
        "stance": {
            "headline_stance": "The experiment is earning my trust, pattern by pattern.",
            "positions": ["the honest-numbers posture is real"],
            "how_my_stance_changed": "",
            "receipts": [],
        }
    }
    summary = esu.apply_extraction(extraction, "2026-07-01", 5, _base_state())
    assert summary["stance_written"] is True
    stance_sks = {i["sk"] for i in fake.puts if str(i.get("sk", "")).startswith("STANCE#")}
    assert stance_sks == {"STANCE#2026-07-01", "STANCE#latest"}
    latest = next(i for i in fake.puts if i["sk"] == "STANCE#latest")
    assert latest["grounding_flag"] is False
    assert latest["persona_id"] == "elena_voss"


# ── E4: drafts never poison memory ────────────────────────────────────────────


def test_updater_refuses_unpublished_installments():
    esu = _updater()
    esu.table = FakeTable()
    with mock.patch.object(esu, "_get_item", return_value={"status": "draft", "content_markdown": "x", "week_number": 5}):
        out = esu.lambda_handler({"date": "2026-07-01"}, None)
    assert out["statusCode"] == 200 and out.get("skipped") == "status=draft"


def test_updater_requires_a_date():
    esu = _updater()
    assert esu.lambda_handler({}, None)["statusCode"] == 400
    assert esu.lambda_handler({"date": "not-a-date"}, None)["statusCode"] == 400


# ── E5: the publish paths invoke, draft paths don't ───────────────────────────


def test_both_publish_paths_invoke_the_updater():
    # approve click
    approve_block = APPROVE_SRC[APPROVE_SRC.index('if action == "approve"') :]
    assert "_invoke_elena_state_updater(date_str)" in approve_block
    # stale-draft sweep
    sweep_block = APPROVE_SRC[APPROVE_SRC.index("def _sweep_stale_drafts") : APPROVE_SRC.index("def lambda_handler")]
    assert "_invoke_elena_state_updater(date_str)" in sweep_block
    # wednesday direct-publish (non-preview branch only)
    assert "_invoke_elena_state_updater(date_str)" in CHRONICLE_SRC
    preview_branch = CHRONICLE_SRC[CHRONICLE_SRC.index("if PREVIEW_MODE:") : CHRONICLE_SRC.index("    else:\n        # ── Standard flow")]
    assert "_invoke_elena_state_updater" not in preview_branch, "draft path must not update her memory"


# ── E6: the chronicle consumes the notebook ───────────────────────────────────


def test_chronicle_prompt_gains_the_notebook():
    assert "_elena_notebook_block(" in CHRONICLE_SRC
    assert "YOUR NOTEBOOK" in CHRONICLE_SRC
    assert "PROMISES DUE" in CHRONICLE_SRC
    assert "OPEN STORY THREADS" in CHRONICLE_SRC
    assert "RUNNING MOTIFS" in CHRONICLE_SRC
    # thread aging is enforced in the block
    assert "STALE" in CHRONICLE_SRC
    # a grounding-flagged stance is never served to the prompt
    assert 'stance.get("grounding_flag")' in CHRONICLE_SRC


# ── E7: ADR-104 on the chronicle body ─────────────────────────────────────────


def test_chronicle_body_joins_the_grounding_gate():
    assert "grounded_generation" in CHRONICLE_SRC
    assert "regen_once" in CHRONICLE_SRC
    assert "allowed_numbers(elena_prompt, user_message)" in CHRONICLE_SRC


# ── E8: the downstream surfaces read the same state ───────────────────────────


def test_between_chronicle_reads_her_stance():
    assert '"PERSONA#elena"' in BETWEEN_SRC
    assert "elena_note" in BETWEEN_SRC
    # garnish, never content — it must not count toward has_real_content
    hrc = BETWEEN_SRC[BETWEEN_SRC.index("def has_real_content") : BETWEEN_SRC.index("def build_email")]
    assert "elena_note" not in hrc


def test_podcast_host_reads_her_state():
    assert '"PERSONA#elena"' in PODCAST_SRC
    assert "_elena_host_state" in PODCAST_SRC


def test_updater_writes_only_the_persona_partition():
    """Every put/update in the updater targets PERSONA_PK — matching the role's
    PERSONA#* LeadingKeys write scope."""
    import re

    for m in re.finditer(r'\.(?:put_item|update_item)\(\s*(?:Item=\{|Key=\{)\s*"pk": ([^,]+),', UPDATER_SRC):
        assert m.group(1).strip() == "PERSONA_PK", f"write outside PERSONA_PK: {m.group(0)}"
