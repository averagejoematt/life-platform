"""owner_actions.py — ADR-170: the alarms and notices only the owner can act on.

The owner's inbox carries ONE kind of platform email: a step only he can take. Every alarm
and ops notice still reaches the digest queue and is logged in full each morning, but the
daily email is sent only when one of the entries below is live, and its subject is the
instruction ("Do: approve the chronicle draft"), not the alarm name.

Who acts on everything else (ADR-170):
  * the system — the remediation dispatcher/agent already triages the urgent set;
  * a Claude session — every red prints in the SessionStart pre-flight, and a red held past
    3 days needs a tracker issue (the wrap citation gate), so code/config work is never lost
    by not emailing it.

An entry belongs here only if the fix needs the owner himself: his approval, his login, his
body, or his money. "A human should look at it" is not enough — that is a session's job.
`tests/test_owner_action_inbox.py` holds every pattern to a real producer (a declared alarm
or a literal notice subject in source), so an entry cannot outlive the thing it matches.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass


@dataclass(frozen=True)
class OwnerAction:
    patterns: tuple[str, ...]  # fnmatch, matched case-insensitively against AlarmName / notice subject
    short: str  # the subject line's instruction: "approve the chronicle draft"
    do: str  # the whole step, imperative, with where to do it
    why_you: str  # why no machine or session can do it instead


OWNER_ACTIONS: tuple[OwnerAction, ...] = (
    OwnerAction(
        patterns=("chronicle-delivery-heartbeat", "chronicle-autopublish-held"),
        short="approve or hold the chronicle draft",
        do=(
            "Open the chronicle preview email and press Approve — or reply in a Claude session "
            "'hold week N' if you want it skipped. Nothing reaches subscribers until you do."
        ),
        why_you="A chronicle publishes to subscribers only with your approval (#4694).",
    ),
    OwnerAction(
        patterns=("panelcast-autopublish-held", "[panel] episode wk* held for review*"),
        short="approve or drop the held Panel episode",
        do="Listen to the held Panel episode and approve or drop it (a Claude session can fetch the draft and play it back).",
        why_you="A Panel episode publishes only with your approval (#4694).",
    ),
    OwnerAction(
        patterns=("ingest-auth-unhealthy*",),
        short="reconnect a data source",
        do=(
            "Reconnect the source named below — its login expired. Start a Claude session and say "
            "'re-auth <source>'; it walks you through the sign-in."
        ),
        why_you="Only you can sign in to your own accounts.",
    ),
    OwnerAction(
        patterns=("calibration-deadman",),
        short="log the overdue calibration",
        do="Take and log the overdue calibration this week — tape measurements, progress photos or the titration run.",
        why_you="Only you can take the measurement.",
    ),
    OwnerAction(
        patterns=("fitness-battery-missed",),
        short="do the fitness test battery",
        do="Do the fitness test battery and log it in Hevy (or tell the coach your results in a session).",
        why_you="Only you can do the test.",
    ),
    OwnerAction(
        patterns=("budget-tier-hardstop", "paging-budget-tier-3", "*budget tier raised *→3*"),
        short="decide on AI spend (paused at the ceiling)",
        do=(
            "All AI is paused at the monthly ceiling until the 1st. Decide: leave it paused, or raise "
            "the ceiling for the month (surge mode) — tell a Claude session which."
        ),
        why_you="Spending more money is your call (ADR-063 / ADR-133).",
    ),
)

# A standing owner red that did not newly fire re-surfaces once a week, not daily — a to-do
# repeated every morning is the noise ADR-170 removes. Monday = weekday 0 (Pacific).
STANDING_REMINDER_WEEKDAY = 0


def owner_action_for(name: str) -> OwnerAction | None:
    """The owner action an alarm name / notice subject asks for, or None (not the owner's job)."""
    n = (name or "").strip().lower()
    for action in OWNER_ACTIONS:
        # '[' is literal in our subjects ("[Panel] …"), never an fnmatch character class.
        if any(fnmatch.fnmatchcase(n, p.lower().replace("[", "[[]")) for p in action.patterns):
            return action
    return None
