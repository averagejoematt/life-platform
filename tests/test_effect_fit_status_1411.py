"""tests/test_effect_fit_status_1411.py — fitted, not authored (#1411, ADR-105).

The cross-pillar effects (Sleep Drag, Training Boost, Synergy Bonus, …) were
authored config multipliers with no fitting step — narrative-shaped priors
wearing the same clothes as measured relationships. The #1411 contract:

  * every effect declares a ``fit_status`` (fitted | authored-prior); the config
    can only ever DECLARE the prior — "fitted" is earned exclusively from data
    by the quarterly re-fit (effect_fitter.fit_effects), never hand-authored;
  * each effect is tested as lagged driver→target pairs with a moving-block
    bootstrap CI + BH-FDR across the family (stats_core — the one sanctioned
    implementation), n_eff from autocorrelation-corrected sample size;
  * an effect ships as "fitted" only when the CI excludes the null in the
    authored direction AND it survives FDR AND n_eff clears the floor —
    otherwise it wears the badge "authored prior — not yet confirmed (n_eff=…)";
  * status moves in BOTH directions — every re-fit recomputes from scratch;
  * null fits feed /api/wrong (an authored prior that fails to confirm is a
    published finding, not a buried one).

Guard classes marked "red pre-fix" FAIL on the pre-#1411 tree.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import character_engine  # noqa: E402
import effect_fitter  # noqa: E402
import phase_taxonomy as pt  # noqa: E402
from web import site_api_intelligence as intel  # noqa: E402

CONFIG_PATH = os.path.join(_REPO, "config", "character_sheet.json")


# ── Synthetic daily character_sheet records ──────────────────────────────────
def _records(days, driver_fn, target_fn, driver_pillar="movement", target_pillar="metabolic", start="2024-01-01"):
    """Build daily sheet records where target(t) is target_fn(t, driver(t-1))."""
    d0 = datetime.strptime(start, "%Y-%m-%d")
    out = []
    prev_driver = 50.0
    for i in range(days):
        date = (d0 + timedelta(days=i)).strftime("%Y-%m-%d")
        drv = driver_fn(i)
        tgt = target_fn(i, prev_driver)
        rec = {"date": date}
        for p in ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"):
            rec[f"pillar_{p}"] = {"raw_score": 50.0}
        rec[f"pillar_{driver_pillar}"] = {"raw_score": drv}
        rec[f"pillar_{target_pillar}"] = {"raw_score": tgt}
        prev_driver = drv
        out.append(rec)
    return out


def _one_effect_config(name="Training Boost", condition="movement > 70", target="metabolic", value=0.05):
    return {
        "cross_pillar_effects": [{"name": name, "condition": condition, "targets": {target: {"type": "multiplicative", "value": value}}}]
    }


def _wave(i):
    """A driver with a slow trend + strong deterministic day-to-day noise —
    variance without the heavy lag-1 autocorrelation that would (correctly)
    collapse n_eff under the AR(1) correction."""
    import math

    n = math.sin(i * 12.9898) * 43758.5453
    noise = (n - math.floor(n)) - 0.5  # deterministic pseudo-uniform in [-0.5, 0.5)
    return 50.0 + 15.0 * math.sin(i / 9.0) + 40.0 * noise


# ═════════════════════════════════════════════════════════════════════════════
# 1. Config guard — every effect declares its status (RED pre-fix)
# ═════════════════════════════════════════════════════════════════════════════
class TestConfigDeclaresFitStatus:
    def test_every_effect_declares_fit_status(self):
        """RED pre-fix: the live config carried no fit_status anywhere."""
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        effects = cfg.get("cross_pillar_effects", [])
        assert effects, "config lost its cross_pillar_effects"
        for e in effects:
            assert e.get("fit_status") in ("authored-prior", "fitted"), f"effect {e.get('name')!r} declares no fit_status (#1411)"

    def test_config_never_hand_authors_fitted(self):
        """The checked-in config may only DECLARE the prior — "fitted" is earned
        from data by the quarterly re-fit and merged at compute/serve time."""
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        for e in cfg.get("cross_pillar_effects", []):
            assert (
                e.get("fit_status") == "authored-prior"
            ), f"effect {e.get('name')!r} hand-authors status {e.get('fit_status')!r} — fitted must be earned, not written"


# ═════════════════════════════════════════════════════════════════════════════
# 2. Engine guard — active effects carry the badge (RED pre-fix)
# ═════════════════════════════════════════════════════════════════════════════
class TestActiveEffectsCarryBadge:
    def test_active_effect_carries_fit_fields(self):
        """RED pre-fix: compute_cross_pillar_effects emitted name/emoji/condition/
        targets only — an active effect said nothing about whether it was ever
        confirmed by data."""
        active, _mods = character_engine.compute_cross_pillar_effects({"movement": 80.0, "metabolic": 50.0}, _one_effect_config())
        assert len(active) == 1
        eff = active[0]
        assert eff.get("fit_status") == "authored-prior"  # nothing merged → the honest default
        assert "fit_n_eff" in eff and "fit_ci_95" in eff
        assert "authored prior" in (eff.get("fit_badge") or ""), "active effect carries no honest badge"

    def test_active_effect_reflects_merged_fit(self):
        cfg = _one_effect_config()
        e = cfg["cross_pillar_effects"][0]
        e["fit_status"] = "fitted"
        e["fit_n_eff"] = 42.0
        e["fit_ci_95"] = [0.08, 0.31]
        e["fit_badge"] = "fitted — n_eff=42, 95% CI [0.08, 0.31]"
        active, _ = character_engine.compute_cross_pillar_effects({"movement": 80.0, "metabolic": 50.0}, cfg)
        assert active[0]["fit_status"] == "fitted"
        assert active[0]["fit_n_eff"] == 42.0
        assert active[0]["fit_ci_95"] == [0.08, 0.31]


# ═════════════════════════════════════════════════════════════════════════════
# 3. The fitter — deterministic verdicts from data (stats_core, ADR-105)
# ═════════════════════════════════════════════════════════════════════════════
class TestFitterVerdicts:
    def test_real_lagged_signal_fits(self):
        """A genuine driver→next-day-target relationship earns "fitted"."""
        import random

        rng = random.Random(7)
        recs = _records(240, _wave, lambda i, prev: 0.85 * prev + 8.0 + rng.gauss(0, 4))
        out = effect_fitter.fit_effects(recs, _one_effect_config())
        eff = out["effects"]["Training Boost"]
        assert eff["status"] == "fitted"
        assert eff["reason"] == "confirmed"
        assert eff["n_eff"] >= effect_fitter.MIN_N_EFF
        lo, hi = eff["ci_95"]
        assert lo > 0.0 and hi <= 1.0
        row = eff["targets"][0]
        assert row["p_adj"] is not None and row["p_adj"] < 0.05  # BH-FDR wired

    def test_pure_noise_stays_authored_prior(self):
        """No relationship → CI straddles the null → the prior is NOT confirmed."""
        import random

        rng = random.Random(11)
        recs = _records(240, lambda i: 50.0 + rng.gauss(0, 12), lambda i, prev: 50.0 + rng.gauss(0, 12))
        out = effect_fitter.fit_effects(recs, _one_effect_config())
        eff = out["effects"]["Training Boost"]
        assert eff["status"] == "authored-prior"
        assert eff["reason"] == "null_not_excluded"
        assert eff["n_eff"] >= effect_fitter.MIN_N_EFF  # tested with real n — an honest null, not thin data

    def test_thin_history_is_insufficient_n(self):
        recs = _records(10, _wave, lambda i, prev: 0.85 * prev + 8.0)
        out = effect_fitter.fit_effects(recs, _one_effect_config())
        eff = out["effects"]["Training Boost"]
        assert eff["status"] == "authored-prior"
        assert eff["reason"] == "insufficient_n"

    def test_confident_opposite_sign_is_never_fitted(self):
        """A CI that excludes the null on the WRONG side must not confirm the
        prior — the authored direction is part of the claim."""
        import random

        rng = random.Random(3)
        recs = _records(240, _wave, lambda i, prev: 120.0 - 0.85 * prev + rng.gauss(0, 4))
        out = effect_fitter.fit_effects(recs, _one_effect_config())
        eff = out["effects"]["Training Boost"]
        assert eff["status"] == "authored-prior"
        assert eff["reason"] == "sign_mismatch"

    def test_deterministic(self):
        recs = _records(120, _wave, lambda i, prev: 0.6 * prev + 20.0)
        a = effect_fitter.fit_effects(recs, _one_effect_config(), as_of_date="2026-07-19")
        b = effect_fitter.fit_effects(recs, _one_effect_config(), as_of_date="2026-07-19")
        assert a == b

    def test_vice_driver_absent_from_sheet_is_honest_zero(self):
        """The sheet partition stores no per-day vice streaks — the Vice Shield
        fit must answer n=0/insufficient, never fabricate a driver."""
        recs = _records(120, _wave, lambda i, prev: prev)
        cfg = _one_effect_config(name="Vice Shield", condition="any_vice_streak > 30", target="mind", value=0.03)
        out = effect_fitter.fit_effects(recs, cfg)
        eff = out["effects"]["Vice Shield"]
        assert eff["status"] == "authored-prior"
        assert eff["reason"] == "insufficient_n"
        assert eff["targets"][0]["n"] == 0

    def test_multi_target_and_conjunction_specs_derive_from_config(self):
        cfg = {
            "cross_pillar_effects": [
                {"name": "Sleep Drag", "condition": "sleep < 35", "targets": {"movement": {"value": -0.08}, "mind": {"value": -0.05}}},
                {"name": "Synergy Bonus", "condition": "nutrition > 70 AND movement > 70", "targets": {"metabolic": {"value": 0.08}}},
                {"name": "Alignment Bonus", "condition": "all_pillars >= 41", "targets": {"_all": {"value": 0.03}}},
            ]
        }
        specs = effect_fitter.derive_fit_specs(cfg)
        by_effect = {}
        for s in specs:
            by_effect.setdefault(s["effect"], []).append(s)
        assert len(by_effect["Sleep Drag"]) == 2  # one lagged pair per target
        assert by_effect["Synergy Bonus"][0]["drivers"]["pillars"] == ["nutrition", "movement"]  # binding constraint = min
        assert by_effect["Alignment Bonus"][0]["drivers"]["kind"] == "all_pillars"
        assert all(s["lag_days"] == 1 for s in specs)

    def test_badge_grammar(self):
        assert "authored prior — not yet confirmed (n_eff=0)" == effect_fitter.badge_text({"fit_status": "authored-prior"})
        fitted = effect_fitter.badge_text({"fit_status": "fitted", "fit_n_eff": 42.3, "fit_ci_95": [0.08, 0.31]})
        assert fitted.startswith("fitted") and "n_eff=42" in fitted and "0.08" in fitted


# ═════════════════════════════════════════════════════════════════════════════
# 4. The fit record — DDB shape (Decimal, cross-phase, quarterly cadence)
# ═════════════════════════════════════════════════════════════════════════════
class TestFitRecord:
    def _fit(self):
        recs = _records(120, _wave, lambda i, prev: 0.6 * prev + 20.0)
        return effect_fitter.fit_effects(recs, _one_effect_config(), as_of_date="2026-07-19")

    def test_item_is_decimal_safe(self):
        item = effect_fitter.build_fit_item(self._fit(), "matthew")
        assert item["pk"] == "USER#matthew#SOURCE#effect_fits"
        assert item["sk"] == "FIT#2026-07-19"

        def _no_floats(o, path="$"):
            if isinstance(o, float):
                raise AssertionError(f"raw float at {path} — boto3 rejects float; Decimal required")
            if isinstance(o, dict):
                for k, v in o.items():
                    _no_floats(v, f"{path}.{k}")
            if isinstance(o, list):
                for i, v in enumerate(o):
                    _no_floats(v, f"{path}[{i}]")

        _no_floats(item)
        assert any(isinstance(v, Decimal) for v in _walk_leaves(item)), "numeric fit facts should survive as Decimal"

    def test_partition_is_classified_cross_phase(self):
        """New partitions land classified (ADR-077) — fits are a long-run
        measurement of the PLATFORM's priors, not of a cycle."""
        assert pt.classify("USER#matthew#SOURCE#effect_fits", "FIT#2026-07-19") == pt.CROSS_PHASE

    def test_refit_due_quarterly_both_directions(self):
        assert effect_fitter.refit_due(None, "2026-07-19") is True  # never fitted → due
        assert effect_fitter.refit_due({"sk": "FIT#2026-07-01"}, "2026-07-19") is False
        assert effect_fitter.refit_due({"sk": "FIT#2026-04-01"}, "2026-07-19") is True  # >90d → re-earn or lose the badge

    def test_merge_fit_into_config_round_trip(self):
        cfg = _one_effect_config()
        cfg["cross_pillar_effects"][0]["fit_status"] = "authored-prior"
        fit = self._fit()
        item = effect_fitter.build_fit_item(fit, "matthew")
        merged = effect_fitter.merge_fit_into_config(cfg, effect_fitter._plain(item))
        e = merged["cross_pillar_effects"][0]
        assert e["fit_status"] in ("fitted", "authored-prior")
        assert e["fit_badge"]
        assert e["fitted_at"] == "2026-07-19"

    def test_receipt_config_hash_is_fit_blind(self):
        """#1373 interplay: the runtime fit merge changes NO computed number, so
        it must not roll the progression-receipt config_hash — otherwise every
        replay against the pristine S3 config reads as spurious config_drift
        and each quarterly fit fakes a mechanical config change."""
        import progression_receipts as pr

        cfg = _one_effect_config()
        cfg["cross_pillar_effects"][0]["fit_status"] = "authored-prior"
        before = pr.config_hash(cfg)
        item = effect_fitter.build_fit_item(self._fit(), "matthew")
        effect_fitter.merge_fit_into_config(cfg, effect_fitter._plain(item))
        assert pr.config_hash(cfg) == before
        # A REAL knob change must still roll the hash (the receipt's whole point).
        cfg["cross_pillar_effects"][0]["targets"]["metabolic"]["value"] = 0.99
        assert pr.config_hash(cfg) != before


