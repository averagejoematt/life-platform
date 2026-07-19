"""lambdas/fulfillment_index.py — the asymmetric-channel fulfillment index (#1404, epic #718).

#718's success criterion is "a fulfillment signal that survives one bad week."
The failure mode it names: every body pillar is passively instrumented, every
fulfillment pillar was manual — so fulfillment measurement died exactly during
the episodes worth measuring (a skipped-journal week read as no signal at all).

The fix is ASYMMETRY. Two layers, with different jobs:

  * BASELINE (the verdict) — passive/one-tap channels only:
      - connection_tap      evening_ritual one-tap connection 0–4 (ADR-124)
      - interactions        logged social interactions (SOURCE#interactions)
      - journal_presence    a journal entry EXISTS today (showing up is the
                            engagement signal — content is not read here)
      - values_todoist      completed Todoist tasks carrying a values label
                            (a label named "values" or prefixed "value:")
    The daily score is a weighted mean over the ADOPTED channels, renormalized
    to the adopted weight mass. This layer alone decides the number.

  * RESOLUTION (the texture) — the journal-enrichment PERMA row
    (SOURCE#flourishing, #1403). THE COMPOSITION RULE, load-bearing and
    test-pinned: enrichment composes MONOTONICALLY — it can only ADD a
    `resolution` block (components, values named, provenance); it never
    changes the score, the state, or the coverage. A skipped-journal week
    therefore degrades resolution ("coarse" instead of "enriched"), never
    the verdict.

ADR-104 semantics, encoded per channel via ADOPTION:
  * A channel is ADOPTED from the date of its first row EVER (cross-cycle,
    tombstoned archives included — adoption is a capability fact about the
    instrumentation, not a per-cycle experiment datum).
  * Before adoption: MEASURED absence — the channel simply isn't in coverage
    (frozen out, contributes nothing, shrinks the denominator).
  * After adoption: BEHAVIORAL absence — a day with no tap / no interaction /
    no journal / no values-completion scores 0 on that channel. Not tapping an
    instrumented one-tap rail is itself the low-connection signal.
  * When too little of the channel mass is adopted (< COVERAGE_FLOOR), the day
    renders the dignified insufficient state — never a fabricated number.

Pure module: no I/O, no clock, no boto3. Callers fetch the rows.
"""

# (channel, weight). Weights sum to 1.0 over the full roster; the daily score
# renormalizes over whatever subset is adopted. connection_tap deliberately
# carries half the mass — it is the one deliberately-frictionless channel the
# whole ADR-124 rail was built around.
CHANNELS = (
    ("connection_tap", 0.50),
    ("interactions", 0.20),
    ("journal_presence", 0.15),
    ("values_todoist", 0.15),
)
CHANNEL_NAMES = tuple(name for name, _ in CHANNELS)

# Below this much adopted weight-mass the index refuses to produce a number:
# with only journal_presence (0.15) or only the two low-weight channels, a
# "fulfillment index" would be an extrapolation, not a measurement.
COVERAGE_FLOOR = 0.5

