"""#4185 §2.5 — the `banned_term` reader CHECK class, proven against the frozen live corpus.

The §2.1A READER RULES ban list + §2.1F per-coach additions, as a regex in code (moved out of
the Haiku judge): EWMA, autocorrelation, etiology, gate, Mifflin/BMR, logging gap, …

Fixture-driven (tests/grounding_corpus/reader_checks/), never a tree sweep. The shared
contract (`reader_checks_corpus.assert_class_contract`) asserts: every live specimen
that names this class fails it; every fixture that does not name it passes it; and the
MUTATION CONTROL — this class replaced by a no-op — lets every specimen through, so
the test cannot be satisfied by some other class firing.
"""

import reader_checks_corpus as corpus
from coach import reader_checks

CHECK = "banned_term"


def test_live_specimens_fail_controls_pass_and_the_mutation_control_is_red(monkeypatch):
    corpus.assert_class_contract(CHECK, monkeypatch)


def test_one_finding_per_distinct_term_case_insensitive():
    found = [f["claimed"].lower() for f in reader_checks.banned_term("EWMA, ewma, and the Mifflin BMR; n=21.")]
    assert found == ["ewma", "n=21", "bmr", "mifflin"]


def test_plain_words_pass():
    assert reader_checks.banned_term("His running average is rising; easy cardio starts next week.") == []


def test_every_listed_term_carries_a_plain_replacement():
    assert all(plain for _p, _word, plain in reader_checks.READER_BANNED_TERMS)


# #4343 (the 2026-10-01 brief): sleep was held on "went dark" and explorer on
# "protein-primacy" — neither was in the prompt's hand-copied 19-term "Never:" list. The
# prompts now render the list from READER_BANNED_TERMS itself.
def test_every_prompt_word_is_caught_by_its_own_pattern():
    for pat, word, _plain in reader_checks.READER_BANNED_TERMS:
        for part in word.split("/"):
            probe = part + "21" if part.endswith("=") else part
            assert reader_checks.banned_term(f"He wrote {probe} today."), (pat, part)


def test_the_coach_prompts_name_every_banned_word():
    from coach import lead_daily_read

    rules = reader_checks.prompt_reader_rules()
    for _p, word, _plain in reader_checks.READER_BANNED_TERMS:
        assert word in rules and word in lead_daily_read.LEAD_PROMPT, word
    assert "went dark" in rules and "protein-primacy" in rules


def test_the_coach_v2_prompt_renders_the_rules_not_a_copy():
    import inspect

    from ai import ai_calls

    src = inspect.getsource(ai_calls._run_coach_v2_pipeline)
    assert "{_reader_rules}" in src and "_rc.prompt_reader_rules()" in src
    assert "Never: EWMA" not in src  # the retired hand-copied literal
    assert "judge_blacklists(voice_spec)" in src and "{json.dumps(_forbidden[0])}" in src


def test_mutation_control_a_term_added_to_the_tuple_reaches_the_prompt(monkeypatch):
    monkeypatch.setattr(reader_checks, "READER_BANNED_TERMS", reader_checks.READER_BANNED_TERMS + ((r"\bzzqx\b", "zzqx", "plain"),))
    assert "zzqx" in reader_checks.prompt_reader_rules()
