#!/usr/bin/env python3
"""
tests/test_site_review_bindings.py — guards for the site-review binding map and the
deterministic cross-page consistency check.

No network, no AWS, no Playwright. The consistency test writes fake captured API JSON
to a tmp dir and exercises the pure comparison logic, so it can run in CI.

Run: python3 -m pytest tests/test_site_review_bindings.py -v
"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TESTS = os.path.join(ROOT, "tests")
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

import site_review_bindings as B  # noqa: E402
import site_review as sr  # noqa: E402


class TestBindingMap:
    def test_selfcheck_passes(self):
        """Every visual_qa.PAGES path is bound and every evidence primary matches REGISTRY."""
        ok, problems = B.selfcheck()
        assert ok, "binding drift:\n" + "\n".join(problems)

    def test_every_page_has_unique_narrative_order(self):
        orders = [b["narrative_order"] for b in B.PAGE_BINDINGS]
        assert len(orders) == len(set(orders))

    def test_all_endpoints_deduped(self):
        eps = B.all_endpoints()
        assert len(eps) == len(set(eps))
        assert "/api/journey" in eps and "/api/snapshot" in eps

    def test_weight_and_level_are_cross_checked(self):
        """The core cross-page metrics must be observed from ≥2 endpoints."""
        obs = B.metric_observations()
        for metric in ("current_weight_lbs", "level"):
            urls = {url for _p, url, _path in obs[metric]}
            assert len(urls) >= 2, f"{metric} only seen from {urls}"

    def test_coaching_door_registered(self):
        """The /coaching/ door (PR C) is in the registry — both PAGES and bindings."""
        import visual_qa  # noqa: E402

        assert "/coaching/" in {b["path"] for b in B.PAGE_BINDINGS}
        assert "coaching" in {b["door"] for b in B.PAGE_BINDINGS}
        assert any(p["path"].startswith("/coaching/") for p in visual_qa.PAGES)
        # the moved-away Story coach paths must NOT linger in the registry
        assert "/story/coaches/" not in {b["path"] for b in B.PAGE_BINDINGS}


class TestCoverageGuard:
    """The sitemap-vs-doors guard: a new top-level door with no bindings is a blind spot."""

    def test_no_gaps_currently(self):
        assert B.coverage_gaps() == [], "a door has sitemap pages but no QA bindings"

    def test_guard_detects_an_unregistered_door(self, monkeypatch):
        """If the sitemap gains a door with no binding, coverage_gaps must flag it."""
        monkeypatch.setitem(B._SEGMENT_TO_DOOR, "newthing", "newthing")
        monkeypatch.setattr(B, "_sitemap_routes", lambda: ["/", "/newthing/foo/"])
        assert "newthing" in B.coverage_gaps()
        # and selfcheck surfaces it as a failure
        ok, problems = B.selfcheck()
        assert not ok and any("newthing" in p for p in problems)

    def test_snapshot_uses_double_nested_paths(self):
        """Guards the verified /api/snapshot shape (journey.journey.* / character.character.*)."""
        obs = B.metric_observations()
        snap_weight = [p for _pg, url, p in obs["current_weight_lbs"] if url == "/api/snapshot"]
        snap_level = [p for _pg, url, p in obs["level"] if url == "/api/snapshot"]
        assert snap_weight == ["journey.journey.current_weight_lbs"]
        assert snap_level == ["character.character.level"]


class TestConsistencyLogic:
    """cross_page_consistency over fake captured JSON — no network."""

    def _write(self, tmp_path, journey_w, snapshot_w):
        api = tmp_path / "api"
        api.mkdir()
        (api / "api-journey.json").write_text(
            json.dumps({"journey": {"current_weight_lbs": journey_w, "lost_lbs": 9.4, "progress_pct": 7.3}})
        )
        (api / "api-snapshot.json").write_text(
            json.dumps(
                {
                    "journey": {"journey": {"current_weight_lbs": snapshot_w, "lost_lbs": 9.4, "progress_pct": 7.3}},
                    "character": {"character": {"level": 4}},
                }
            )
        )
        (api / "api-character.json").write_text(json.dumps({"character": {"level": 4}}))
        return {
            "/api/journey": {"file": "api/api-journey.json", "ok": True, "status": 200},
            "/api/snapshot": {"file": "api/api-snapshot.json", "ok": True, "status": 200},
            "/api/character": {"file": "api/api-character.json", "ok": True, "status": 200},
        }

    def test_agreement_when_weights_match(self, tmp_path):
        idx = self._write(tmp_path, 305.0, 305.0)
        res = sr.cross_page_consistency(str(tmp_path), idx)
        assert res["disagreements"] == 0
        weight = next(c for c in res["checks"] if c["metric"] == "current_weight_lbs")
        assert weight["agree"] and weight["severity"] == "ok"

    def test_disagreement_flagged_when_weights_diverge(self, tmp_path):
        # 305.0 vs 306.0 → Δ1.0 > 0.1 lb tolerance → HIGH
        idx = self._write(tmp_path, 305.0, 306.0)
        res = sr.cross_page_consistency(str(tmp_path), idx)
        weight = next(c for c in res["checks"] if c["metric"] == "current_weight_lbs")
        assert not weight["agree"]
        assert weight["severity"] == "high"
        assert res["disagreements"] >= 1

    def test_within_tolerance_still_agrees(self, tmp_path):
        # 305.00 vs 305.05 → Δ0.05 ≤ 0.1 lb tolerance → still agrees (rounding)
        idx = self._write(tmp_path, 305.00, 305.05)
        res = sr.cross_page_consistency(str(tmp_path), idx)
        weight = next(c for c in res["checks"] if c["metric"] == "current_weight_lbs")
        assert weight["agree"]

    def test_missing_or_failed_endpoint_is_skipped_not_crashed(self, tmp_path):
        idx = self._write(tmp_path, 305.0, 305.0)
        idx["/api/snapshot"]["ok"] = False  # simulate a fetch failure
        res = sr.cross_page_consistency(str(tmp_path), idx)
        # weight now seen from only /api/journey → not cross-checked, no crash
        weight = [c for c in res["checks"] if c["metric"] == "current_weight_lbs"]
        assert weight == [] or len(weight[0]["sources"]) < 2
