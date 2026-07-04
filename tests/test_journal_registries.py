"""tests/test_journal_registries.py — journal Phase 2 deterministic aggregator (#506).

Pins the pure core of the rebuilt journal_analyzer: per-day rows derived from
pass-1 enrichment (no AI), the entity/behavior registries (counts, never padded
trends), the habitify join, causal-hint → HYPO_CANDIDATE aggregation with quote
provenance, the metric mapping into the hypothesis engine's vocabulary, and the
honest needs_instrumentation split. Also pins J-8: no one_line_summary written.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "intelligence"))

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import journal_analyzer_lambda as jal  # noqa: E402


def _entry(date, **over):
    e = {
        "sk": f"DATE#{date}#journal#evening",
        "body_text": "words " * 30,
        "enriched_themes": ["sleep", "work"],
        "enriched_sentiment": "positive",
        "enriched_mood": 7,
        "enriched_energy": 6,
        "enriched_entities": [{"name": "Sarah", "type": "person", "sentiment": "positive", "role": "support"}],
        "enriched_behaviors": [{"behavior": "morning walk", "valence": "positive", "time_of_day": "morning"}],
        "enriched_causal_hints": [{"cause": "late coffee", "effect": "bad sleep", "quote": "slept badly because of the late coffee"}],
    }
    e.update(over)
    return e


class TestDeriveDailyRow:
    def test_derives_from_enrichment(self):
        row = jal.derive_daily_row(_entry("2026-07-01"), "2026-07-01")
        assert row["dominant_theme"] == "health_body"  # "sleep" theme tag
        assert row["themes"] == ["sleep", "work"]
        assert row["sentiment_label"] == "positive"  # mood 7 → score 0.4
        assert row["model"] == "deterministic-v2"
        assert "one_line_summary" not in row  # J-8: dropped at the writer

    def test_unenriched_entry_returns_none(self):
        bare = {"sk": "DATE#2026-07-01#journal#evening", "body_text": "short note about the day and nothing else at all"}
        assert jal.derive_daily_row(bare, "2026-07-01") is None

    def test_mood_maps_to_score_and_label(self):
        row = jal.derive_daily_row(_entry("2026-07-01", enriched_mood=9), "2026-07-01")
        assert float(row["sentiment_score"]) == 0.8
        assert row["sentiment_label"] == "very_positive"
        row = jal.derive_daily_row(_entry("2026-07-01", enriched_mood=1), "2026-07-01")
        assert row["sentiment_label"] == "very_negative"

    def test_energy_level_honest_absence(self):
        row = jal.derive_daily_row(_entry("2026-07-01", enriched_energy=None), "2026-07-01")
        assert "energy_level" not in row

    def test_theme_categorization(self):
        assert jal.categorize_themes(["gratitude"]) == "gratitude"
        assert jal.categorize_themes(["anxiety about work"]) == "anxiety_stress"
        assert jal.categorize_themes(["quantum physics"]) == "other"
        assert jal.categorize_themes([]) == "other"


class TestEntityRegistry:
    def test_aggregates_across_entries(self):
        dated = [
            ("2026-07-01", _entry("2026-07-01")),
            ("2026-07-03", _entry("2026-07-03", enriched_entities=[{"name": "sarah", "type": "person", "sentiment": "negative"}])),
        ]
        reg = jal.build_entity_registry(dated)
        assert len(reg) == 1  # "Sarah" and "sarah" merge on normalized name
        e = reg[0]
        assert e["mentions"] == 2
        assert e["first_seen"] == "2026-07-01" and e["last_seen"] == "2026-07-03"
        assert e["sentiment_counts"] == {"positive": 1, "negative": 1}

    def test_empty_is_empty(self):
        assert jal.build_entity_registry([]) == []

    def test_malformed_entities_skipped(self):
        # dicts without a name, empty strings, and non-string scalars are skipped;
        # plain strings are VALID (the live-data vintage - see TestStringShapeTolerance)
        dated = [("2026-07-01", _entry("2026-07-01", enriched_entities=[{"type": "person"}, "  ", 42]))]
        assert jal.build_entity_registry(dated) == []


class TestBehaviorRegistry:
    def test_habitify_join(self):
        dated = [("2026-07-01", _entry("2026-07-01"))]
        reg = jal.build_behavior_registry(dated, {"Morning Walk", "Read 30 min"})
        assert reg[0]["habitify_match"] == "Morning Walk"

    def test_no_match_is_none(self):
        dated = [("2026-07-01", _entry("2026-07-01", enriched_behaviors=[{"behavior": "doomscrolling", "valence": "negative"}]))]
        reg = jal.build_behavior_registry(dated, {"Morning Walk"})
        assert reg[0]["habitify_match"] is None

    def test_match_habit_token_subset(self):
        assert jal.match_habit("went for a long morning walk today", {"Morning Walk"}) == "Morning Walk"
        assert jal.match_habit("walk", {"Morning Walk"}) == "Morning Walk"
        assert jal.match_habit("cold plunge", {"Morning Walk"}) is None


class TestHypoCandidates:
    def test_aggregation_with_quote_provenance(self):
        dated = [
            ("2026-07-01", _entry("2026-07-01")),
            (
                "2026-07-02",
                _entry(
                    "2026-07-02",
                    enriched_causal_hints=[{"cause": "Late coffee", "effect": "bad sleep", "quote": "coffee at 6pm wrecked me"}],
                ),
            ),
        ]
        cands = jal.build_hypo_candidates(dated)
        assert len(cands) == 1  # same normalized cause→effect pair merges
        c = cands[0]
        assert c["mentions"] == 2
        assert len(c["quotes"]) == 2
        assert c["quotes"][0]["quote"] == "slept badly because of the late coffee"

    def test_metric_mapping_and_status(self):
        dated = [("2026-07-01", _entry("2026-07-01"))]
        c = jal.build_hypo_candidates(dated)[0]
        # "late coffee" has no tracked metric; "bad sleep" maps → needs instrumentation
        assert c["cause_metric"] is None
        assert c["effect_metric"] == "total_sleep_hrs"
        assert c["status"] == "needs_instrumentation"

    def test_testable_when_both_sides_map(self):
        dated = [
            ("2026-07-01", _entry("2026-07-01", enriched_causal_hints=[{"cause": "hard workout", "effect": "low recovery", "quote": "q"}])),
        ]
        c = jal.build_hypo_candidates(dated)[0]
        assert c["cause_metric"] == "workout" and c["effect_metric"] == "recovery"
        assert c["status"] == "testable"

    def test_same_metric_both_sides_not_testable(self):
        dated = [
            ("2026-07-01", _entry("2026-07-01", enriched_causal_hints=[{"cause": "bad sleep", "effect": "worse sleep", "quote": "q"}]))
        ]
        assert jal.build_hypo_candidates(dated)[0]["status"] == "needs_instrumentation"

    def test_slug_stability(self):
        assert jal.slugify("Late Coffee", "Bad  Sleep") == jal.slugify("late coffee", "bad sleep")


class TestMetricMapping:
    def test_known_mappings(self):
        assert jal.map_phrase_to_metric("deep sleep quality") == "deep_sleep_hrs"
        assert jal.map_phrase_to_metric("felt stressed") == "journal_stress"
        assert jal.map_phrase_to_metric("protein intake") == "protein_g"
        assert jal.map_phrase_to_metric("alcohol") is None

    def test_mapped_metrics_exist_in_spec_vocabulary(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "compute"))
        os.environ.setdefault("S3_BUCKET", "test-bucket")
        import hypothesis_engine_lambda as eng

        for _, metric in jal.METRIC_KEYWORDS:
            assert metric in eng.SPEC_METRICS, f"{metric} not in SPEC_METRICS — the mapping drifted"


class TestJournalCandidateSeeding:
    def test_prompt_block_format(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "compute"))
        os.environ.setdefault("S3_BUCKET", "test-bucket")
        import hypothesis_engine_lambda as eng

        block = eng.format_journal_candidates(
            [
                {
                    "cause": "hard workout",
                    "effect": "low recovery",
                    "cause_metric": "workout",
                    "effect_metric": "recovery",
                    "mentions": 3,
                    "quotes": [{"date": "2026-07-01", "quote": "legs day wrecked my recovery"}],
                }
            ]
        )
        assert "JOURNAL-DERIVED CANDIDATES" in block
        assert "workout -> recovery" in block
        assert "legs day wrecked my recovery" in block
        assert eng.format_journal_candidates([]) == ""


class TestStringShapeTolerance:
    """The live data stores entities/behaviors as plain strings (["Britt"]),
    not the v2 dict sketch — both vintages must aggregate."""

    def test_string_entities(self):
        dated = [("2026-07-01", _entry("2026-07-01", enriched_entities=["Britt", "britt", "Dr. Chen"]))]
        reg = jal.build_entity_registry(dated)
        assert len(reg) == 2
        assert reg[0]["name"] == "Britt" and reg[0]["mentions"] == 2

    def test_string_behaviors_join(self):
        dated = [("2026-07-01", _entry("2026-07-01", enriched_behaviors=["went on a morning walk"]))]
        reg = jal.build_behavior_registry(dated, {"Morning Walk"})
        assert reg[0]["habitify_match"] == "Morning Walk"
