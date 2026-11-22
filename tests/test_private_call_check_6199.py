"""tests/test_private_call_check_6199.py — #6199 P: the publish-time check for calls the policy keeps private.

Synthetic calls only: two invented coaches, invented claims, invented ids. Every row is filed after the reviewed registry
(``prediction_publication_registry.THROUGH``), so ``classify_call`` / ``classify_ask`` decide it from its structure —
the test asserts each class before relying on it, so a policy change cannot silently turn a fixture public.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _k, _v in {"TABLE_NAME": "life-platform", "S3_BUCKET": "matthew-life-platform", "AWS_REGION": "us-west-2"}.items():
    os.environ.setdefault(_k, _v)  # the approve and Panel modules read these at import
for _p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import prediction_publication as PP  # noqa: E402
from content import autopublish_audit, private_call_check as P, story_pipeline  # noqa: E402

ALPHA, BETA = "COACH#alpha_coach", "COACH#beta_coach"
NAMES = {"alpha_coach": ("Avery Quill", "Quill"), "beta_coach": ("Rowan Fenn", "Fenn")}
FILED = "2026-12-01T09:00:00+00:00"
PRIVATE_ID = "pred_20261201_synthetic_quiet_hours"
PRIVATE_CLAIM = "The subject will log nine quiet hours across the stated testing fortnight without a single break."
PUBLIC_CLAIM = "Daily walking counts will climb past a modest line by the end of the coming test week."
ASK_TEXT = "Rate your mood each morning before opening any screen, and send the rating along unedited."


def _private_call(cycle="17"):
    # filed as an observation (not gradeable) → PRIVATE ``unclassified_subject``; its spec still names a sleep metric
    return {
        "sk": f"PREDICTION#{PRIVATE_ID}",
        "prediction_id": PRIVATE_ID,
        "created_at": FILED,
        "cycle": cycle,
        "filing": {"verdict": "observation"},
        "evaluation": {"metric": "sleep_duration_hours"},
        "claim_natural": PRIVATE_CLAIM,
    }


def _public_call(metric="steps", pid="pred_20261201_synthetic_walking_line", cycle="17"):
    return {
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "created_at": FILED,
        "cycle": cycle,
        "filing": {"verdict": "gradeable"},
        "evaluation": {"metric": metric},
        "claim_natural": PUBLIC_CLAIM,
    }


def _private_ask():
    return {"sk": "COMMITMENT#commit_20261201_synthetic_rating", "created_at": FILED, "commitment_natural": ASK_TEXT}


def _calls(*extra):
    rows = [(ALPHA, _private_call()), (ALPHA, _public_call()), (BETA, _private_ask()), *extra]
    return P.build(rows, NAMES)


def test_the_fixture_rows_are_classified_as_the_test_assumes():
    assert PP.classify_call(ALPHA, _private_call())[0] == PP.PRIVATE
    assert PP.classify_call(ALPHA, _public_call())[0] == PP.PUBLIC
    assert PP.classify_ask(BETA, _private_ask())[0] == PP.PRIVATE
    calls = _calls()
    assert len(calls.private) == 2  # the call AND the ask (classify_ask coverage)
    assert calls.is_private(ALPHA, PRIVATE_ID) and not calls.is_private(ALPHA, "pred_20261201_synthetic_walking_line")
    assert calls.is_private(ALPHA, "pred_never_read"), "a call this run did not read counts as private (fail closed)"


# ── the three rules, each with its public twin ───────────────────────────────


def test_rule_1_echo_of_a_private_call_or_ask_blocks_and_the_public_twin_does_not():
    calls = _calls()
    assert any(
        "(echo," in f for f in P.findings("Elena wrote that he would log nine quiet hours across the stated testing fortnight.", calls)
    )
    assert any("(echo," in f for f in P.findings("The coach asked him to rate your mood each morning before opening any screen.", calls))
    assert P.findings("He said daily walking counts will climb past a modest line by the end of the coming test week.", calls) == []


def test_rule_1_ignores_runs_of_function_words_dates_and_figures():
    calls = P.build([(ALPHA, {**_private_call(), "claim_natural": "On the night of September 6 and the morning of the 7th."})], NAMES)
    assert P.findings("It rained on the night of September 6 and the morning of the 7th.", calls) == []


def test_rule_2_a_private_id_in_any_slug_form_blocks():
    calls = _calls()
    for text in (f"see {PRIVATE_ID}", "see /calls/pred-20261201-synthetic-quiet-hours/", "SEE PRED_20261201_SYNTHETIC_QUIET_HOURS"):
        assert any("(id," in f for f in P.findings(text, calls)), text
    assert P.findings("see pred_20261201_synthetic_walking_line", calls) == []


def test_rule_3_a_described_private_call_blocks_only_without_a_public_twin_on_that_topic():
    sentence = "Quill's sleep call missed by a wide margin."
    assert any("(described," in f for f in P.findings(sentence, _calls()))
    twin = (ALPHA, _public_call(metric="sleep_duration_hours", pid="pred_20261201_synthetic_sleep_line"))
    assert P.findings(sentence, _calls(twin)) == [], "a public call on the same coach and topic keeps the sentence publishable"
    # the twin must be in the SAME cycle
    other_cycle = (ALPHA, _public_call(metric="sleep_duration_hours", pid="pred_20261201_synthetic_sleep_old", cycle="16"))
    assert any("(described," in f for f in P.findings(sentence, _calls(other_cycle)))


def test_rule_3_needs_the_coach_the_topic_and_a_call_word_in_one_sentence():
    calls = _calls()
    assert P.findings("Quill read the sleep data closely.", calls) == []  # no call word
    assert P.findings("Fenn's sleep call missed.", calls) == []  # another coach
    assert P.findings("Quill's steps call missed.", calls) == []  # a topic with a public call
    assert P.findings("Quill was wrong. The sleep data was noisy.", calls) == []  # two sentences


def test_his_own_nonsensitive_detail_is_not_blocked():
    calls = _calls()
    text = (
        "He weighed in at the heaviest he has been in years, lifted four days running, and said the AI's advice annoyed "
        "him. Quill's steps call came good on Thursday."
    )
    assert P.findings(text, calls) == []


def test_findings_never_carry_the_calls_words_id_or_coach():
    calls = _calls()
    found = P.findings(f"Quill's sleep call missed. {PRIVATE_CLAIM} {PRIVATE_ID}", calls)
    assert found
    blob = " ".join(found).lower()
    for leak in ("quiet hours", PRIVATE_ID, "quill", "alpha", "sleep"):
        assert leak not in blob


def test_unreadable_calls_fail_closed_and_a_tombstoned_call_is_not_matched():
    assert P.findings("anything at all", None) == [P.UNAVAILABLE]
    calls = P.build([(ALPHA, {**_private_call(), "tombstone": True})], NAMES)
    assert P.findings(PRIVATE_CLAIM, calls) == []


class _Table:
    """A stub table: query(KeyConditionExpression) by pk + sk prefix over in-memory rows, one page each."""

    def __init__(self, rows, fail=False):
        self.rows, self.fail, self.queries = rows, fail, []

    def query(self, **kw):
        if self.fail:
            raise RuntimeError("table unreachable")
        expr = kw["KeyConditionExpression"]
        vals = [c._values for c in expr._values]  # (pk == x) & begins_with(sk, y)
        pk, prefix = vals[0][1], vals[1][1]
        self.queries.append((pk, prefix))
        return {"Items": [r for p, r in self.rows if p == pk and str(r.get("sk", "")).startswith(prefix)]}


def test_load_reads_every_coach_partition_for_calls_and_asks(monkeypatch):
    from web import publication_snapshot

    monkeypatch.setattr(publication_snapshot, "partitions", lambda: (ALPHA, BETA, "ENSEMBLE#docket"))
    monkeypatch.setattr(P, "coach_names", lambda ids: NAMES)
    t = _Table([(ALPHA, _private_call()), (ALPHA, _public_call()), (BETA, _private_ask())])
    calls = P.load(t)
    assert {(pk, pre) for pk, pre in t.queries} >= {(ALPHA, "PREDICTION#"), (ALPHA, "COMMITMENT#"), (BETA, "COMMITMENT#")}
    assert all(not pk.startswith("ENSEMBLE#") for pk, _ in t.queries)
    assert len(calls.private) == 2
    with pytest.raises(RuntimeError):
        P.load(_Table([], fail=True))


# ── the wiring: every place text becomes public ─────────────────────────────

CLEAN_POST = '"A Quiet Week"\n\nHe walked every day and lifted twice. The scale moved a little.\n\n*Week 3 of The Measured Life*'
LEAKY_POST = '"A Quiet Week"\n\nHe walked every day. Quill\'s sleep call missed.\n\n*Week 3 of The Measured Life*'


@pytest.fixture
def no_fact(monkeypatch):
    """The fact read is a model call; these tests compare the deterministic gates around it."""
    monkeypatch.setattr(story_pipeline.story_writers, "fact_check", lambda *a, **k: [])


def _gates(calls=P.NOT_WIRED):
    return story_pipeline._Gates(3, {}, {}, {}, None, {}, private_calls=calls)


def test_the_desk_gates_hold_a_leaky_post_episode_and_dek(no_fact):
    g = _gates(_calls())
    assert any(f.startswith(P.PREFIX) for f in g.post_deterministic(LEAKY_POST, "end_turn"))
    assert any(
        f.startswith(P.PREFIX) for f in g.episode({"turns": [{"speaker": "elena", "line": "Quill's sleep call missed."}]}, "end_turn")
    )
    assert any(P.PREFIX in f for f in g.dek_hard("Quill's sleep call missed."))
    assert not [f for f in g.post_deterministic(CLEAN_POST, "end_turn") if f.startswith(P.PREFIX)]
    assert _gates(None).private("clean text") == [P.UNAVAILABLE], "unreadable calls hold every text on the live path"
    assert _gates().private(LEAKY_POST) == [], "an unwired (offline) gate skips the check"


def test_the_legacy_writer_gate_holds_a_leaky_draft_both_switch_positions():
    g = _gates(_calls())
    assert any(f.startswith(P.PREFIX) for f in story_pipeline.legacy_findings(g, LEAKY_POST, {}))
    found = story_pipeline.legacy_gate_findings(g, LEAKY_POST, {}, fact_check=lambda *a, **k: [])
    assert any(f.startswith(P.PREFIX) for f in found)


def test_the_live_paths_build_their_gates_with_the_calls(monkeypatch):
    """live_week and legacy_audit read the calls (``load_private_calls``) — the read that arms the gates."""
    import inspect

    for fn in (story_pipeline.live_week, story_pipeline.legacy_audit):
        assert "private_calls=load_private_calls(table)" in inspect.getsource(fn), fn.__name__
    monkeypatch.setattr(P, "load", lambda t: (_ for _ in ()).throw(RuntimeError("down")))
    assert story_pipeline.load_private_calls(object()) is None


def test_the_autopublish_audit_blocks_a_leaky_draft_and_fails_closed():
    item = {
        "status": "draft",
        "date": "2026-12-08",
        "title": "T",
        "content_markdown": LEAKY_POST,
        "desk_findings_json": '{"post": [], "episode": []}',
    }
    assert any(f.startswith(P.PREFIX) for f in autopublish_audit.blocking_items(item, private_calls=_calls(), check_private_calls=True))
    assert P.UNAVAILABLE in autopublish_audit.blocking_items(
        {**item, "content_markdown": CLEAN_POST}, private_calls=None, check_private_calls=True
    )
    assert not [f for f in autopublish_audit.blocking_items(item) if f.startswith(P.PREFIX)], "the flag is what arms it"


def test_the_approve_click_and_the_sweep_read_the_calls(monkeypatch):
    from emails import chronicle_approve_lambda as approve

    item = {
        "status": "draft",
        "date": "2026-12-08",
        "title": "T",
        "content_markdown": LEAKY_POST,
        "desk_findings_json": '{"post": [], "episode": []}',
    }
    monkeypatch.setattr(approve, "_private_calls", lambda: _calls())
    assert any(f.startswith(P.PREFIX) for f in approve.approval_refusal(item))
    monkeypatch.setattr(approve, "_private_calls", lambda: None)
    assert P.UNAVAILABLE in approve._audit_refusal({**item, "content_markdown": CLEAN_POST})


def test_the_panel_safety_gate_checks_every_line_once_armed(monkeypatch):
    from emails import coach_panel_podcast_lambda as panel, panelcast_desk

    monkeypatch.setattr(panelcast_desk, "_PRIVATE_CALLS", {"armed": False, "calls": None})
    line = "And Quill's sleep call missed, Elena."
    assert "private-call" not in panel._safety_gate(line), "unarmed (a unit test on a literal) skips it"
    monkeypatch.setattr(P, "load", lambda t: _calls())
    panelcast_desk.arm_private_calls(object())
    assert "private-call" in panel._safety_gate(line)
    assert "private-call" not in panel._safety_gate("He walked every day this week, Elena.")
    monkeypatch.setattr(P, "load", lambda t: (_ for _ in ()).throw(RuntimeError("down")))
    panelcast_desk.arm_private_calls(object())
    assert panel._safety_gate("He walked every day this week, Elena.") == ["private-call-check-unavailable"]


def test_the_panel_handler_and_the_recut_arm_the_check():
    import inspect

    from emails import coach_panel_podcast_lambda as panel

    assert "arm_private_calls(table)" in inspect.getsource(panel.lambda_handler)
    with open(os.path.join(ROOT, "scripts", "panel_recut.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert src.index("arm_private_calls(") < src.index("gate_findings(turns, panel._safety_gate)")


def test_season_promote_refuses_staged_text_that_names_a_private_call(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("season_promote_6199", os.path.join(ROOT, "scripts", "season_promote.py"))
    sp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sp)
    (tmp_path / "wk3_chronicle.md").write_text(CLEAN_POST, encoding="utf-8")
    (tmp_path / "wk3_episode.json").write_text(
        json.dumps({"turns": [{"line": "Quill's sleep call missed."}], "title": "Ep"}), encoding="utf-8"
    )
    found = sp.private_call_gate(str(tmp_path), [3], _calls())
    assert found and all(f.startswith("week 3: private call:") for f in found)
    (tmp_path / "wk3_episode.json").write_text(json.dumps({"turns": [{"line": "He walked."}]}), encoding="utf-8")
    assert sp.private_call_gate(str(tmp_path), [3], _calls()) == []
    refused = sp.private_call_gate(str(tmp_path), [3], load=lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert refused and "could not be read" in refused[0]


def test_revision_verify_reports_a_private_call_and_fails_only_when_strict():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "chronicle_revision_apply_6199", os.path.join(ROOT, "scripts", "chronicle_revision_apply.py")
    )
    cra = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cra)
    m = {"verify": [{"url": "https://example.invalid/chapter/", "phrases": ["an old phrase"]}]}
    page = "<html><body><p>Quill's sleep call missed.</p></body></html>"
    log: list = []
    assert cra.verify(m, lambda u: page, private_calls=_calls(), log=log.append) == 0
    assert any(line.startswith("PRIVATE https://example.invalid/chapter/") for line in log)
    assert cra.verify(m, lambda u: page, private_calls=_calls(), strict=True, log=lambda s: None) == 1
    assert cra.verify(m, lambda u: "<p>He walked.</p>", private_calls=_calls(), strict=True, log=lambda s: None) == 0


# ── production behaviour for clean inputs is unchanged ───────────────────────


def test_a_clean_week_gates_byte_identically_with_and_without_the_check(no_fact):
    dossier = {
        "week": 3,
        "training": {"strava_walks": [{"date": "2026-12-02", "miles": 2.1}]},
        "owner_voice": {"answers": [{"answer": "fine"}]},
    }
    episode = {"turns": [{"speaker": "elena", "line": "He walked every day this week."}], "title": "Ep", "excerpt": "A walk."}
    off, on = story_pipeline._Gates(3, dossier, {}, {}, None, {}), story_pipeline._Gates(
        3, dossier, {}, {}, None, {}, private_calls=_calls()
    )
    for name, args in (("post_deterministic", (CLEAN_POST, "end_turn")), ("craft_post", (CLEAN_POST,)), ("dek_hard", ("A quiet week.",))):
        assert json.dumps(getattr(off, name)(*args)) == json.dumps(getattr(on, name)(*args)), name
    assert json.dumps(off.episode(episode, "end_turn")) == json.dumps(on.episode(episode, "end_turn"))
    assert json.dumps(off.post(CLEAN_POST, "end_turn")) == json.dumps(on.post(CLEAN_POST, "end_turn"))