DISCLOSURE = (
    "Baseline from passive one-tap channels only (connection tap, logged interactions, "
    "journal presence, values-tagged task completions) — journal text adds resolution, "
    "never the verdict, so a skipped-journal week degrades detail, not the number. "
    "Channels count only from the day they were first used; before that they are "
    "excluded, not zeroed (ADR-104)."
)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── per-channel day scores (each takes ONLY that day's rows) ─────────────────


def score_connection_tap(ritual_row):
    """evening_ritual row → 0–100. A row with a tap maps 0–4 → 0–100; a day
    with no tap (row absent, or row without `connection`) is behavioral 0 —
    the one-tap rail was in that evening's nudge."""
    c = _f((ritual_row or {}).get("connection"))
    if c is None:
        return 0.0
    return max(0.0, min(4.0, c)) / 4.0 * 100.0


def score_interactions(interaction_rows):
    """Count of logged interactions that day → 0/60/85/100 (saturating —
    the third interaction of a day proves less than the first)."""
    n = len(interaction_rows or [])
    if n <= 0:
        return 0.0
    return {1: 60.0, 2: 85.0}.get(n, 100.0)


def score_journal_presence(has_entry):
    """Showing up in the journal at all is the engagement signal: 100/0.
    Deliberately binary — reading the text is the resolution layer's job."""
    return 100.0 if has_entry else 0.0


def values_tagged_completions(todoist_row):
    """Count completed tasks on the daily todoist row whose labels mark a
    values-aligned task: a label exactly "values" or prefixed "value:"
    (case-insensitive). The convention is defined HERE — one place."""
    count = 0
    for task in (todoist_row or {}).get("completed_tasks") or []:
        labels = task.get("labels") or [] if isinstance(task, dict) else []
        for lb in labels:
            if isinstance(lb, str) and (lb.strip().lower() == "values" or lb.strip().lower().startswith("value:")):
                count += 1
                break
    return count


def score_values_todoist(todoist_row):
    """Values-tagged completions that day → 0/70/100 (saturating)."""
    n = values_tagged_completions(todoist_row)
    if n <= 0:
        return 0.0
    return 70.0 if n == 1 else 100.0


# ── composition ──────────────────────────────────────────────────────────────


def compose_day(date_str, adopted, channel_scores):
    """One day's index from the baseline layer alone (pure).

    adopted: {channel: bool} — is the channel adopted as of date_str.
    channel_scores: {channel: float 0–100} — that day's raw channel scores
      (values for un-adopted channels are ignored).

    Returns the day dict: state "ok" (score + coverage + per-channel detail)
    or state "insufficient_signal" (coverage only — no score key at all, so a
    consumer cannot accidentally render a number that doesn't exist).
    """
    adopted = {name: bool(adopted.get(name)) for name in CHANNEL_NAMES}
    coverage = sum(w for name, w in CHANNELS if adopted[name])
    day = {"date": date_str, "coverage": round(coverage, 2)}
    if coverage < COVERAGE_FLOOR:
        day["state"] = "insufficient_signal"
        day["reason"] = (
            f"only {coverage:.2f} of the channel weight-mass is instrumented (floor {COVERAGE_FLOOR}) — "
            "not enough passive signal to state a number honestly"
        )
        return day
    score = 0.0
    channels = {}
    for name, w in CHANNELS:
        if not adopted[name]:
            channels[name] = {"adopted": False}
            continue
        s = max(0.0, min(100.0, _f(channel_scores.get(name)) or 0.0))
        score += (w / coverage) * s
        channels[name] = {"adopted": True, "score": round(s, 1), "weight": w}
    day["state"] = "ok"
    day["score"] = round(score, 1)
    day["channels"] = channels
    return day


def attach_resolution(day, flourishing_row, model=None):
    """THE MONOTONE COMPOSITION RULE (#1404 AC2), enforced here and pinned by
    tests: enrichment may only ADD the `resolution` block to an already-composed
    day — `score`, `state`, `coverage`, and `channels` are never touched, so
    enrichment absence can never subtract from the verdict.

    Returns the SAME day dict, with:
      resolution: "enriched" + components (from the #1403 flourishing row,
                  with its provenance line), or "coarse" when no row exists
                  (a skipped-journal day — detail degraded, verdict intact).
    """
    if not flourishing_row:
        day["resolution"] = {"level": "coarse"}
        return day
    components = {}
    for k in (
        "values_lived_count",
        "gratitude_count",
        "flow",
        "growth_signals_count",
        "ownership_score",
        "social_quality_score",
    ):
        if k in flourishing_row:
            v = _f(flourishing_row.get(k))
            if v is not None:
                components[k] = v
    res = {"level": "enriched", "components": components}
    values = flourishing_row.get("values_lived")
    if isinstance(values, list) and values:
        res["values_lived"] = [str(v) for v in values]
    if model or flourishing_row.get("enrichment_model"):
        # provenance mirrors flourishing.provenance_line — these numbers are a
        # language model's reading of prose, never sensor data (ADR-104/#1403).
        m = model or flourishing_row.get("enrichment_model")
        res["provenance"] = f"LLM-coded from journal text (model {m})"
    day["resolution"] = res
    return day


def window_mean(days):
    """Mean score over the days that HAVE a score (state ok). Returns
    (mean, n_scored) — (None, 0) when nothing scored, never a fabricated 0."""
    scored = [d["score"] for d in days if d.get("state") == "ok" and d.get("score") is not None]
    if not scored:
        return None, 0
    return round(sum(scored) / len(scored), 1), len(scored)
