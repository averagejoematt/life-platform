# module-size-exception: canonical registry (#3615) — HOOK_REGISTRY is a table of
# reader-hook rows plus their downstream-artifact rows and the thin accessors over it.
# Growth is linear in the number of HOOKS, not in feature complexity, and splitting it
# would create a second place to look up "which hook owns this door", which is the exact
# drift this file exists to end. See docs/ENGINEERING_STANDARDS.md §2.
"""hook_registry.py — THE registry of reader hooks and their downstream artifacts (#3615).

WHAT WAS MISSING, STATED PLAINLY
  Before this file the platform had exactly ONE per-hook liveness probe:
  `qa_smoke_lambda.check_predict_week_freshness()`. Ask-the-board was observed only by
  the 3x/week AI canary, chronicle and podcast cadence by nothing at all, and the
  publication extension's five downstream artifacts — the post PERMALINK, the served
  MANIFEST, `RECAP#latest`, the SHARE-KIT and the onboarding email — were each checked,
  when at all, by a different one-off with its own idea of what "fine" meant. So the
  question "is every reader hook alive TODAY, on cycle day N?" had no answer anywhere,
  and the honest answer on any given night was: nobody looked.

WHAT A ROW COMMITS TO
  A `Hook` names a reader-facing entry point and the `post_endpoints` the SITE reaches
  it through (verbatim as `tests/test_hook_registry_3615.py`'s scanner emits them, `*`
  standing for a JS template hole). The scanner sweeps `site/**/*.js` for POST targets
  and every token it finds must be claimed by exactly one row — that is the derivation
  guard: a hook added to site/ without a row REDS, rather than joining the set of things
  nobody probes.

  An `Artifact` is one CELL of the nightly matrix: a bounded probe (one HTTP GET, one
  `get_item`, one `Limit`-ed query, one `get_object`) whose verdict is ALIVE,
  HONESTLY_ABSENT or MISSING. There is no fourth value and no shrug: a cell that cannot
  be shown alive and carries no DECLARED absence contract is MISSING, and MISSING is a
  FAIL. (A cell the read budget never reached is reported separately as `deferred` — an
  absence of evidence, never a pass. See census_probe.py.)

HONEST ABSENCE IS A COMMITMENT, NOT A DEFAULT
  `Absence` requires a reason, a DATE it was declared and the issue that owns it. That
  is what stops "honestly absent" from becoming the escape hatch every red cell takes:
  an absence with nobody's name on it is not honest, it is unexamined. Today exactly two
  rows carry one — predict-the-week outside a live cycle (there is no week to bet on),
  and the podcast feed (zero episodes). Since #3615 box 5 the podcast row is also
  LOAD-BEARING OUTSIDE this module: `scripts/v4_chrome.dark_feeds()` derives from it, so
  a feed declared dark here is a feed the SITE does not advertise. Declaring a feed dark
  and advertising it anyway was the actual defect — 11 pages offered an empty show to
  every podcast client that unfurled them — and the two halves now move together, or
  `tests/test_podcast_feed_link_3615.py` reds.

THE RATCHET
  `tests/test_hook_registry_3615.py` pins a floor on the number of hooks and cells: the
  registry may only GROW. Deleting a hook is a deliberate edit to that floor with a
  reason in the PR, never a silent shrink — the #395 tool-audit lesson applied to hooks.

Pure data + pure accessors: no AWS, no network, no clock. The walk lives in
`hook_liveness_qa.py`; this module is what it walks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ── cell verdicts ────────────────────────────────────────────────────────────
ALIVE = "alive"
HONESTLY_ABSENT = "honestly-absent"
MISSING = "missing"
DEFERRED = "deferred"
VERDICTS = (ALIVE, HONESTLY_ABSENT, MISSING, DEFERRED)

# ── probe kinds (the evaluator in hook_liveness_qa dispatches on these) ───────
HTTP_DOOR = "http_door"  # GET a POST-only endpoint: its method guard proves the route is mounted
HTTP_JSON = "http_json"  # GET a JSON surface and test one declared predicate
HTTP_TEXT = "http_text"  # GET a text/XML surface and count a declared needle
HTTP_PAGE = "http_page"  # GET an HTML page (permalink reachability)
S3_JSON = "s3_json"  # get_object a generated artifact
DDB_ROW = "ddb_row"  # get_item one key
DDB_WINDOW = "ddb_window"  # one Limit-ed / filtered query over a bounded window
PROBE_KINDS = (HTTP_DOOR, HTTP_JSON, HTTP_TEXT, HTTP_PAGE, S3_JSON, DDB_ROW, DDB_WINDOW)

#: Honest-absence contracts the evaluator knows how to TEST. A row may not invent one:
#: an absence whose condition nothing evaluates is a shrug with a comment on it.
ABSENCE_CONTRACTS = (
    "no_live_cycle",  # honest only while no experiment cycle is running
    "nothing_to_produce",  # honest only when the probe proves there was no input to act on
    "declared_dark",  # honest because the platform has DECLARED the surface dark (dated, owned)
)


@dataclass(frozen=True)
class Absence:
    """The conditions under which this artifact's absence is HONEST rather than missing."""

    contract: str
    reason: str
    declared_on: str  # ISO date the declaration was made
    issue: str  # the issue that owns the residual


