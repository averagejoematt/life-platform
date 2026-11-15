"""tests/test_subscriber_copy_derives_3565.py — #3565 (epic #3498): a subscriber
email may not hand-type what the registry and the manifest already publish.

Two live defects, one shape:

  G-6    the confirmation email said "real biometric data from 19 sources" while
         `lambdas/ingestion/source_registry.py` — the count scripts/doc_facts_og.py
         calls "the ONE source of truth for the reader-facing card count", and the
         count og-home derives — held a different number. #1260's gate would have
         caught it on day one, but its scan globbed `lambdas/web/og_*.py`, so the
         first email a subscriber ever receives sat outside the net.
  CPO-5  `_get_published_posts` re-derived a card label as f"Week {p['week']}"
         from the manifest's integer week, throwing away the genesis-anchored
         `label` chronicle_render.py carries precisely so a pre-genesis
         installment reads "Prologue · Part III". Every prologue is stamped
         `week: 0` deliberately, so the welcome email's cards read
         "Week 0 · The Plan, On the Record" — and the integer sort could rank a
         prologue above the newest post.

Guards: the rendered figure equals the derivation (not a literal), the derivation
is negative-controlled by MOVING the source it derives from, and the doc-facts
gate now reaches the templates.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")


def _load_check_doc_facts():
    path = os.path.join(_REPO, "scripts", "check_doc_facts.py")
    spec = importlib.util.spec_from_file_location("check_doc_facts_3565", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── G-6: the source count is derived ─────────────────────────────────────────


def test_confirmation_email_states_the_registry_count():
    from ingestion.source_registry import SOURCE_REGISTRY
    from web.email_subscriber_lambda import _confirmation_email_content

    _, html = _confirmation_email_content("https://averagejoematt.com/api/subscribe?action=confirm&token=x")
    flat = " ".join(html.split())
    # The canonical reader-facing phrase, deliberately — it is the one scripts/doc_facts_og.py
    # polices, so the wording itself keeps the email inside the gate.
    assert f"{len(SOURCE_REGISTRY)} data sources" in flat
    assert "19 data sources" not in flat and "19 sources" not in flat, "the hand-typed #3565 literal is back"


def test_the_count_follows_the_registry_when_the_registry_moves(monkeypatch):
    """NEGATIVE CONTROL. Add a source to the registry the template reads and the
    email must state the new number. A literal would not move; a derivation must."""
    from web import email_subscriber_lambda as esl

    grown = dict(esl.SOURCE_REGISTRY)
    grown["a_new_wearable_3565"] = {"label": "New Wearable"}
    monkeypatch.setattr(esl, "SOURCE_REGISTRY", grown)

    _, html = esl._confirmation_email_content("https://x/confirm")
    flat = " ".join(html.split())
    assert f"{len(grown)} data sources" in flat
    assert f"{len(grown) - 1} data sources" not in flat


def test_doc_facts_source_count_scan_now_reaches_the_subscriber_templates():
    """The gate's scan set — not just the fix. #1260 policed og_*.py only, which is
    why a wrong count could live in the confirmation email for months."""
    facts = _load_check_doc_facts()
    scanned = {Path(p).name for p in facts._scan_source_count_files()}
    assert "email_subscriber_lambda.py" in scanned
    assert "subscriber_onboarding_lambda.py" in scanned
    assert any(n.startswith("og_") for n in scanned), "the og cards fell out of the scan set"


def test_doc_facts_source_count_scan_bites_on_a_subscriber_template(tmp_path):
    """Non-vacuous (#1189): plant the exact pre-fix sentence in a scratch template and
    the rule must flag it against the live registry truth."""
    facts = _load_check_doc_facts()
    truth = facts._registry_source_count()
    bad = tmp_path / "email_subscriber_lambda.py"
    bad.write_text('    html = """live biometrics from 19 data sources, habit performance"""\n')
    hits = facts._og_source_hits([bad], truth)
    assert hits, "the widened scan did not flag the planted stale count"
    assert "claims 19 data sources" in hits[0] and f"truth is {truth}" in hits[0]


def test_doc_facts_source_count_scan_is_clean_on_the_current_tree():
    facts = _load_check_doc_facts()
    truth = facts._registry_source_count()
    files = facts._scan_source_count_files()
    assert len(files) == len(facts._scan_og_files()) + 5, f"the scan set changed shape: {[f.name for f in files]}"
    assert len(files) > 5, "the og cards fell out — the scan is not reading the tree"
    hits = facts._og_source_hits(files, truth)
    assert hits == [], "a reader-facing surface still hardcodes a stale data-source count:\n" + "\n".join(hits)


# ── CPO-5: the card label is the manifest's ──────────────────────────────────


class _StubS3:
    """Minimal S3 stub — returns one manifest body. No AWS, no network."""

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def get_object(self, Bucket=None, Key=None):  # noqa: N803 — boto3 kwarg casing
        assert Key == "generated/journal/posts.json"
        return {"Body": _Body(self._payload)}


class _Body:
    def __init__(self, raw):
        self._raw = raw

    def read(self):
        return self._raw


# The shape the live manifest actually serves (issue #3565's reproduction): one
# genesis-week post and three prologue parts, every prologue stamped week 0, each
# carrying the genesis-anchored `label` chronicle_render.py computes.
_MANIFEST = {
    "posts": [
        {"week": 1, "label": "Week 1", "sequence": 4, "title": "328.1", "date": "2026-09-09", "url": "/journal/posts/week-04/"},
        {
            "week": 0,
            "label": "Prologue · Part III",
            "sequence": 3,
            "title": "The Plan, On the Record",
            "date": "2026-09-04",
            "url": "/journal/posts/week-03/",
        },
        {
            "week": 0,
            "label": "Prologue · Part II",
            "sequence": 2,
            "title": "The Night Before Everything",
            "date": "2026-09-03",
            "url": "/journal/posts/week-02/",
        },
        {
            "week": 0,
            "label": "Prologue · Part I",
            "sequence": 1,
            "title": "Before the Numbers",
            "date": "2026-09-02",
            "url": "/journal/posts/week-01/",
        },
    ]
}


@pytest.fixture()
def onboarding(monkeypatch):
    from web import subscriber_onboarding_lambda as mod

    monkeypatch.setattr(mod, "s3", _StubS3(_MANIFEST))
    return mod


def test_cards_use_the_manifest_label_never_a_re_derived_week(onboarding):
    cards = onboarding._get_published_posts(max_posts=4)
    assert [c["label"] for c in cards] == ["Week 1", "Prologue · Part III", "Prologue · Part II", "Prologue · Part I"]
    assert all("Week 0" not in c["label"] for c in cards), "a prologue is being labelled Week 0 again"


def test_the_welcome_email_never_renders_week_0(onboarding):
    _, html = onboarding._build_onboarding_email("reader@example.com")
    assert "Week 0" not in html
    assert "Prologue · Part III" in html
    assert "The Plan, On the Record" in html


def test_ordering_is_by_date_not_by_integer_week(monkeypatch):
    """The ordering half. A prologue part is `week: 0` by construction, so an integer
    sort ranks an OLD week-1 post above the NEWEST installment whenever the newest one
    is pre-genesis — which is exactly the state of the manifest on a restart eve."""
    from web import subscriber_onboarding_lambda as mod

    manifest = {
        "posts": [
            {"week": 1, "label": "Week 1", "sequence": 1, "title": "old but numbered", "date": "2026-08-01", "url": "/a/"},
            {"week": 0, "label": "Prologue · Part III", "sequence": 3, "title": "newest", "date": "2026-09-03", "url": "/b/"},
        ]
    }
    monkeypatch.setattr(mod, "s3", _StubS3(manifest))
    cards = mod._get_published_posts(max_posts=2)
    assert [c["title"] for c in cards] == ["newest", "old but numbered"]
    # the pre-fix key, for contrast: sorting on the integer week inverts this.
    by_week = sorted(manifest["posts"], key=lambda p: p.get("week", 0), reverse=True)
    assert [p["title"] for p in by_week] == ["old but numbered", "newest"]


def test_same_date_parts_break_the_tie_on_the_manifest_sequence(monkeypatch):
    """chronicle_render.py's own ordering key is (date, sequence) — #1988's same-date
    multi-part run. The email must not reintroduce a second, different ordering."""
    from web import subscriber_onboarding_lambda as mod

    manifest = {
        "posts": [
            {"week": 0, "label": "Prologue · Part I", "sequence": 1, "title": "I", "date": "2026-09-04", "url": "/1/"},
            {"week": 0, "label": "Prologue · Part III", "sequence": 3, "title": "III", "date": "2026-09-04", "url": "/3/"},
            {"week": 0, "label": "Prologue · Part II", "sequence": 2, "title": "II", "date": "2026-09-04", "url": "/2/"},
        ]
    }
    monkeypatch.setattr(mod, "s3", _StubS3(manifest))
    assert [c["title"] for c in mod._get_published_posts(max_posts=3)] == ["III", "II", "I"]


def test_a_manifest_without_labels_degrades_to_a_neutral_marker(monkeypatch):
    """Absence semantics (ADR-104): a post with no label gets a neutral card marker,
    never an invented week number."""
    from web import subscriber_onboarding_lambda as mod

    manifest = {"posts": [{"week": 0, "sequence": 1, "title": "unlabelled", "date": "2026-09-04", "url": "/x/"}]}
    monkeypatch.setattr(mod, "s3", _StubS3(manifest))
    cards = mod._get_published_posts(max_posts=1)
    assert cards[0]["label"] == "The Chronicle"
    assert "Week" not in cards[0]["label"]


def test_unreadable_manifest_still_falls_back_to_the_static_pages(monkeypatch):
    from web import subscriber_onboarding_lambda as mod

    class _Boom:
        def get_object(self, **kwargs):
            raise RuntimeError("no such key")

    monkeypatch.setattr(mod, "s3", _Boom())
    assert mod._get_published_posts() == mod.FALLBACK_PAGES


# ── #5939 r2:cpo-3: the welcome email is day-aware and links the v9 doors ─────
#
# A Day-69 subscriber was told "the site is brand new and the data is just starting to
# accumulate" and sent to the legacy /cockpit/ and /story/chronicle/. The day now comes from
# EXPERIMENT_START_DATE through pacific_day_n; the clock is frozen in every case below (the
# function's own `on_date=` plus a pinned module `pacific_today`), so no assertion here can
# step at a round-number instant (#4848).

_LEGACY_WELCOME_PATHS = ("/cockpit/", "/story/chronicle/", "/legacy")


def _welcome_offenders(body: str, expect_brand_new: bool) -> list[str]:
    """Every way a rendered welcome email breaks #5939's contract (empty = clean)."""
    out = [f"legacy link {p}" for p in _LEGACY_WELCOME_PATHS if p in body]
    if ("brand new" in body) != expect_brand_new:
        out.append(f"'brand new' paragraph present={'brand new' in body}, expected {expect_brand_new}")
    return out


def _on_day(day: int) -> str:
    from datetime import date, timedelta

    from common.constants import EXPERIMENT_START_DATE

    return (date.fromisoformat(EXPERIMENT_START_DATE) + timedelta(days=day - 1)).isoformat()


def test_the_welcome_email_is_day_aware_and_links_the_v9_doors(monkeypatch):
    import web.email_subscriber_lambda as esl

    # Freeze the default clock too: the default path must give the same answer as the explicit one.
    monkeypatch.setattr(esl, "pacific_today", lambda: _on_day(69))
    _, day69_default = esl._welcome_email_content("reader@example.com")
    _, day69 = esl._welcome_email_content("reader@example.com", on_date=_on_day(69))
    _, day3 = esl._welcome_email_content("reader@example.com", on_date=_on_day(3))
    _, day15 = esl._welcome_email_content("reader@example.com", on_date=_on_day(15))

    offenders = {
        "day 69 (default clock)": _welcome_offenders(day69_default, expect_brand_new=False),
        "day 69": _welcome_offenders(day69, expect_brand_new=False),
        "day 15": _welcome_offenders(day15, expect_brand_new=False),
        "day 3": _welcome_offenders(day3, expect_brand_new=True),
    }
    assert not any(offenders.values()), offenders
    assert day69_default == day69
    assert "day 69 of the experiment" in day69
    assert "day 15 of the experiment" in day15
    for body in (day69, day3):
        for path in ("/", "/story/", "/data/", "/system/"):
            assert f"{esl.SITE_URL}{path}\n" in body, f"v9 door {path} missing"


def test_the_welcome_contract_check_fails_on_the_old_copy(monkeypatch):
    """Must-fail control: put the pre-#5939 behaviour back (the brand-new paragraph on every
    day, the legacy cockpit/chronicle links) and the same check must name both defects."""
    import web.email_subscriber_lambda as esl

    monkeypatch.setattr(esl, "pacific_today", lambda: _on_day(69))
    monkeypatch.setattr(esl, "WELCOME_BRAND_NEW_MAX_DAY", 10_000)
    monkeypatch.setattr(
        esl,
        "WELCOME_DOORS",
        (("The live cockpit", "/cockpit/"), ("The first dispatch", "/story/chronicle/")),
    )
    _, old = esl._welcome_email_content("reader@example.com", on_date=_on_day(69))
    offenders = _welcome_offenders(old, expect_brand_new=False)
    assert "legacy link /cockpit/" in offenders
    assert "legacy link /story/chronicle/" in offenders
    assert any("brand new" in o for o in offenders), offenders
