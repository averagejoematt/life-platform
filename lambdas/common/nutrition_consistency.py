"""common/nutrition_consistency.py — target-neutral nutrition consistency repairs: ONE switchboard, every item OFF (#6195).

THE RULING (owner, 2026-11-22, remaster-2 section 11, "target-neutral fixes approved for implementation"). The public
site must stop implying that an estimated deficit-sustainability output is a medical clearance. Apply correct windows,
source dates, partial-export exclusions and maintenance-estimate labels; a maintenance estimate is never presented as
a calorie target; owner-facing text tells the base plan apart from the served daily minimums. Use a reversible
switchboard with OFF-state regression tests. Verified factual-labelling corrections that change no calorie target,
training prescription, clinical stop line or titration decision may be activated; a new calorie target, a medication
prescription or a change to an AI-generated medical rule may not.

THE SWITCHBOARD. ``SWITCHES`` is the one place each item is turned on or off, one reviewed line per item. Every item
defaults OFF, and OFF is today's output exactly (``tests/test_nutrition_consistency_6195.py`` pins both states per
surface). Nothing here is read from SSM: a committed switch is reviewed, diffable and the same in every Lambda of one
deploy. An item changes LABELS, WINDOWS, DATES, EXCLUSIONS or EXPLANATORY COPY only — never a number the platform
serves, grades against or prescribes (the same test resolves every target with all items ON and with all OFF and
asserts the values are identical).

TWO GROUPS, so an activation can be done in the safe order:
  * ``LABELLING`` — pure wording, labels and dated provenance. Safe to activate under the ruling.
  * ``COMPUTED`` — changes which days a mean or a page counts, or which record a sentence is read from. Activate after
    reading the before/after numbers.

ACTIVATION: set the item to ``True`` here, then the fleet deploy (``deploy/deploy_fleet.sh``) and
``deploy/deploy_site_api.sh``; the MCP description needs the MCP deploy. ROLLBACK: set it back to ``False`` and run
the same deploys. The site JavaScript needs neither: it renders the new fields only when the API sends them.
"""

from __future__ import annotations

ISSUE = "#6195"

# ── group 1: labelling and copy (safe to activate under the 2026-11-22 ruling) ─────────────────────────────────────
#: F1/F2. /api/deficit_sustainability: the five-channel read says what it is based on, what it is not based on and its
#: dates; it never says the body is "absorbing" the deficit. Additive fields: as_of, based_on, not_based_on, honesty.
PUBLIC_VERDICT_NOT_CLEARANCE = "public_verdict_not_clearance"
#: F4/F6. /api/nutrition_overview and /api/deficit_sustainability carry the maintenance estimate's source and as-of
#: date (``tdee_as_of``); the page prints both and the calorie chart captions it "estimated maintenance", never "goal".
MAINTENANCE_LABELLED = "maintenance_labelled"
#: F7. The /data/nutrition/ loss-rate line drops the unsupported "defensible early at this size" verdict.
RATE_LINE_WORDING = "rate_line_wording"
#: F15/F16. MCP get_deficit_sustainability: the all-channels-holding recommendation stops reading as a clearance,
#: and the tool description stops routing "is my deficit sustainable?" to it.
MCP_SUSTAINABILITY_WORDING = "mcp_sustainability_wording"
#: F9/F10/F11. Owner-facing AI prompts (Morning Brief profile and Board intro, Nutrition Review, Weekly Plate) state
#: the calorie target with its layers named: the served rest-day and lifting-day minimums and the base.
OWNER_TARGET_LAYERS = "owner_target_layers"
#: F12. The Morning Brief NUTRITION REPORT tile labels its calorie figure with the served band, not one layer.
BRIEF_TILE_LAYERS = "brief_tile_layers"
#: F14. The critics' rate-overshoot option says what the step moves: the base, and the served rest/lifting minimums.
OVERSHOOT_OPTION_LAYERS = "overshoot_option_layers"

# ── group 2: computed windows, exclusions and sources (activate after reading the before/after numbers) ────────────
#: F3. A partial export (``partial_at_export``) or stub is not a day eaten in the public five-channel intake mean,
#: the MCP deficit tool's intake mean, or the critics' and tripwires' day series (the overview's own rule, #5954).
PARTIAL_EXPORT_EXCLUDED = "partial_export_excluded"
#: F5a. Day pages print the window's maintenance estimate only on days on or after its as-of date, with that date.
#: Needs ``MAINTENANCE_LABELLED`` (the API's ``tdee_as_of``); without it the day pages are unchanged.
DAY_PAGE_MAINTENANCE_DATED = "day_page_maintenance_dated"
#: F5b. A partial-export day page is labelled as one and is not graded against the protein floor.
DAY_PAGE_PARTIAL_LABELLED = "day_page_partial_labelled"
#: F13. The Board intro states the charter's rate band instead of the profile row's February phase targets.
BOD_INTRO_CHARTER_RATE = "bod_intro_charter_rate"

