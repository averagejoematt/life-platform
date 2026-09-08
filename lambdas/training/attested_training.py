"""attested_training.py — training the owner attests to that was never captured (#3717).

WHY THIS IS NOT A BACKFILL. The obvious fix for missing history is to write the
missing sessions into the store. We are deliberately not doing that. Synthetic
rows in `SOURCE#hevy` or `SOURCE#strava` become indistinguishable from measured
data the moment they land — they would feed the band reference, the proven
curve, the public site and every future comparison with no way to tell them
apart, and `raw/*` is delete-protected so the mistake is close to irreversible.
The platform's entire credibility rests on a reader being able to believe the
numbers are measured (ADR-104).

So an attestation is a SEPARATE, DECLARED layer. It never merges into a measured
figure; it travels beside one, labelled, and any consumer that reports it must
say which it used. `bands[b]["walk_hr_wk"]` stays measured forever;
`bands[b]["attested"]` is what the owner says was also happening.

WHY THIS FILE AND NOT config/. `config/*.json` is NOT staged into the Lambda
bundle (build_bundle stages food_vocabulary / personas / coaches only), so the
runtime reads S3 and a repo-side edit is inert — the #3675 trap, and #3671's
lesson. Attestations ship in every bundle by living in code.

THE STANDING RULE. An attestation records what the owner asserts, with its
date range, its condition, and when he said it. It is evidence of a claim, not
evidence of a session. Nothing here may ever be presented as measured.
"""

from __future__ import annotations

from typing import Any

# ── the attested record(s) ─────────────────────────────────────────────────
#
# STATUS: awaiting the owner's numbers (#3717). The entry below is the SHAPE,
# recorded from his 2026-09-08 description, and is marked `active: False` until
# he confirms the range and the period — an unconfirmed attestation must not
# reach a prescription.
#
# What he described: "1 hour of lifting followed by 45 mins +/- (30-60) of low
# cardio — normally recumbent bike, but sometimes treadmill, crosstrainer."
#
# What the data shows, and why this cannot be derived instead:
#   - 95 Whoop sessions DO start within 45 min of a Hevy lift ending, but the
#     median is 22 min and only 34 of 95 fall in the 25-70 min band.
#   - Whoop `Cross Training` (id=45) is the LIFT itself: paired against the
#     same-day Hevy session the residual is 0 min in every case.
#   - `Sport_128` (n=289) is not it either: median 20 min, 41/289 in range,
#     and no heart rate recorded at all.
#   - Strava rides are genuine outdoor cycling, per the owner — not this.
# A low-intensity seated bike at ~100 bpm plausibly never crossed Whoop's
# auto-detect threshold, which is why it is absent rather than mislabelled.

ATTESTATIONS: list[dict[str, Any]] = [
    {
        "id": "post_lift_low_cardio",
        "active": False,  # ← flip to True only when the owner confirms below
        "start_date": None,  # ← owner: when did this pattern begin?
        "end_date": None,  # ← owner: when did it stop?
        "applies_when": "hevy_lift_logged",  # only on days with a logged lift
        "kind": "cycle",
        "minutes_low": 30,
        "minutes_high": 60,
        "minutes_typical": 45,
        "bpm_estimate": None,  # ← owner: unknown; leave None rather than guess
        "modalities": ["recumbent_bike", "treadmill", "cross_trainer"],
        "attested_by": "matthew",
        "attested_at": "2026-09-08",
        "basis": "owner recollection — never captured by any device",
    }
]


def active_attestations() -> list[dict[str, Any]]:
    """Only confirmed attestations. An unconfirmed one is a draft, not evidence."""
    return [a for a in ATTESTATIONS if a.get("active") and a.get("start_date") and a.get("end_date")]


def attested_minutes_for_day(day: str, had_lift: bool) -> dict[str, Any] | None:
    """Attested cardio minutes for one day, or None if nothing applies.

    Returns the typical value plus its declared range, so a consumer can show
    the uncertainty rather than a single invented number.
    """
    for a in active_attestations():
        if not (str(a["start_date"]) <= day <= str(a["end_date"])):
            continue
        if a.get("applies_when") == "hevy_lift_logged" and not had_lift:
            continue
        return {
            "id": a["id"],
            "kind": a.get("kind"),
            "minutes": a.get("minutes_typical"),
            "minutes_low": a.get("minutes_low"),
            "minutes_high": a.get("minutes_high"),
            "bpm_estimate": a.get("bpm_estimate"),
        }
    return None


def attested_overlay(day_set: set, lift_days: set) -> dict[str, Any] | None:
    """Weekly attested cardio over `day_set`, or None when nothing applies.

    Deliberately mirrors the measured covariates' units so the two can be shown
    side by side — and deliberately does NOT return a merged total, because the
    only safe way to combine them is at the point of display, with a label.
    """
    days = sorted(day_set)
    if not days:
        return None
    hits = [d for d in days if attested_minutes_for_day(d, d in lift_days)]
    if not hits:
        return None
    weeks = max(1, len(days)) / 7.0
    spec = attested_minutes_for_day(hits[0], True) or {}
    typical = float(spec.get("minutes") or 0.0)
    return {
        "attestation_id": spec.get("id"),
        "kind": spec.get("kind"),
        "n_days_covered": len(hits),
        "cardio_hr_wk_attested": round(typical * len(hits) / 60.0 / weeks, 2),
        "cardio_hr_wk_attested_low": round(float(spec.get("minutes_low") or 0) * len(hits) / 60.0 / weeks, 2),
        "cardio_hr_wk_attested_high": round(float(spec.get("minutes_high") or 0) * len(hits) / 60.0 / weeks, 2),
        # The label is not decoration. Anything rendering this MUST carry it.
        "basis": "OWNER-ATTESTED, NOT MEASURED",
    }
