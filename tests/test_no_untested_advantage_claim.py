"""Owner ruling 2026-11-09 (calibration v2): never claim the coaches beat the simple guess on a point estimate alone.

After the 2026-11-09 classification corrections the base-rate Brier skill went slightly positive and every reader
surface printed "so far they beat a simple guess" with no test behind it. These pin that no path claims a win from
an untested skill reading, on either side of zero, and a mutation control shows the guard is what holds it."""

from coach import coach_baseline
from web import record_words


def test_a_positive_point_estimate_never_claims_an_advantage():
    for skill in (0.0001, 0.05, 0.4):
        assert record_words.claimable_advantage(skill) is False
        assert "do not beat" in coach_baseline.skill_sentence(95, skill)
        assert record_words.guess_sentence(record_words.claimable_advantage(skill)) == record_words.GUESS_NOT_YET
        assert "does about as well" in record_words.baseline(50, 95, record_words.claimable_advantage(skill))["text"]


def test_no_reading_stays_too_few():
    assert record_words.claimable_advantage(None) is None
    assert record_words.claimable_advantage(True) is None


def test_mutation_control_the_old_rule_would_claim_the_win():
    old_rule = lambda skill: skill > 0  # noqa: E731 — the pre-2026-11-09 rule, for the control only
    assert record_words.guess_sentence(old_rule(0.05)) == record_words.GUESS_BEATS
    assert record_words.guess_sentence(record_words.claimable_advantage(0.05)) != record_words.GUESS_BEATS