@dataclass(frozen=True)
class Artifact:
    """One (hook × artifact) cell of the nightly matrix."""

    id: str
    label: str
    kind: str
    locator: str  # url path, S3 key, DDB "pk|sk", or "derive:<name>" for a locator read from another cell
    expect: dict = field(default_factory=dict)
    absence: Optional[Absence] = None


@dataclass(frozen=True)
class Hook:
    """A reader-facing hook and everything downstream of it that must be alive."""

    id: str
    label: str
    why: str  # what a reader loses when this hook is dark
    post_endpoints: tuple = ()  # verbatim scanner tokens; () for a hook with no reader POST
    artifacts: tuple = ()


# ── the registry ─────────────────────────────────────────────────────────────
# Ordered cheapest-and-most-load-bearing first: the read budget is spent top-down, so a
# short night reports the doors and the chronicle chain rather than stopping at random.
HOOK_REGISTRY: tuple = (
    Hook(
        id="predict_week",
        label="Predict the Week",
        why="the primary reader-participation hook — a dark week is a reader invited to bet on nothing",
        post_endpoints=("*/predict_week",),
        artifacts=(
            Artifact(
                id="live_subject",
                label="an active subject on the current ISO week",
                kind=HTTP_JSON,
                locator="/api/predict_week",
                expect={"truthy_path": "active"},
                absence=Absence(
                    contract="no_live_cycle",
                    reason="no experiment cycle is running, so there is no week to bet on — the fail-closed state, not a dark hook",
                    declared_on="2026-09-21",
                    issue="#1953",
                ),
            ),
        ),
    ),
    Hook(
        id="ask_the_board",
        label="Ask the platform (/api/ask)",
        why="the reader's direct question door; a 404 here is a silent end to every ask on the site",
        post_endpoints=("/api/ask",),
        artifacts=(Artifact(id="door", label="POST door mounted", kind=HTTP_DOOR, locator="/api/ask"),),
    ),
    Hook(
        id="board_ask",
        label="Ask the board",
        why="the persona board's two reader doors — probed today only by the 3x/week AI canary",
        post_endpoints=("/api/board_ask", "/api/board_question"),
        artifacts=(
            Artifact(id="door_ask", label="POST /api/board_ask mounted", kind=HTTP_DOOR, locator="/api/board_ask"),
            Artifact(id="door_question", label="POST /api/board_question mounted", kind=HTTP_DOOR, locator="/api/board_question"),
        ),
    ),
    Hook(
        id="chronicle",
        label="The chronicle (the weekly installment + its publication extension)",
        why="the platform's narrative spine; its five downstream artifacts were each checked by a different one-off",
        artifacts=(
            Artifact(
                id="manifest",
                label="served journal manifest carries at least one post",
                kind=HTTP_JSON,
                locator="/journal/posts.json",
                expect={"nonempty_path": "posts"},
            ),
            Artifact(
                id="permalink",
                label="the newest installment's own url is reachable",
                kind=HTTP_PAGE,
                locator="derive:newest_post_url",
                expect={"status_in": (200,)},
            ),
            Artifact(
                id="share_kit",
                label="the newest installment's share kit exists",
                kind=S3_JSON,
                locator="derive:newest_post_share_kit_key",
                expect={"nonempty_path": "caption"},
            ),
            Artifact(
                id="recap_latest",
                label="RECAP#latest is present and not tombstoned",
                kind=DDB_ROW,
                locator="USER#matthew#SOURCE#chronicle|RECAP#latest",
                expect={"not_tombstoned": True, "max_age_days": 35, "date_fields": ("generated_at", "date", "updated_at")},
            ),
            Artifact(
                id="onboarding_email",
                label="the subscriber bridge email (which carries the newest installments) has fired for its confirmed subscribers",
                kind=DDB_WINDOW,
                locator="USER#matthew#SOURCE#subscribers|SUB#",
                expect={"window_days": 30, "created_field": "confirmed_at", "produced_field": "onboarding_sent_at"},
                absence=Absence(
                    contract="nothing_to_produce",
                    reason="no subscriber confirmed inside the window, so there was no bridge email to send — absence proven from the same query, not assumed",
                    declared_on="2026-09-21",
                    issue="#3615",
                ),
            ),
        ),
    ),
    Hook(
        id="podcast",
        label="The podcast feed",
        why="11 pages advertise /podcast/feed.xml; a feed with no items unfurls as real in every podcast client",
        artifacts=(
            Artifact(
                id="feed_items",
                label="the advertised feed carries at least one episode",
                kind=HTTP_TEXT,
                locator="/podcast/feed.xml",
                expect={"needle": "<item>", "min_count": 1},
                absence=Absence(
                    contract="declared_dark",
                    reason=(
                        "the feed ships a channel and ZERO <item> elements (re-measured live 2026-09-21: 200, 593 bytes, "
                        "no <item>). #3615 box 5 took the honest-absence path that day: v4_chrome.syndication_links() "
                        "withholds the <link rel=alternate> for every feed THIS declaration names, so the 11 pages that "
                        "advertised an empty show no longer do, while the census keeps probing the live feed nightly so "
                        "the darkness stays reported rather than invisible. Building the TTS episodes remains the owner's "
                        "alternative and the clause is satisfied either way: delete this Absence, re-run "
                        "scripts/v4_build_dispatches.py, and the advertisement returns in the same commit"
                    ),
                    declared_on="2026-09-21",
                    issue="#3615",
                ),
            ),
        ),
    ),
    Hook(
        id="votes",
        label="Vote / follow on a challenge or experiment",
        why="the reader-participation write surface; all four doors are built from one JS template, so one break takes all four",
        post_endpoints=("/api/*_vote", "/api/*_follow"),
        artifacts=(
            Artifact(id="door_challenge_vote", label="POST /api/challenge_vote mounted", kind=HTTP_DOOR, locator="/api/challenge_vote"),
            Artifact(
                id="door_challenge_follow", label="POST /api/challenge_follow mounted", kind=HTTP_DOOR, locator="/api/challenge_follow"
            ),
            Artifact(id="door_experiment_vote", label="POST /api/experiment_vote mounted", kind=HTTP_DOOR, locator="/api/experiment_vote"),
            Artifact(
                id="door_experiment_follow", label="POST /api/experiment_follow mounted", kind=HTTP_DOOR, locator="/api/experiment_follow"
            ),
        ),
    ),
    Hook(
        id="explain",
        label="Explain this surface",
        why="the grounded on-page explainer door (ADR-104's refusal path lives behind it)",
        post_endpoints=("/api/explain",),
        artifacts=(Artifact(id="door", label="POST door mounted", kind=HTTP_DOOR, locator="/api/explain"),),
    ),
    Hook(
        id="subscribe",
        label="Subscribe to the weekly signal",
        why="the one place a reader converts; a dead door is invisible from the page, which renders its own success state",
        post_endpoints=("/api/subscribe",),
        artifacts=(Artifact(id="door", label="POST door mounted", kind=HTTP_DOOR, locator="/api/subscribe"),),
    ),
    Hook(
        id="reader_findings",
        label="Submit a finding",
        why="reader-submitted findings reach a moderation queue; a dead door silently discards them",
        post_endpoints=("/api/submit_finding",),
        artifacts=(Artifact(id="door", label="POST door mounted", kind=HTTP_DOOR, locator="/api/submit_finding"),),
    ),
    Hook(
        id="challenge_checkin",
        label="Challenge check-in",
        why="the daily 'I did the rep too' hook — the only participation surface with a per-day cadence",
        post_endpoints=("/api/challenge_checkin",),
        artifacts=(Artifact(id="door", label="POST door mounted", kind=HTTP_DOOR, locator="/api/challenge_checkin"),),
    ),
    Hook(
        id="experiment_suggest",
        label="Suggest an experiment",
        why="reader-proposed experiments enter the library queue through this door",
        post_endpoints=("/api/experiment_suggest",),
        artifacts=(Artifact(id="door", label="POST door mounted", kind=HTTP_DOOR, locator="/api/experiment_suggest"),),
    ),
    Hook(
        id="replicate_certify",
        label="Replication self-certification",
        why="the engagement ladder's top rung — a PII-free self-cert POST",
        post_endpoints=("*/replicate_certify",),
        artifacts=(Artifact(id="door", label="POST door mounted", kind=HTTP_DOOR, locator="/api/replicate_certify"),),
    ),
    Hook(
        id="cohort_submit",
        label="Cohort join",
        why="the cockpit's cohort door",
        post_endpoints=("*/cohort_submit",),
        artifacts=(Artifact(id="door", label="POST door mounted", kind=HTTP_DOOR, locator="/api/cohort_submit"),),
    ),
)


# ── accessors (every consumer derives; nobody re-enumerates) ─────────────────
# Deliberately minimal: under the one-bundle rule (#781) every public def here ships in
# ~104 Lambda zips and reads as API, so the registry exposes only what the nightly walk
# calls. The derivation guard's endpoint-claim matching lives in
# tests/test_hook_registry_3615.py, where its only caller is.
def hooks() -> tuple:
    return HOOK_REGISTRY


def cells() -> list:
    """Every (hook, artifact) pair — THE matrix, in probe order."""
    return [(h, a) for h in HOOK_REGISTRY for a in h.artifacts]
