"""cdk/stacks/web_edge_rate_rule.py — the ONE edge rate rule on the reader write doors (#6114).

Owner ruling 2026-11-16 (supersedes the 2026-08-23 "no edge WAF" priced acceptance,
docs/PROPORTIONALITY.md): a narrowly scoped AWS WAF rate rule for the reader-submission
endpoints only — never ordinary browsing — with conservative limits, and the backend
limiter (fail-closed identity, DDB atomic counters, per-route budgets; the IPv6 /64
grouping arrives with #6108) kept as the real per-route, per-network control. The rule is
a flood backstop, not a guarantee: no anonymous system stops a distributed botnet.

What this module is: plain data, no aws_cdk import. `web_acl_properties()` returns the
CloudFormation `AWS::WAFv2::WebACL` property map; `web_stack.py` declares it with
`cdk.CfnResource` in the SAME stack (us-east-1, the CLOUDFRONT-scope region) that owns the
distribution and feeds its `Arn` straight into the distribution's `WebACLId`. One stack owns
both ends, so the 2026-06 failure (a `web_acl_id` pointing at a deleted ACL) cannot recur:
the reference is a CloudFormation `GetAtt`, not a pasted ARN. Keeping the spec import-free
lets `tests/test_edge_rate_rule_6114.py` prove the scope on every CI run, with the
synthesized-template check on top wherever aws-cdk-lib is importable.

The rule, exactly:
  * default action ALLOW — every request the rule does not block passes untouched;
  * ONE rate-based rule, aggregate key IP, LIMIT requests per EVALUATION_WINDOW_SEC;
  * scope-down = HTTP method is exactly POST  AND  the URI path matches READER_WRITE_REGEX;
  * action BLOCK with a 429 whose JSON body carries the backend limiter's `error` key (so
    every page that handles the backend's 429 handles this one identically) plus
    `"limiter": "edge"` and a response header, so the nightly `ratelimit:edge_429`
    observation can tell the edge answering from the backend answering.

Why the paths are listed here and not imported from the route table: the route tables live
in Lambda modules whose import wires AWS clients, and synth must not do that. The list is
instead held honest by tests/test_edge_rate_rule_6114.py, which derives every public POST
door from the real route tables (site-api `_SIMPLE_ROUTES`, the site-api-ai handler's path
literals, the subscriber behaviour) and fails both ways: a public POST door the scope misses,
or a scoped path that is not a public POST door (a GET-only route, an owner-token door, a
path nothing routes).

IPv6 (verified 2026-11-16 against the live CloudFormation schema for AWS::WAFv2::WebACL:
`RateBasedStatement` offers IP / FORWARDED_IP / CUSTOM_KEYS / CONSTANT aggregation and no
prefix or mask setting): WAF counts each IPv6 address as its own aggregation instance — it
does NOT group a /64. A single IPv6 subscriber can therefore rotate addresses inside its /64
and spread past this rule; the backend's /64 grouping is the per-network control, and this
rule does not replace it.
"""

from __future__ import annotations

import json
import re

# ── the scope ────────────────────────────────────────────────────────────────────────────
# Exact paths: every POST a reader can make without the owner token, by origin.
SITE_API_READER_POSTS = (
    "/api/board_question",
    "/api/challenge_checkin",
    "/api/challenge_follow",
    "/api/challenge_vote",
    "/api/cohort_submit",
    "/api/experiment_follow",
    "/api/experiment_suggest",
    "/api/experiment_vote",
    "/api/nudge",
    "/api/page_feedback",
    "/api/predict_week",  # GET (the tally) stays untouched — the method leg is POST only
    "/api/reader_call",  # #6108 (open): routed {GET, POST}; covered before it can go live
    "/api/replicate_certify",
    "/api/submit_finding",
)
AI_READER_POSTS = ("/api/ask", "/api/board_ask", "/api/explain")

# Prefix: the subscriber origin answers EVERY POST under the CloudFront `/api/subscribe*`
# behaviour with a subscribe (email_subscriber_lambda.lambda_handler's default arm), so the
# scope must be the prefix, not the one literal, or a POST to /api/subscribeX walks past it.
SUBSCRIBER_POST_PREFIX = "/api/subscribe"

# Routed POST doors deliberately OUT of scope — each verifies an owner token before writing.
OWNER_TOKEN_POST_DOORS = {
    "/api/morning_note": "_handle_morning_note",  # #4189: the owner's morning-note write (verify_morning_note_token)
}

# Doors in the scope that a pending PR routes; the coverage test tolerates their absence
# from the route table until it lands, and nothing else.
PENDING_DOORS = {"/api/reader_call": "#6108 — the reader-call door, built dark"}


