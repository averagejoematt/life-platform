"""cdk/stacks/reader_audience.py — #3499: the reader-audience facet DECIDES SNS routing.

#3423 curated `scripts/platform_model_alarms.py::READER_AUDIENCE_ALARMS` — the alarms
whose ALARM state means a real reader of averagejoematt.com is hitting a broken door —
and taught two READERS of the alarm board (the `/wrap` citation gate and
`remediation/agent.py::aged_alarm_escalations`) to escalate those on first red instead of
after 72h. It deliberately added no notification surface.

The consequence #3499 found: both of those readers run on a *slower or inverted* clock
than the detector. The AI canary fires `cron(20 16 ? * MON,WED,FRI *)`; the remediation
agent's own schedule was `45 14 * * 1,3,5` — **95 minutes BEFORE it**, so the responder
read Friday's board before Friday's probe had run. The only other reader is the daily
15:00Z digest. In a no-session week a Friday `/api/board_ask` outage was detected
immediately, digested Saturday and agent-escalated *Monday*. A detector whose responders
all run later than it — or worse, earlier — is a detector with no responder.

The fix is routing, not a new alarm: **a facet member ALSO publishes to the urgent topic**
(`life-platform-alerts`, ADR-052's real-time tier — immediate SES email, and the topic the
remediation dispatcher Lambda is SNS-subscribed to). The existing digest action stays, so
the batched daily record is unchanged and nothing is removed; the member simply gains a
second, immediate path to a human. No alarm is created, no topic is created, no schedule
is created — the live alarm inventory count is untouched.

WHY THIS MODULE EXISTS RATHER THAN 11 HAND-ADDED ACTIONS: the routing must be *derived*
from the facet, so that tagging an alarm `audience: reader` is the single act that both
lowers its escalation bar (#3423) and gives it the urgent route (#3499), and so that a
future member cannot be tagged-but-unrouted. `route_reader_audience()` is the one place
that decision is taken, and `assert_facet_fully_routed()` is its synth-time dead-man: an
`cdk synth` that has not routed every member of the registry RAISES, so a tagged-but-
unrouted alarm cannot deploy (the #2846 "does not synthesize, so it cannot deploy" shape).

WHERE THE REGISTRY LIVES: still `scripts/platform_model_alarms.py`, unmoved. It is a
hand-curated list of alarm NAMES, and standing rule 1 (the #2844 conformance guard) sweeps
`lambdas/ mcp/ cdk/` for exactly that — relocating it into `cdk/` would turn the platform's
own curated registry into a conformance violation. So this module imports it instead, and
`scripts/` stays its one home (which also keeps every existing `…platform_model_alarms.py::
READER_AUDIENCE_ALARMS` reference in docs/PROPORTIONALITY.md, docs/DEPENDENCY_GRAPH.md and
check_alarm_citations.py true).

IMPORT POSTURE: the module-level import is stdlib-only (`platform_model_alarms` imports
`ast` + `pathlib` and nothing else at module scope — its heavy work is behind function
calls), so importing this file needs no CDK installed and no AWS. `aws_cdk` is imported
INSIDE `route_reader_audience`, which is only ever reached from a real synth.
"""

from __future__ import annotations

import pathlib
import sys

_SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from platform_model_alarms import READER_AUDIENCE_ALARMS  # noqa: E402

# The urgent, real-time SNS topic (ADR-052 tier 1). Same ARN literal the monitoring stack
# already carries; kept here so serve_stack does not grow a second spelling of it.
URGENT_TOPIC_NAME = "life-platform-alerts"

# Every member routed during this synth, across every stack. Module-level because the
# facet spans two stacks (monitoring_stack declares the `ai-canary-*` family, serve_stack
# the `site-api-*` family) and the completeness proof has to span them too.
_ROUTED: set[str] = set()


def route_reader_audience(alarm, alarm_name: str, urgent_topic) -> bool:
    """Give `alarm` the urgent SNS action iff the facet names it. Returns whether it did.

    Additive: the caller has already attached whatever routing ADR-052 gave the alarm
    (digest for all 11 of today's members). This never removes an action.
    """
    if alarm_name not in READER_AUDIENCE_ALARMS:
        return False
    from aws_cdk import aws_cloudwatch_actions as cw_actions

    alarm.add_alarm_action(cw_actions.SnsAction(urgent_topic))
    _ROUTED.add(alarm_name)
    return True


def routed_members() -> frozenset[str]:
    """The facet members routed urgent so far this synth."""
    return frozenset(_ROUTED)


def reset_routing_record() -> None:
    """Clear the cross-stack record. For tests that synth more than one app."""
    _ROUTED.clear()


def assert_facet_fully_routed() -> None:
    """Synth-time dead-man: every facet member must have gained the urgent action.

    Called from cdk/app.py after every stack is constructed. A member that is tagged
    `audience: reader` but declared in a stack (or by a factory) that never calls
    `route_reader_audience` would otherwise be silently escalation-tagged and
    digest-only — the #3499 defect, restored, and invisible. This raises instead.
    """
    missing = sorted(set(READER_AUDIENCE_ALARMS) - _ROUTED)
    if missing:
        raise AssertionError(
            "#3499: reader-audience alarms tagged in READER_AUDIENCE_ALARMS but NOT routed to "
            f"the urgent topic during synth: {missing}. Every member must reach "
            f"{URGENT_TOPIC_NAME!r} — the declaring stack must call route_reader_audience() "
            "for it (see cdk/stacks/monitoring_stack.py::_alarm and cdk/stacks/serve_stack.py)."
        )
