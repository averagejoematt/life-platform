"""
tests/test_character_targets_1412.py — #1412 (ADR-105 rule 4): character pillar-component
targets derived from personal variance.

The character engine's component targets (sleep duration/architecture, daily steps) were
hand-authored constants; ADR-105 rule 4 says thresholds derive from Matthew's OWN
distribution. This suite pins:

  1. the derivation shape functions against fixtures (type-7 percentile bands,
     MIN_N=30 floor-guard — below it the band is None and the authored constant
     survives unchanged);
  2. the provenance contract — every derivable target carries {method, window, n}
     when personal, and the EXACT label "population prior, n<30" when below-floor;
  3. purity — apply_character_targets never mutates the input config (the engine
     caches the S3 config in-process; mutation would leak the overlay into the
     cached copy);
  4. engine consumption — compute_sleep_raw/compute_movement_raw actually score
     against the derived target and surface the provenance in component details;
  5. wiring — the three consumer sites (nightly compute, qa_smoke receipt replay,
     site-api receipt verify) all build the SAME effective config, so receipt
     config-hashes agree across write and replay (#1373: a baselines refresh shows
     as labeled config_drift, never a permanent unlabeled mismatch).
"""

import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "compute"))

import character_engine as ce  # noqa: E402
import personal_baselines as pb  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_ROOT, "config", "character_sheet.json")


def _authored_config():
    with open(_CONFIG_PATH) as f:
        return json.load(f)


def _band(p25, p50, p75, n, window_days=365):
    return {"p25": p25, "p50": p50, "p75": p75, "n": n, "window_days": window_days}


# ══════════════════════════════════════════════════════════════════════════════
# 1. Shape functions pinned against fixtures
# ══════════════════════════════════════════════════════════════════════════════


class TestCharacterTargetBands:
    def test_band_pinned_type7_percentiles(self):
        # 40 evenly spaced sleep durations 6.00..7.95 — type-7 interpolation:
        #   p25 rank 9.75  → 6.4875;  p50 rank 19.5 → 6.975;  p75 rank 29.25 → 7.4625
        vals = [6.0 + 0.05 * i for i in range(40)]
        bands = pb.compute_character_target_bands({"sleep_duration_hours": vals}, window_days=365)
        band = bands["sleep_duration_hours"]
        assert band["n"] == 40
        assert band["window_days"] == 365
        assert abs(band["p25"] - 6.4875) < 1e-9
        assert abs(band["p50"] - 6.975) < 1e-9
        assert abs(band["p75"] - 7.4625) < 1e-9

    def test_min_n_floor_guard(self):
        thin = [7.0] * (pb.MIN_N - 1)
        bands = pb.compute_character_target_bands({"sleep_duration_hours": thin}, window_days=365)
        assert bands["sleep_duration_hours"] is None

    def test_exactly_min_n_produces_band(self):
        vals = [7.0 + 0.01 * i for i in range(pb.MIN_N)]
        bands = pb.compute_character_target_bands({"daily_steps": vals}, window_days=365)
        assert bands["daily_steps"] is not None
        assert bands["daily_steps"]["n"] == pb.MIN_N

    def test_none_and_nonnumeric_dropped(self):
        vals = [7.0] * pb.MIN_N + [None, "x"]
        bands = pb.compute_character_target_bands({"rem_sleep_fraction": vals})
        assert bands["rem_sleep_fraction"]["n"] == pb.MIN_N

    def test_every_spec_metric_is_computed(self):
        bands = pb.compute_character_target_bands({})
        assert set(bands) == set(pb.CHARACTER_TARGET_SPECS)
        assert all(v is None for v in bands.values())


# ══════════════════════════════════════════════════════════════════════════════
# 2. Per-target derivation + provenance {method, window, n} / below-floor label
# ══════════════════════════════════════════════════════════════════════════════


class TestDeriveComponentTarget:
    def test_personal_value_and_provenance(self):
        baselines = {"sleep_duration_hours": _band(6.4875, 6.975, 7.4625, 40)}
        value, prov = pb.derive_component_target("sleep_duration_hours", baselines)
        assert value == 7.46  # p75 rounded to 2dp
        assert prov["source"] == "personal"
        assert prov["method"] == "percentile_band_p75"
        assert prov["window_days"] == 365
        assert prov["n"] == 40

    def test_steps_target_is_integer(self):
        baselines = {"daily_steps": _band(7000.0, 9000.0, 11234.4, 60)}
        value, prov = pb.derive_component_target("daily_steps", baselines)
        assert value == 11234
        assert isinstance(value, int)
        assert prov["source"] == "personal"

    def test_below_floor_label_exact(self):
        baselines = {"sleep_duration_hours": _band(6.5, 7.0, 7.5, pb.MIN_N - 1)}
        value, prov = pb.derive_component_target("sleep_duration_hours", baselines)
        assert value is None
        assert prov["source"] == "population_prior"
        assert prov["label"] == "population prior, n<30"
        assert prov["n"] == pb.MIN_N - 1

    def test_missing_band_labeled_population_prior(self):
        value, prov = pb.derive_component_target("rem_sleep_fraction", {})
        assert value is None
        assert prov["label"] == pb.POPULATION_PRIOR_LABEL
        assert prov["n"] == 0

    def test_guardrail_clamp_is_labeled(self):
        # A pathological personal p75 (10.2h) clamps to the documented safety
        # bound and SAYS so — a derived target may never drift into indefensible
        # territory silently (ADR-105: population guardrails stay, labeled).
        baselines = {"sleep_duration_hours": _band(9.0, 9.8, 10.2, 45)}
        value, prov = pb.derive_component_target("sleep_duration_hours", baselines)
        assert value == 9.0
        assert prov.get("clamped") is True
        assert prov["source"] == "personal"


