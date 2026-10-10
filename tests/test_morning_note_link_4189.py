"""tests/test_morning_note_link_4189.py — the owner's link to the cockpit's four-word box (#4189 box 3).

The box (`site/assets/js/morning_note_box.js`) renders ONLY from `#note=<day>.<32-hex token>`.
The link is minted by `content.ritual_link.morning_note_link` into the evening nudge email for
the NEXT Pacific morning. Pinned here:
  * the minted token verifies at the write door for that day (mint/verify agree) and for no other;
  * the grant is in the FRAGMENT (never sent to the server) and matches the box's GRANT_RE;
  * the nudge mints TOMORROW's day, and an unavailable secret omits the section (fail-soft);
  * the cockpit shell itself carries no box markup — a reader's page has none to un-hide.
"""

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambdas"))

os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

from content.ritual_link import morning_note_link, verify_morning_note_token  # noqa: E402
from emails import evening_nudge_lambda as nudge  # noqa: E402

SECRET = "test-morning-note-secret"
BOX_JS = ROOT / "site" / "assets" / "js" / "morning_note_box.js"


def _js_grant_re() -> re.Pattern:
    """The box's own GRANT_RE, read out of the shipped module — the other half of the format."""
    m = re.search(r"const GRANT_RE = /(.+)/;", BOX_JS.read_text())
    assert m, "morning_note_box.js no longer declares GRANT_RE"
    return re.compile(m.group(1).replace("\\/", "/"))


def test_the_minted_link_opens_the_box_and_verifies_at_the_door_for_that_day_only():
    url = morning_note_link("https://averagejoematt.com/", SECRET, "2026-10-10")
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path, parts.query) == ("https", "averagejoematt.com", "/cockpit/", "")
    m = _js_grant_re().search("#" + parts.fragment)
    assert m, f"the box would not recognise the minted fragment: {parts.fragment!r}"
    day, token = m.group(1), m.group(2)
    assert day == "2026-10-10"
    assert verify_morning_note_token(SECRET, "2026-10-10", token)
    assert not verify_morning_note_token(SECRET, "2026-10-11", token)
    assert not verify_morning_note_token("another-secret", "2026-10-10", token)


def test_the_nudge_mints_tomorrows_link(monkeypatch):
    """Mutation (run 2026-10-10): mint `today` instead of `shift_day_key(today, 1)` -> the
    date assertion reds (the door accepts only the day the note is written)."""
    monkeypatch.setattr(nudge, "_get_ritual_secret", lambda: SECRET)
    html = nudge._build_morning_note_section("2026-10-09")
    m = re.search(r'href="([^"]+)"', html)
    assert m
    frag = urlsplit(m.group(1)).fragment
    day, token = _js_grant_re().search("#" + frag).groups()
    assert day == "2026-10-10"
    assert verify_morning_note_token(SECRET, "2026-10-10", token)


def test_no_secret_no_section(monkeypatch):
    monkeypatch.setattr(nudge, "_get_ritual_secret", lambda: None)
    assert nudge._build_morning_note_section("2026-10-09") == ""


def test_the_cockpit_shell_carries_no_box_and_the_module_is_wired():
    shell = (ROOT / "site" / "cockpit" / "index.html").read_text()
    assert "morning-note" not in shell and "/api/morning_note" not in shell, "the box must never ship in the reader's markup"
    cockpit_js = (ROOT / "site" / "assets" / "js" / "cockpit.js").read_text()
    assert 'from "/assets/js/morning_note_box.js"' in cockpit_js
    assert "mountMorningNoteBox(" in cockpit_js
