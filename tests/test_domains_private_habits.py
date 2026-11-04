"""/api/domains names no private habit (owner ruling 2026-11-04).

"Remove Morning Journal and Evening Journal from the public configuration ... Keep Whoop Journal and Food
Journal public under their existing field-level restrictions." The config no longer names them, and the route
asks the publication policy (``common.activity_publication``, identity — never words) about whatever the config
says, so a habit re-added to the config by hand is still not served.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from common import activity_publication as AP  # noqa: E402
from web import site_api_protocols as P  # noqa: E402

CONFIG = os.path.join(ROOT, "site", "config", "domains.json")


def _config() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def _served(config: dict, monkeypatch) -> dict:
    monkeypatch.setattr(P, "_domains_cache", config)
    return json.loads(P.domains()["body"])


def test_the_config_names_no_private_habit_and_no_private_source():
    for d in _config()["domains"]:
        for name in d.get("habit_names", []):
            assert AP.NP.classify(AP.habit_family(name)) != AP.PRIVATE, f"{d['id']}: {name} is a private habit"
        assert not [s for s in d.get("data_sources", []) if "notion" in s.lower()], f"{d['id']}: names the private journal source"


def test_the_public_journal_habits_stay_public():
    names = {n for d in _config()["domains"] for n in d.get("habit_names", [])}
    assert "Food Journal" in names
    assert AP.habit_is_public("Food Journal") and AP.habit_is_public("Whoop Journal")


def test_the_route_drops_a_private_habit_the_config_names(monkeypatch):
    """Mutation control: put the two journal habits back into the config and the route still does not serve them."""
    cfg = _config()
    mind = next(d for d in cfg["domains"] if d["id"] == "mind")
    mind["habit_names"] = ["Morning Journal", "Evening Journal"] + mind["habit_names"]
    body = _served(cfg, monkeypatch)
    served = {n for d in body["domains"] for n in d.get("habit_names", [])}
    assert not {"Morning Journal", "Evening Journal"} & served
    assert "Deep Work Block" in served and "Food Journal" in served
    assert body["count"] == len(cfg["domains"])
