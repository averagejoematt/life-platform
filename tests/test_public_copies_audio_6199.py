"""tests/test_public_copies_audio_6199.py — #6199 A: audio is a public copy (check_public_copies rule F).

Fixture listing only: one indexed episode, one unindexed alternate format of it, one restart tombstone, one archive file
under a sub-prefix → exactly the unindexed objects over the tombstone size are red. Sizes and keys only.
"""

from __future__ import annotations

import importlib.util
import json
import os
import urllib.error
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("check_public_copies_6199", os.path.join(ROOT, "scripts", "check_public_copies.py"))
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

T = datetime(2026, 12, 1, tzinfo=timezone.utc)
BIG = 3_000_000


def _o(key, size):
    return {"Key": key, "Size": size, "LastModified": T}


def _listing():
    return [
        _o("generated/panelcast/episodes.json", 900),
        _o("generated/panelcast/wk7.wav", BIG),  # indexed
        _o("generated/panelcast/wk7.mp3", BIG),  # an alternate format nobody indexes
        _o("generated/panelcast/wk6.mp3", 219),  # a restart tombstone
        _o("generated/panelcast/archive/old/wk9.mp3", BIG),  # under the panelcast index, not in it
        _o("generated/panelcast/wk7.transcript.txt", 8000),  # not audio
        _o("generated/podcast/episodes.json", 19),
        _o("generated/podcast/ep-2026-12-01.mp3", BIG),
        _o("site/index.html", 5000),  # not an audio prefix
    ]


INDEXES = {
    "generated/panelcast/episodes.json": {"episodes": [{"week": 7, "url": "https://example.invalid/panelcast/wk7.wav"}]},
    "generated/podcast/episodes.json": {"episodes": []},
}


def test_exactly_the_unindexed_audio_over_the_tombstone_size_is_red():
    found = C.audio_issues(_listing(), INDEXES.__getitem__)
    keys = sorted(d.split(" — ")[0] for _c, _r, d in found)
    assert keys == ["generated/panelcast/archive/old/wk9.mp3", "generated/panelcast/wk7.mp3", "generated/podcast/ep-2026-12-01.mp3"]
    assert all(c == "audio" and r == "F" for c, r, _d in found)


def test_an_indexed_alternate_and_a_listed_podcast_episode_are_green():
    idx = {
        "generated/panelcast/episodes.json": {
            "episodes": [{"url": "/panelcast/wk7.wav", "mp3_url": "/panelcast/wk7.mp3"}, {"url": "/panelcast/archive/old/wk9.mp3"}]
        },
        "generated/podcast/episodes.json": {"episodes": [{"url": "https://example.invalid/podcast/ep-2026-12-01.mp3"}]},
    }
    found = C.audio_issues(_listing(), idx.__getitem__)
    assert [d for _c, _r, d in found if "archive/old" in d] == [], "the deepest index above a key governs it"
    assert found == []


def test_an_unreadable_index_leaves_every_audio_object_under_it_unlisted():
    def read(k):
        if k.startswith("generated/podcast/"):
            raise urllib.error.URLError("down")
        return INDEXES[k]

    found = C.audio_issues(_listing(), read)
    assert any("generated/podcast/episodes.json could not be read" in d for _c, _r, d in found)
    assert any(d.startswith("generated/podcast/ep-2026-12-01.mp3") for _c, _r, d in found)


def test_evaluate_runs_rule_f_and_the_remediation_names_each_key():
    violations = C.audio_issues(_listing(), INDEXES.__getitem__)
    text = C.remediation_commands(violations, {"orphans": {}})
    for key in ("generated/panelcast/wk7.mp3", "generated/podcast/ep-2026-12-01.mp3"):
        assert key in text
    assert "tombstone" in text and "delete" not in text.replace("delete-protected", "")
    assert "audio" in C.COPIES and "rule F" in C.PUBLIC_RESOURCES["generated/panelcast/*"]
    import inspect

    assert "audio_issues(listing" in inspect.getsource(C.evaluate)
    json.dumps(violations)
