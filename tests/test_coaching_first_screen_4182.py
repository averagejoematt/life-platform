"""tests/test_coaching_first_screen_4182.py — #4182/#4188: the coaching door's first screen.

The door opened on a 60-word tutorial ("Start with the read — what they're saying about
you right now — … the Third Wall …"), then on the integrator's WEEKLY call served
unlabelled on a Friday. The panel's rulings (epic #4182, 2(iv) + vii-6/vii-8) replace it
with: the 11-word definition, ONE coach read dated in words, the week's call labelled
weekly beneath it, and "the Third Wall" cut from reader surfaces.

Source/shell-level pins (the browser half is tests/js/coach_today_4182.test.mjs):

  1. the first-screen mount ships on the hub and /coaching/read/ ONLY, directly under the
     hero and before the section tabs; the portraits disclaimer sits below it;
  2. the hero's promise states the SERVED roster's size in words, derived from the persona
     registry the way /api/coaches composes its roster — never a typed numeral (the
     panel's own draft said "seven" when the roster was eight);
  3. "Third Wall" is absent from every committed /coaching/** page's <main>;
  4. in coaching.js, today's read renders before the week's call, and the week's call's
     label contains "week".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO / "lambdas"))

import v4_build_coaching  # noqa: E402
from coach import persona_registry  # noqa: E402

_SITE = _REPO / "site" / "coaching"
_JS = _REPO / "site" / "assets" / "js"


def _main(html: str) -> str:
    m = re.search(r"<main\b.*?</main>", html, re.S)
    assert m, "page has no <main>"
    return m.group(0)


def test_first_screen_mount_ships_on_the_hub_and_the_read_shell_only():
    for rel in ("index.html", "read/index.html"):
        main = _main((_SITE / rel).read_text(encoding="utf-8"))
        assert "data-coach-today" in main, f"/coaching/{rel}: the first-screen mount is missing"
        hero_end = main.index("</div>", main.index('class="page-hero"'))
        mount = main.index("data-coach-today")
        assert hero_end < mount < main.index("data-dx-tabs"), f"/coaching/{rel}: the mount must sit under the hero, above the tabs"
        assert mount < main.index("dx-foot"), f"/coaching/{rel}: the portraits disclaimer must sit below the first screen"
    for rel in ("by-coach/index.html", "scorecard/index.html", "team/index.html", "lab-notes/index.html", "qa/index.html"):
        assert "data-coach-today" not in (_SITE / rel).read_text(encoding="utf-8"), f"/coaching/{rel} opens on its own section"


def test_the_promise_is_the_eleven_word_definition_with_a_derived_roster_count():
    served = v4_build_coaching.roster_size()
    # The /api/coaches composition (site_api_coach_profile.handle_coaches): operational + the lead.
    ops = persona_registry.operational_personas()
    lead = persona_registry.lead_persona()
    assert served == len(ops) + (1 if lead.get("lead") and persona_registry.LEAD_PERSONA_ID not in ops else 0)
    word = v4_build_coaching.roster_word()
    expected = f"{word} AI characters, software not people, read his numbers every morning."
    assert len(expected.split()) == 11
    for rel in ("index.html", "read/index.html", "by-coach/index.html"):
        html = (_SITE / rel).read_text(encoding="utf-8")
        assert f'<p class="ph-promise">{expected}</p>' in html, f"/coaching/{rel}: the promise drifted from the registry-derived roster"
    # the retired tutorial promise is gone
    hub = (_SITE / "index.html").read_text(encoding="utf-8")
    assert "Start with <strong>the read</strong>" not in hub


def test_the_roster_word_is_derived_not_typed(monkeypatch):
    """Mutation control: one more operational persona in the registry moves the count by one."""
    before = v4_build_coaching.roster_size()
    real = persona_registry.operational_personas()
    monkeypatch.setattr(persona_registry, "operational_personas", lambda *a, **k: {**real, "extra_coach": {"operational": True}})
    assert v4_build_coaching.roster_size() == before + 1


def test_third_wall_is_absent_from_every_coaching_page_main():
    offenders = []
    for page in sorted(_SITE.rglob("index.html")):
        if "Third Wall" in _main(page.read_text(encoding="utf-8")):
            offenders.append(str(page.relative_to(_REPO)))
    assert not offenders, "'Third Wall' is cut from reader surfaces (#4182 ruling vii-8): " + ", ".join(offenders)
    # and the lab-notes shell carries its new title, keeping its URL
    lab = (_SITE / "lab-notes" / "index.html").read_text(encoding="utf-8")
    assert "<title>What the AI said, and how it felt — The Coaching — averagejoematt</title>" in lab


def test_todays_read_precedes_the_weekly_call_and_the_call_is_labelled_weekly():
    src = (_JS / "coaching.js").read_text(encoding="utf-8")
    body = src[src.index("async function renderToday(") :]
    body = body[: body.index("\n}\n")]
    read_at = body.index("today's read")
    week_at = body.index("weekCallLabel(")
    assert read_at < week_at, "the week's call must render BELOW today's read, never as the current read"
    today = (_JS / "coach_today.js").read_text(encoding="utf-8")
    label = re.search(r"return day \? `(the week's call[^`]*)`", today)
    assert label and "week" in label.group(1), "the week's call label must say it is the week's"
    # the first-screen stamps are in words — the machine "as of" never appears in them
    assert "as of" not in body.lower()
