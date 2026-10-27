"""qa_check_coach_cards.py — the coach share cards the og sweep owes (#5434, ADR-106).

``og-image-generator``'s coach-card step is fail-soft by design, so a portrait bundle it
could not parse used to cost one log line and nothing else: no coach card was rewritten and
nothing in the nightly sweep noticed. This reads the SAME bundle the sweep reads, through
the same stdlib reader (``web.portrait_bundle``), over the public site (qa-smoke's role has
no S3 grant on ``site/*`` or ``generated/*``), and:

* FAILS when the bundle does not parse — the loud form of the old log line. That is the
  state in which no card is being refreshed at all.
* WARNS (alarmed, not chronic) when a signed portrait has no card or a stale one. It is a
  warn on purpose: the first nightly after a deploy that fixes the producer runs BEFORE the
  next og sweep has written the cards, and a FAIL there is the CI-smoke rollback shape.

``assess_coach_cards`` is the pure assessor tests drive with synthetic inputs;
``check_coach_cards`` is the live-fetching wrapper qa_smoke_lambda wires in. Deterministic,
no LLM call, so never budget-paused.
"""

import email.utils
import urllib.error
import urllib.request
from datetime import datetime, timezone

from web.portrait_bundle import PortraitBundleError, load_signed_recipes_from_bundle

from operational.qa_check import CONTENT_TRUTH, Check
from operational.qa_check_reader_truth import SITE_BASE_URL

BUNDLE_PATH = "/assets/js/portrait_data.js"
# The sweep rewrites every card daily. Last-Modified is the ORIGIN object's write time, so
# edge caching does not age it; the bound is one daily cycle plus slack.
MAX_AGE_HOURS = 30


def card_path(persona_id):
    return f"/assets/images/og-coach-{persona_id.replace('_', '-')}.png"


def assess_coach_cards(bundle_text, card_last_modified, now):
    """Pure: ``(level, message)`` with level ``ok`` | ``warn`` | ``fail``.

    ``card_last_modified`` maps persona_id -> aware datetime, or ``None`` when the card is
    absent. Never raises on a bad bundle — that is the finding."""
    try:
        recipes = load_signed_recipes_from_bundle(bundle_text)
    except PortraitBundleError as e:
        return "fail", f"og coach-card sweep cannot read the portrait bundle, so no coach card is being refreshed: {e}"
    if not recipes:
        return "ok", "no signed portraits bundled — nothing to render"
    missing, stale = [], []
    for pid in sorted(recipes):
        modified = card_last_modified.get(pid)
        if modified is None:
            missing.append(pid)
            continue
        age_h = (now - modified).total_seconds() / 3600
        if age_h > MAX_AGE_HOURS:
            stale.append(f"{pid} ({age_h:.0f}h)")
    if missing or stale:
        parts = []
        if missing:
            parts.append(f"no card for: {', '.join(missing)}")
        if stale:
            parts.append(f"older than {MAX_AGE_HOURS}h: {', '.join(stale)}")
        return "warn", f"coach share cards not refreshed by the og sweep — {'; '.join(parts)}"
    return "ok", f"all {len(recipes)} coach share cards refreshed within {MAX_AGE_HOURS}h"


def _request(path, method):
    return urllib.request.Request(SITE_BASE_URL + path, method=method, headers={"User-Agent": "life-platform-qa-smoke"})


def _card_modified(persona_id):
    try:
        with urllib.request.urlopen(_request(card_path(persona_id), "HEAD"), timeout=15) as r:  # noqa: S310 — fixed trusted host
            header = r.headers.get("Last-Modified")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return email.utils.parsedate_to_datetime(header) if header else datetime.now(timezone.utc)


def check_coach_cards():
    c = Check("og:coach-cards", "Output Files", CONTENT_TRUTH)
    try:
        with urllib.request.urlopen(_request(BUNDLE_PATH, "GET"), timeout=15) as r:  # noqa: S310 — fixed trusted host
            bundle_text = r.read().decode("utf-8", "replace")
        try:
            pids = list(load_signed_recipes_from_bundle(bundle_text))
        except PortraitBundleError:
            pids = []  # the assessor reports it
        modified = {pid: _card_modified(pid) for pid in pids}
    except Exception as e:  # a transient edge blip must never red the nightly
        return [c.warn(f"coach-card fetch failed (fail-soft): {str(e)[:120]}")]
    level, msg = assess_coach_cards(bundle_text, modified, datetime.now(timezone.utc))
    return [getattr(c, "ok" if level == "ok" else level)(msg)]
