"""brief_format.py — small formatting primitives for the Daily Brief renderer.

Split out of `html_builder.py` (#1654 shape) so the xfail burn-down of
`tests/test_html_builder_behavior.py` could land without growing the module past
its `tests/test_module_size_guard.py` baseline.

Everything here is pure: no AWS, no clock, no I/O.

Three rules these helpers exist to enforce, all of them ADR-104/105:

  * `esc` — every model-generated, third-party or config string interpolated
    into the email body goes through it. It deliberately does NOT coerce: a
    non-string raises, which keeps the caller's section-level try/except doing
    its job (a malformed value must cost one named section, never the email).
  * `pct_int` — percentages ROUND, they do not truncate. `int(0.29 * 100)` is 28
    in IEEE-754 and every percentage the reader sees was biased low by it.
  * `weather_context_cells` — the WEATHER CONTEXT card renders the fields
    `lambdas/ingestion/weather_lambda.py` actually writes.
  * `coach_header_title` / `v2_coach_header_titles` — a V2 coach section
    header names its coach from `persona_registry`, never a hand-typed
    literal (#4360: `DR. VICTOR REYES` survived a 2026-08-10 rename to Dr. Max
    Reyes for six weeks because nothing pointed at the coach's own config).
    `v2_coach_header_titles()` precomputes the whole `{engine_id: title}` map
    so each `html_builder.py` call site is a short dict lookup — that is what
    keeps every header a one-line statement under
    `tests/test_module_size_guard.py`'s ceiling.
"""

from __future__ import annotations

import html as _html

from coach.persona_registry import display_name as persona_display_name
from common.digest_utils import safe_float


def esc(text):
    """HTML-escape a string for interpolation into element text.

    `quote=False` on purpose: apostrophes and double quotes are ordinary
    punctuation in coach narrative and must stay readable in the mail client.
    Non-strings raise (AttributeError) rather than being coerced — the caller's
    section guard turns that into a named placeholder, which is the honest
    outcome for a value that was never meant to be text.
    """
    return _html.escape(text, quote=False)


def pct_int(frac):
    """Return a 0..1 fraction as a rounded whole percent (never truncated)."""
    return int(round(frac * 100))


def coach_header_title(engine_id: str, emoji: str, label: str) -> str:
    """``"{emoji} {NAME} — {LABEL}"`` for a V2 coach section header.

    #4360: every one of these headers used to be a hand-typed literal, and a
    rename (Dr. Victor Reyes -> Dr. Max Reyes, 2026-08-10) left the
    physical-coach header stale for six weeks because nothing pointed at
    ``config/coaches/physical_coach.json``. The name comes from
    ``persona_registry`` (the CC-00 registry reconciling coach config keys,
    engine ids, and board personas) so a future rename updates every header
    with no code edit. ``engine_id`` is the persona/engine id (e.g.
    ``"physical_coach"``); falls back to a titleized id if the registry can't
    be read at all (S3 down AND the bundled local copy missing) rather than
    rendering an empty name.
    """
    name = persona_display_name(engine_id) or engine_id.replace("_", " ").title()
    return f"{emoji} {name.upper()} — {label}"


# (engine_id, emoji, label) for every V2 coach header, in `build_html`'s render
# order. One table here rather than eight `coach_header_title(...)` call sites
# in `html_builder.py` — each call site's line was long enough that `black`
# wrapped it across several physical lines, which is what pushed
# `html_builder.py` over its `tests/test_module_size_guard.py` ceiling (#4360).
_V2_COACH_HEADERS = (
    ("sleep_coach", "\U0001f6cf️", "SLEEP INTELLIGENCE"),
    ("nutrition_coach", "\U0001f34e", "NUTRITION INTELLIGENCE"),
    ("training_coach", "\U0001f3cb️", "TRAINING INTELLIGENCE"),
    ("mind_coach", "\U0001f9e0", "MIND INTELLIGENCE"),
    ("physical_coach", "\U0001f4aa", "PHYSICAL INTELLIGENCE"),
    ("glucose_coach", "\U0001f4c9", "GLUCOSE INTELLIGENCE"),
    ("labs_coach", "\U0001f9ec", "LABS INTELLIGENCE"),
    ("explorer_coach", "\U0001f50d", "EXPLORER INTELLIGENCE"),
)