SWITCHES: dict[str, bool] = {
    PUBLIC_VERDICT_NOT_CLEARANCE: False,
    MAINTENANCE_LABELLED: False,
    RATE_LINE_WORDING: False,
    MCP_SUSTAINABILITY_WORDING: False,
    OWNER_TARGET_LAYERS: False,
    BRIEF_TILE_LAYERS: False,
    OVERSHOOT_OPTION_LAYERS: False,
    PARTIAL_EXPORT_EXCLUDED: False,
    DAY_PAGE_MAINTENANCE_DATED: False,
    DAY_PAGE_PARTIAL_LABELLED: False,
    BOD_INTRO_CHARTER_RATE: False,
}

LABELLING: tuple[str, ...] = (
    PUBLIC_VERDICT_NOT_CLEARANCE,
    MAINTENANCE_LABELLED,
    RATE_LINE_WORDING,
    MCP_SUSTAINABILITY_WORDING,
    OWNER_TARGET_LAYERS,
    BRIEF_TILE_LAYERS,
    OVERSHOOT_OPTION_LAYERS,
)
COMPUTED: tuple[str, ...] = (
    PARTIAL_EXPORT_EXCLUDED,
    DAY_PAGE_MAINTENANCE_DATED,
    DAY_PAGE_PARTIAL_LABELLED,
    BOD_INTRO_CHARTER_RATE,
)


def on(item: str) -> bool:
    """Whether ``item`` is in force. An unknown item raises: a typo must never read as 'off' silently."""
    if item not in SWITCHES:
        raise KeyError(f"unknown nutrition-consistency item {item!r}; known: {sorted(SWITCHES)}")
    return bool(SWITCHES[item])


# ── the copy, in one place (public sentences are checked against the publication gate in the tests) ────────────────
#: What the public five-channel read is computed from, and what it is not (F1).
PUBLIC_BASED_ON = ("HRV", "sleep quality", "recovery", "habit completion", "training output")
PUBLIC_NOT_BASED_ON = ("food intake", "protein", "blood tests", "electrolytes", "lean mass")

PUBLIC_HONESTY = (
    "These five channels are recovery signals only. They do not measure food, protein, blood tests or muscle, "
    "so holding steady here is not a statement that the deficit is safe, and it is not medical advice."
)


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def short_day(iso: str) -> str:
    """``2026-11-09`` -> ``Nov 9`` (the site's own ``fmtShort`` form); anything else is returned as given."""
    try:
        y, m, d = str(iso)[:10].split("-")
        return f"{_MONTHS[int(m) - 1]} {int(d)}"
    except (ValueError, IndexError):
        return str(iso)


def public_holding_verdict(holding: int, start: str, end: str, deficit_published: bool) -> str:
    """The all-channels-holding verdict with the switch on (F1): what held, over which dates, and what it cannot say."""
    text = (
        f"{holding} of 5 recovery channels held steady from {short_day(start)} to {short_day(end)}. This read has no food, protein, lab or "
        "lean-mass input, so it does not say whether the deficit itself is safe or sustainable."
    )
    if not deficit_published:
        text += " The deficit is not published: the platform's estimate of it fails its own plausibility check."
    return text


MCP_HOLDING_RECOMMENDATION = (
    "The five recovery channels are holding. This is not a clearance of the deficit: read `critics`, "
    "`tripwire_reports` and `deficit.basis` for the intake, protein, rate and floor signals."
)
MCP_REFUSED_SUFFIX = " The deficit itself is refused as implausible on this window."
MCP_VETO_SUFFIX = " A critic vetoed on this window."

MCP_USE_FOR_OFF = "Use for: 'is my deficit sustainable?', 'am I cutting too hard?', "
MCP_USE_FOR_ON = (
    "Use for: 'are my recovery signals holding during the cut?', 'am I cutting too hard?' "
    "(read with critics + tripwires; not a clearance on its own), "
)


def mcp_holding_recommendation(deficit_published: bool, critic_veto: bool) -> str:
    """F15: the MCP recommendation when every channel holds, with the switch on."""
    return MCP_HOLDING_RECOMMENDATION + ("" if deficit_published else MCP_REFUSED_SUFFIX) + (MCP_VETO_SUFFIX if critic_veto else "")