# ══════════════════════════════════════════════════════════════════════════════
# 3. apply_character_targets — overlay semantics + purity
# ══════════════════════════════════════════════════════════════════════════════


class TestApplyCharacterTargets:
    def test_no_baselines_keeps_authored_values_with_label(self):
        cfg = _authored_config()
        authored = cfg["pillars"]["sleep"]["components"]["duration_vs_target"]["target_hours"]
        out = pb.apply_character_targets(cfg, {})
        comp = out["pillars"]["sleep"]["components"]["duration_vs_target"]
        assert comp["target_hours"] == authored  # unchanged below floor
        assert comp["target_provenance"]["label"] == "population prior, n<30"

    def test_personal_bands_replace_targets(self):
        cfg = _authored_config()
        baselines = {
            "sleep_duration_hours": _band(6.4875, 6.975, 7.4625, 40),
            "daily_steps": _band(7000.0, 9000.0, 11234.4, 60),
        }
        out = pb.apply_character_targets(cfg, baselines)
        sleep_comp = out["pillars"]["sleep"]["components"]["duration_vs_target"]
        steps_comp = out["pillars"]["movement"]["components"]["daily_steps"]
        assert sleep_comp["target_hours"] == 7.46
        assert sleep_comp["target_provenance"]["n"] == 40
        assert steps_comp["target"] == 11234
        # derivable-but-thin metrics stay authored + labeled
        deep = out["pillars"]["sleep"]["components"]["deep_sleep_pct"]
        assert deep["target_pct"] == cfg["pillars"]["sleep"]["components"]["deep_sleep_pct"]["target_pct"]
        assert deep["target_provenance"]["source"] == "population_prior"

    def test_input_config_never_mutated(self):
        cfg = _authored_config()
        snapshot = copy.deepcopy(cfg)
        pb.apply_character_targets(cfg, {"daily_steps": _band(7000.0, 9000.0, 11000.0, 60)})
        assert cfg == snapshot  # the engine's in-process config cache must stay pristine

    def test_none_config_passthrough(self):
        assert pb.apply_character_targets(None, {}) is None

    def test_deterministic_for_receipt_hashing(self):
        # #1373: the overlay feeds config_hash — identical inputs must yield an
        # identical effective config, byte for byte, across repeated calls.
        cfg = _authored_config()
        baselines = {"daily_steps": _band(7000.0, 9000.0, 11234.4, 60)}
        a = pb.apply_character_targets(cfg, baselines)
        b = pb.apply_character_targets(cfg, baselines)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Engine consumption — derived targets actually score, provenance surfaces
# ══════════════════════════════════════════════════════════════════════════════


class TestEngineConsumesDerivedTargets:
    def _sleep_data(self, hours):
        return {"sleep": {"sleep_duration_hours": hours}}

    def test_sleep_duration_scored_against_personal_target(self):
        cfg = _authored_config()
        baselines = {"sleep_duration_hours": _band(6.2, 6.6, 6.9, 45)}
        out = pb.apply_character_targets(cfg, baselines)
        _, details = ce.compute_sleep_raw(self._sleep_data(6.9), out)
        # personal target 6.9 → ratio 1.0 → round((1/1.15)*100, 1) = 87.0
        assert details["duration_vs_target"]["score"] == 87.0
        # against the authored 7.5 it would have been 80.0 — prove the derived
        # value is the one consumed
        _, authored_details = ce.compute_sleep_raw(self._sleep_data(6.9), cfg)
        assert authored_details["duration_vs_target"]["score"] == 80.0

    def test_provenance_surfaces_in_component_details(self):
        cfg = _authored_config()
        baselines = {"sleep_duration_hours": _band(6.2, 6.6, 6.9, 45)}
        out = pb.apply_character_targets(cfg, baselines)
        _, details = ce.compute_sleep_raw(self._sleep_data(7.0), out)
        prov = details["duration_vs_target"]["target_provenance"]
        assert prov["source"] == "personal"
        assert prov["method"] == "percentile_band_p75"
        assert prov["n"] == 45

    def test_population_prior_label_surfaces_in_details(self):
        cfg = _authored_config()
        out = pb.apply_character_targets(cfg, {})  # nothing cleared the floor
        _, details = ce.compute_sleep_raw(self._sleep_data(7.0), out)
        prov = details["duration_vs_target"]["target_provenance"]
        assert prov["label"] == "population prior, n<30"

    def test_steps_component_consumes_personal_target(self):
        cfg = _authored_config()
        baselines = {"daily_steps": _band(7000.0, 9000.0, 10000.0, 60)}
        out = pb.apply_character_targets(cfg, baselines)
        data = {"apple": {"steps": 10000}, "strava_7d": [], "strava_42d": []}
        _, details = ce.compute_movement_raw(data, out)
        # steps 10000 vs personal target 10000 → ratio 1.0 → round((1/1.5)*100,1) = 66.7
        assert details["daily_steps"]["score"] == 66.7
        assert details["daily_steps"]["target_provenance"]["source"] == "personal"

    def test_unlabeled_components_are_untouched(self):
        # Components with no derivation spec (e.g. efficiency) carry no
        # provenance key at all — no fabricated labels (ADR-104).
        cfg = _authored_config()
        out = pb.apply_character_targets(cfg, {})
        assert "target_provenance" not in out["pillars"]["sleep"]["components"]["efficiency"]