def v2_coach_header_titles() -> dict:
    """``{engine_id: escaped "{emoji} NAME — LABEL"}`` for every V2 coach header.

    Computed once, here, so each `html_builder.py` call site is a short dict
    lookup (`titles["physical_coach"]`) instead of a `coach_header_title(...)`
    call — the lookup keeps every header a one-line statement, so a rename or
    a persona-name length change can never itself trip the module-size gate.
    """
    return {engine_id: esc(coach_header_title(engine_id, emoji, label)) for engine_id, emoji, label in _V2_COACH_HEADERS}


def _cell(value_html, label, color="#94a3b8", size="12px"):
    return (
        '<div><p style="color:' + color + ";font-size:" + size + ';margin:0;">' + value_html + "</p>"
        '<p style="color:#475569;font-size:9px;margin:0;">' + label + "</p></div>"
    )


def weather_context_cells(weather):
    """Render the WEATHER CONTEXT cells for the fields the weather lambda writes.

    `weather_lambda.transform()` stores temp_high_f / temp_low_f / temp_avg_f /
    humidity_pct / precipitation_mm / wind_speed_max_mph / pressure_hpa /
    daylight_hours / sunshine_hours / uv_index_max and strips None keys. The
    Hi/Lo cell is rendered by the caller; everything else the writer emits is
    rendered here. Absent stays absent — no cell is drawn for a field the
    record does not carry (ADR-104).
    """
    out = ""

    precip_mm = safe_float(weather, "precipitation_mm")
    if precip_mm is not None:
        out += _cell(str(round(precip_mm, 1)) + " mm", "Precip", "#60a5fa")

    humidity = safe_float(weather, "humidity_pct")
    if humidity is not None:
        out += _cell(str(round(humidity)) + "%", "Humidity")

    wind = safe_float(weather, "wind_speed_max_mph")
    if wind is not None:
        out += _cell(str(round(wind)) + " mph", "Wind max")

    uv = safe_float(weather, "uv_index_max")
    if uv is not None:
        uv_color = "#22c55e" if uv < 3 else "#f59e0b" if uv < 8 else "#ef4444"
        out += _cell(str(round(uv, 1)), "UV max", uv_color)

    daylight = safe_float(weather, "daylight_hours")
    if daylight is not None:
        out += _cell(str(round(daylight, 1)) + "h", "Daylight", "#fbbf24")

    sunshine = safe_float(weather, "sunshine_hours")
    if sunshine is not None:
        out += _cell(str(round(sunshine, 1)) + "h", "Sunshine", "#fbbf24")

    return out


_SUPPLEMENT_TIMING_LABELS = {
    "morning_fasted": "Morning (fasted)",
    "afternoon_with_food": "Afternoon (with food)",
    "evening_sleep": "Evening / Sleep",
}


def supplement_timing_order(by_timing):
    """Return the timing keys present in `by_timing`, known labels first.

    The render loop used to iterate the hardcoded label map, so any supplement
    whose `timing` was anything else — including the renderer's own "other"
    default — was collected and then never printed.
    """
    known = [k for k in _SUPPLEMENT_TIMING_LABELS if k in by_timing]
    rest = sorted(k for k in by_timing if k not in _SUPPLEMENT_TIMING_LABELS)
    return known + rest


def supplement_timing_label(timing_key):
    """Human label for a supplement timing group; unknown keys are humanised."""
    known = _SUPPLEMENT_TIMING_LABELS.get(timing_key)
    if known:
        return known
    return str(timing_key).replace("_", " ").strip() or "Other"