def _walk_leaves(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _walk_leaves(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_leaves(v)
    else:
        yield o


# ═════════════════════════════════════════════════════════════════════════════
# 5. /api/wrong — null fits are published findings (RED pre-fix)
# ═════════════════════════════════════════════════════════════════════════════
class FakeTable:
    def __init__(self, by_pk=None):
        self.by_pk = by_pk or {}

    @staticmethod
    def _find_pk(cond):
        vals = getattr(cond, "_values", None)
        if vals is None:
            return None
        for v in vals:
            got = FakeTable._find_pk(v) if hasattr(v, "_values") else (v if isinstance(v, str) else None)
            if isinstance(got, str) and got.startswith("USER#"):
                return got
        return None

    def query(self, **kwargs):
        cond = kwargs.get("KeyConditionExpression")
        pk = self._find_pk(cond) if cond is not None else None
        items = list(self.by_pk.get(pk, []))
        if kwargs.get("ScanIndexForward") is False:
            items = sorted(items, key=lambda i: str(i.get("sk", "")), reverse=True)
        limit = kwargs.get("Limit")
        return {"Items": items[:limit] if limit else items}

    def get_item(self, **kwargs):
        return {}


_FIT_ITEM = {
    "pk": "USER#matthew#SOURCE#effect_fits",
    "sk": "FIT#2026-07-19",
    "as_of_date": "2026-07-19",
    "window_days": Decimal("365"),
    "n_days": Decimal("120"),
    "summary": {"tested": Decimal("3"), "fitted": Decimal("1"), "authored_prior": Decimal("2")},
    "effects": {
        "Training Boost": {
            "status": "fitted",
            "reason": "confirmed",
            "n_eff": Decimal("41.2"),
            "ci_95": [Decimal("0.08"), Decimal("0.31")],
            "r": Decimal("0.2"),
            "targets": [],
        },
        "Sleep Drag": {
            "status": "authored-prior",
            "reason": "null_not_excluded",
            "n_eff": Decimal("38.5"),
            "ci_95": [Decimal("-0.11"), Decimal("0.2")],
            "r": Decimal("0.05"),
            "targets": [],
        },
        "Vice Shield": {
            "status": "authored-prior",
            "reason": "insufficient_n",
            "n_eff": Decimal("0"),
            "ci_95": None,
            "r": None,
            "targets": [],
        },
    },
}


class TestWrongPagePublishesNullFits:
    def test_handle_wrong_carries_effect_fits_section(self, monkeypatch):
        """RED pre-fix: /api/wrong had no effect_fits stream at all."""
        monkeypatch.setattr(intel, "table", FakeTable({"USER#matthew#SOURCE#effect_fits": [_FIT_ITEM]}), raising=True)
        body = json.loads(intel.handle_wrong()["body"])
        ef = body.get("effect_fits")
        assert ef is not None, "/api/wrong serves no effect_fits stream (#1411)"
        assert ef["available"] is True
        assert ef["as_of"] == "2026-07-19"
        # A tested-and-unconfirmed prior is the published finding; a thin-data
        # one is only "not yet tested" — the two must not be conflated.
        names = [u["name"] for u in ef["unconfirmed"]]
        assert "Sleep Drag" in names and "Vice Shield" not in names and "Training Boost" not in names
        drag = ef["unconfirmed"][0]
        assert drag["n_eff"] == 38.5 and drag["ci_95"] == [-0.11, 0.2]  # honest n + uncertainty ride along (ADR-104/105)
        assert ef["not_yet_tested"] == 1

    def test_handle_wrong_honest_before_first_fit(self, monkeypatch):
        monkeypatch.setattr(intel, "table", FakeTable({}), raising=True)
        body = json.loads(intel.handle_wrong()["body"])
        ef = body.get("effect_fits")
        assert ef is not None and ef["available"] is False


# ═════════════════════════════════════════════════════════════════════════════
# 6. The badge renders where effects are surfaced (RED pre-fix)
# ═════════════════════════════════════════════════════════════════════════════
class TestBadgeSurfaces:
    def test_character_endpoint_passes_fit_fields_through(self):
        """/api/character's active_effects projection must not strip the badge."""
        import inspect

        from web import site_api_vitals as vitals

        src = inspect.getsource(vitals.handle_character)
        for field in ("fit_status", "fit_badge"):
            assert field in src, f"handle_character strips {field} from active_effects (#1411)"

    def test_character_config_endpoint_serves_fit_fields(self):
        import inspect

        from web import site_api_vitals as vitals

        src = inspect.getsource(vitals.handle_character_config)
        for field in ("fit_status", "fit_badge"):
            assert field in src, f"handle_character_config serves no {field} (#1411)"

    def test_method_game_builder_renders_status_column(self):
        with open(os.path.join(_REPO, "scripts", "v4_build_game_explained.py")) as f:
            src = f.read()
        assert "fit_status" in src, "the /method/game builder renders no fit-status column (#1411)"

    def test_character_sheet_js_renders_badge(self):
        with open(os.path.join(_REPO, "site", "assets", "js", "evidence_character.js")) as f:
            src = f.read()
        assert "fit_badge" in src or "fit_status" in src, "the character sheet renders no fit badge (#1411)"

    def test_wrong_page_js_renders_null_fits(self):
        with open(os.path.join(_REPO, "site", "assets", "js", "evidence_intelligence.js")) as f:
            src = f.read()
        assert "effect_fits" in src, "the wrong page renders no effect-fit findings (#1411)"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