# ══════════════════════════════════════════════════════════════════════════════
# 5. load_baselines round-trip + consumer wiring
# ══════════════════════════════════════════════════════════════════════════════


class _FakeTable:
    def __init__(self, item=None):
        self._item = item

    def get_item(self, Key):
        return {"Item": self._item} if self._item else {}


class TestLoadAndWiring:
    def test_load_baselines_coerces_window_days_to_int(self):
        from decimal import Decimal

        item = {
            "bands": {
                "daily_steps": {
                    "p25": Decimal("7000"),
                    "p50": Decimal("9000"),
                    "p75": Decimal("11000"),
                    "n": Decimal("60"),
                    "window_days": Decimal("365"),
                }
            }
        }
        out = pb.load_baselines(_FakeTable(item), "USER#matthew#SOURCE#")
        band = out["daily_steps"]
        assert band["n"] == 60 and isinstance(band["n"], int)
        assert band["window_days"] == 365 and isinstance(band["window_days"], int)

    def test_effective_character_config_end_to_end(self):
        from decimal import Decimal

        cfg = _authored_config()
        item = {
            "bands": {
                "daily_steps": {
                    "p25": Decimal("7000"),
                    "p50": Decimal("9000"),
                    "p75": Decimal("11000"),
                    "n": Decimal("60"),
                    "window_days": Decimal("365"),
                }
            }
        }
        out = pb.effective_character_config(cfg, _FakeTable(item), "USER#matthew#SOURCE#")
        assert out["pillars"]["movement"]["components"]["daily_steps"]["target"] == 11000
        # DDB miss → authored config values survive, labeled
        out_miss = pb.effective_character_config(cfg, _FakeTable(None), "USER#matthew#SOURCE#")
        assert out_miss["pillars"]["movement"]["components"]["daily_steps"]["target"] == 8000
        assert out_miss["pillars"]["movement"]["components"]["daily_steps"]["target_provenance"]["source"] == "population_prior"

    def test_all_replay_sites_build_the_same_effective_config(self):
        # #1373 invariant: the config the nightly compute hashes into receipts
        # and the config qa_smoke / site-api replay against must be built by the
        # SAME helper, or every receipt reads as permanent unlabeled drift.
        sites = {
            "compute": os.path.join(_ROOT, "lambdas", "compute", "character_sheet_lambda.py"),
            "qa_smoke": os.path.join(_ROOT, "lambdas", "operational", "qa_smoke_lambda.py"),
            "site_api": os.path.join(_ROOT, "lambdas", "web", "site_api_vitals.py"),
        }
        for name, path in sites.items():
            with open(path) as f:
                assert "effective_character_config" in f.read(), f"{name} does not build the effective config (#1412)"


# ══════════════════════════════════════════════════════════════════════════════
# 6. Lambda series builders (pure functions)
# ══════════════════════════════════════════════════════════════════════════════


class TestLambdaSeriesBuilders:
    def _import_lambda(self):
        os.environ.setdefault("S3_BUCKET", "test-bucket")
        import personal_baselines_lambda as pbl

        return pbl

    def test_sleep_series_extraction(self):
        pbl = self._import_lambda()
        records = [
            {"sleep_duration_hours": 7.2, "slow_wave_sleep_hours": 1.1, "rem_sleep_hours": 1.5},
            {"sleep_duration_hours": 27000, "deep_sleep_seconds": 4000, "total_sleep_seconds": 27000, "rem_sleep_pct": 0.22},
            {"no_sleep_fields": True},
        ]
        durations, deep, rem = pbl._sleep_series(records)
        assert durations == [7.2, 7.5]  # 27000s → 7.5h
        assert abs(deep[0] - 1.1 / 7.2) < 1e-9
        assert abs(deep[1] - 4000 / 27000) < 1e-9
        assert abs(rem[0] - 1.5 / 7.2) < 1e-9
        assert abs(rem[1] - 0.22) < 1e-9

    def test_steps_series_extraction(self):
        pbl = self._import_lambda()
        records = [{"steps": 8200}, {"steps": 0}, {"steps": None}, {}, {"steps": 12100.0}]
        assert pbl._steps_series(records) == [8200.0, 12100.0]