def _alternation(paths) -> str:
    names = sorted(p[len("/api/") :] for p in paths)
    for n in names:
        assert re.fullmatch(r"[a-z_]+", n), n  # nothing in the alternation needs escaping
    return "|".join(names)


READER_WRITE_REGEX = rf"^/api/({_alternation(SITE_API_READER_POSTS + AI_READER_POSTS)})$|^{SUBSCRIBER_POST_PREFIX}"

# ── the limit ────────────────────────────────────────────────────────────────────────────
# Measured 2026-10-17 → 2026-11-16 (31 days of the distribution's access logs, read-only):
# every scoped POST from a non-AWS address totalled 6 (submit_finding 5, challenge_checkin 1);
# the busiest single IP in any 5-minute window was 10 POSTs, and those were the platform's
# own probes from AWS (qa-smoke's 8-request board_ask trip, the subscribe canary). The floor
# AWS accepts is 10 (schema minimum); the windows are 60/120/300/600 s. 100 per 5 minutes is
# 10x the busiest observed source and far above any one reader (the tightest backend budgets
# are 3-7 an hour per route), leaving room for many readers behind one carrier-grade NAT.
LIMIT = 100
EVALUATION_WINDOW_SEC = 300

WAF_LIMIT_FLOOR = 10  # AWS::WAFv2::WebACL RateLimit minimum (live CFN schema, 2026-11-16)
WAF_EVALUATION_WINDOWS = (60, 120, 300, 600)  # EvaluationWindowSec enum (same source)

# ── the answer ───────────────────────────────────────────────────────────────────────────
EDGE_MARKER_HEADER = "edge-ratelimit"
EDGE_MARKER_VALUE = "waf"
RESPONSE_BODY_KEY = "reader-write-rate-limited"
RESPONSE_BODY = {"error": "Too many requests from this connection. Try again in a few minutes.", "limiter": "edge"}

WEB_ACL_NAME = "life-platform-amj-reader-writes"
RULE_NAME = "ReaderWritePostRate"


def _visibility(metric: str) -> dict:
    # WAF's own CloudWatch metrics (AWS/WAFV2, no charge) and sampled requests; no full logging.
    return {"CloudWatchMetricsEnabled": True, "MetricName": metric, "SampledRequestsEnabled": True}


def scope_down_statement() -> dict:
    return {
        "AndStatement": {
            "Statements": [
                {
                    "ByteMatchStatement": {
                        "FieldToMatch": {"Method": {}},
                        "PositionalConstraint": "EXACTLY",
                        "SearchString": "POST",
                        "TextTransformations": [{"Priority": 0, "Type": "NONE"}],
                    }
                },
                {
                    "RegexMatchStatement": {
                        "FieldToMatch": {"UriPath": {}},
                        "RegexString": READER_WRITE_REGEX,
                        # URL_DECODE: `/api/experiment%5Fvote` must not walk past the rule.
                        "TextTransformations": [{"Priority": 0, "Type": "URL_DECODE"}],
                    }
                },
            ]
        }
    }


def web_acl_properties() -> dict:
    """The CloudFormation properties of the ONE WebACL (CLOUDFRONT scope, us-east-1)."""
    return {
        "Name": WEB_ACL_NAME,
        "Scope": "CLOUDFRONT",
        "Description": "#6114 - one rate rule on POSTs to the reader write doors, everything else allowed",
        "DefaultAction": {"Allow": {}},
        "CustomResponseBodies": {
            RESPONSE_BODY_KEY: {"ContentType": "APPLICATION_JSON", "Content": json.dumps(RESPONSE_BODY, separators=(",", ":"))}
        },
        "Rules": [
            {
                "Name": RULE_NAME,
                "Priority": 0,
                "Statement": {
                    "RateBasedStatement": {
                        "AggregateKeyType": "IP",
                        "Limit": LIMIT,
                        "EvaluationWindowSec": EVALUATION_WINDOW_SEC,
                        "ScopeDownStatement": scope_down_statement(),
                    }
                },
                "Action": {
                    "Block": {
                        "CustomResponse": {
                            "ResponseCode": 429,
                            "CustomResponseBodyKey": RESPONSE_BODY_KEY,
                            "ResponseHeaders": [
                                {"Name": EDGE_MARKER_HEADER, "Value": EDGE_MARKER_VALUE},
                                {"Name": "Retry-After", "Value": str(EVALUATION_WINDOW_SEC)},
                            ],
                        }
                    }
                },
                "VisibilityConfig": _visibility(RULE_NAME),
            }
        ],
        "VisibilityConfig": _visibility(WEB_ACL_NAME),
    }
