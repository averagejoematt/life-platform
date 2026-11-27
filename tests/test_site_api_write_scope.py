"""tests/test_site_api_write_scope.py — SEC-01: the public site-api DynamoDB write
must be scoped (LeadingKeys) to exactly the interactive partitions the code writes.

Two guards:
 1. every partition the site-api actually writes is covered by the role's LeadingKeys
    allowlist (so scoping never breaks a live public feature); and
 2. a write-call-site canary — if a new put_item/update_item appears in the site-api
    social module, this test fails so its partition gets added to the allowlist BEFORE
    it ships an AccessDenied to a public endpoint.
"""

import os
import re
from fnmatch import fnmatch
from glob import glob

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# #2604: role_policies.py is a facade; site_api()/site_api_ai() now live in the
# role_policies_serve.py sibling. Locate the definition across the FAMILY rather than
# pinning one filename, so the next split cannot make this canary go quietly blind.
_ROLE_FAMILY = sorted(glob(os.path.join(_REPO, "cdk", "stacks", "role_policies*.py")))
_WEB = os.path.join(_REPO, "lambdas", "web")
# #2515: the social module is a facade + `site_api_social_*.py` siblings that hold the
# handler bodies. The canary counts the FAMILY — globbed, never hand-listed — so the
# split cannot make the count fall by moving a write instead of removing one.
_SOCIAL_FAMILY = sorted(glob(os.path.join(_WEB, "site_api_social*.py")))


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _role_src(marker):
    """Source of the `role_policies*.py` family member that contains `marker`."""
    for path in _ROLE_FAMILY:
        text = _read(path)
        if marker in text:
            return text
    raise AssertionError(f"{marker!r} not found in any of {[os.path.basename(p) for p in _ROLE_FAMILY]}")


def _site_api_leadingkeys():
    """Extract the LeadingKeys patterns from role_policies.site_api()'s write statement."""
    src = _role_src("def site_api(")
    body = src[src.index("def site_api(") : src.index("def site_api_ai(")]
    block = re.search(r'DynamoDBWrite.*?dynamodb:LeadingKeys"\s*:\s*\[(.*?)\]', body, re.DOTALL)
    assert block, "site_api() DynamoDBWrite LeadingKeys block not found"
    return set(re.findall(r'"([^"]+)"', block.group(1)))


# Every concrete partition-key the site-api writes (site_api_social.py + rate_limiter.py),
# enumerated from the code. Keep in sync with the write call sites.
_WRITTEN_KEYS = [
    "VOTES#rate_limit",  # vote/follow/predict per-IP rate limits
    "VOTES#experiment_library",  # experiment votes
    "VOTES#challenges",  # challenge votes
    "VOTES#predict_week",  # predict-the-week votes
    "VOTES#ladder_replicator",  # #1393 — engagement-ladder self-cert Replicator counter
    "EXPERIMENT_FOLLOWS",  # experiment follows
    "CHALLENGE_FOLLOWS",  # challenge follows
    "USER#matthew#SOURCE#experiment_suggestions",  # reader experiment suggestions
    "USER#matthew#SOURCE#reader_feedback",  # #4182: /api/page_feedback
    "USER#matthew#SOURCE#morning_note",  # #4189: /api/morning_note — the owner's four words (owner-token write)
    "CHALLENGE_CHECKINS#cold-shower-finish",  # #6087: reader challenge check-ins (never the owner's challenges row)
    "USER#matthew#SOURCE#evening_ritual",  # #769 (ADR-124): one-tap evening-ritual taps
    "COHORT#resting_heart_rate#2026-W30",  # #1394: anonymous cohort-strip submissions (COHORT#<metric>#<week>)
    "RATE#board_ask#deadbeef",  # shared rate_limiter.py → RATE#{endpoint}#{ip_hash}
    "READERCALL#sleep-pred_20261114_x",  # #6088: web/site_api_reader_call.py — TAP#<ip_hash> + TALLY#<choice>
    "USER#matthew#SOURCE#brief_trial",  # #6175: web/site_api_brief_response.py — TOKEN# spend + SEND# answer (POST only)
]


def test_leadingkeys_cover_every_site_api_write():
    patterns = _site_api_leadingkeys()
    uncovered = [k for k in _WRITTEN_KEYS if not any(fnmatch(k, p) for p in patterns)]
    assert not uncovered, f"site-api writes not covered by LeadingKeys {sorted(patterns)}: {uncovered}"


def test_write_call_site_canary():
    """If this count changes, a write was added/removed — verify its partition is in
    _WRITTEN_KEYS and the role's LeadingKeys before updating this baseline."""
    n = sum(len(re.findall(r"\.(put_item|update_item)\(", _read(f))) for f in _SOCIAL_FAMILY)
    assert n == 18, (
        f"site_api_social family write count is {n}, baseline 18 — a write was added/removed. "
        "Confirm its partition is in the SEC-01 LeadingKeys allowlist + _WRITTEN_KEYS, then update this baseline."
    )


# ── #531: the AI lambda's write scope (board_ask episodic write-back) ─────────

# #3118: the AI lambda is a handler + `site_api_ai_*.py` siblings that hold extracted
# bodies (request parsing #2688, context #2667, the #546 session store #3118). The
# canary counts the FAMILY — globbed, never hand-listed, exactly like _SOCIAL_FAMILY —
# because the previous single-file form went from 3 writes to 1 the moment the session
# store moved out, and a canary that reads "fewer writes now" as a pass is a canary
# that has gone blind rather than one reporting good news.
_AI_FAMILY = sorted(glob(os.path.join(_WEB, "site_api_ai*.py")))

# Every concrete partition-key the AI lambda writes: rate-limit counters
# (rate_limiter.py, UpdateItem) + the coach interaction write-back (PutItem).
_AI_WRITTEN_KEYS = [
    "RATE#board_ask#deadbeef",
    "RATE#ask#deadbeef",
    "COACH#sleep_coach",  # INTERACTION# episodic records (#531)
    "BOARDSESS#deadbeefcafe",  # #546: board follow-up sessions (PutItem + UpdateItem)
]


def _site_api_ai_leadingkeys():
    """Union of LeadingKeys patterns across site_api_ai()'s write statements."""
    src = _role_src("def site_api_ai(")
    start = src.index("def site_api_ai(")
    nxt = src.find("\ndef ", start + 1)
    body = src[start : nxt if nxt > 0 else len(src)]
    patterns = set()
    for block in re.findall(r'dynamodb:LeadingKeys"\s*:\s*\[(.*?)\]', body, re.DOTALL):
        patterns |= set(re.findall(r'"([^"]+)"', block))
    assert patterns, "site_api_ai() LeadingKeys blocks not found"
    return patterns


def test_ai_leadingkeys_cover_every_ai_lambda_write():
    patterns = _site_api_ai_leadingkeys()
    uncovered = [k for k in _AI_WRITTEN_KEYS if not any(fnmatch(k, p) for p in patterns)]
    assert not uncovered, f"site-api-ai writes not covered by LeadingKeys {sorted(patterns)}: {uncovered}"


def test_ai_write_call_site_canary():
    """The AI family's DDB writes: the #531 interaction write-back (PutItem,
    COACH#*) + the #546 board-session mint (PutItem) and follow-up append
    (UpdateItem, BOARDSESS#*). Rate-limit counters live in the shared
    rate_limiter module. If this count changes, scope the new write's partition
    first."""
    n = sum(len(re.findall(r"\.(put_item|update_item)\(", _read(f))) for f in _AI_FAMILY)
    assert n == 3, (
        f"site_api_ai family write count is {n}, baseline 3 — a write was added/removed. "
        "Confirm its partition is in site_api_ai()'s LeadingKeys + _AI_WRITTEN_KEYS, then update this baseline."
    )


def test_ai_interaction_write_is_putitem_only():
    """The COACH#* write grant must stay PutItem-only — the public lambda must
    never gain the ability to mutate STANCE#/COMPRESSED#/OUTPUT# in place."""
    src = _role_src('sid="DynamoDBCoachInteractionWrite"')
    start = src.index('sid="DynamoDBCoachInteractionWrite"')
    block = src[start : start + 600]
    m = re.search(r"actions=\[(.*?)\]", block, re.DOTALL)
    assert m and '"dynamodb:PutItem"' in m.group(1)
    assert "UpdateItem" not in m.group(1) and "DeleteItem" not in m.group(1)


# ══════════════════════════════════════════════════════════════════════════════
# #5543: the READ half — every partition a public serving role reaches is granted
# ══════════════════════════════════════════════════════════════════════════════
# premerge-gate: repo-shape ratchet — the reached-partition set is read off the Lambdas' import closure (AST), so a new read can red before merge, not after the deploy 403s a public route
#
# cdk/stacks/role_policies_serve.py scopes each public role's GetItem/Query with
# dynamodb:LeadingKeys. An under-grant does not fail a deploy; it fails a reader, as an
# AccessDenied inside a fail-soft read (a blank section) or a 5xx. So the reach is derived
# from the code, never hand-listed, two ways:
#
#   STATIC  — walk the Lambda's import closure (every `import`/`from` it can execute,
#             lazy ones included) and collect every string that names a partition:
#             a USER#… key shape, or any literal the phase taxonomy recognises as a
#             registered partition (phase_taxonomy.classify — it raises on anything that
#             is not, which is what separates a partition from a sort key). A read cannot
#             reach a partition without naming it or its family somewhere in that closure;
#             data-driven ids (a coach id, a book id, a routine hash) land under the family
#             the code names. phase_taxonomy.py itself is excluded: it is the classifier
#             and names every partition in the table.
#   OBSERVED — a read-only replay of every GET route (+ query-string variants, ~375
#             requests) against the live table on 2026-11-15, with every non-read AWS call
#             blocked, recorded the partitions below (families; opaque ids collapsed).
import ast  # noqa: E402

_LAMBDAS = os.path.join(_REPO, "lambdas")
_SERVE_POLICIES = os.path.join(_REPO, "cdk", "stacks", "role_policies_serve.py")
_CLASSIFIER = os.path.join("experiment", "phase_taxonomy.py")
_UNKNOWN = "\x00"

# Families a closure NAMES but the role never READS — each with the reason. Kept tiny and
# reasoned: an entry here is a partition the role is denied while the code mentions it.
_NAMED_NOT_READ = {
    "EVALRET#": "experiment/eval_retention.retain() is a WRITE (fail-soft); fetch() is the eval-harvest's, never a route's",
    "PERSONA#": "named as a classification prefix (narrative_publication.NARRATIVE_PK_PREFIXES, pk_census); no public read",
    "PROGRESS_LINK#": "the progress viewer's one-time nonce, a conditional PutItem; never read",
}

# OBSERVED, 2026-11-15 (see above). Opaque ids are written as their family.
_OBSERVED_READS = {
    "SITE_API_READ_PARTITIONS": [
        "USER#matthew",
        "USER#matthew#ROUTINE#5f3f5f1f",
        "USER#matthew#SOURCE#whoop",
        "USER#matthew#SOURCE#email_log#daily_brief",
        "USER#matthew#SOURCE#notion",
        "COACH#sleep_coach",
        "COACH#commitments",
        "COACH#computation",
        "ENSEMBLE#digest",
        "ENSEMBLE#dispute",
        "ENSEMBLE#docket",
        "READING#PROFILE",
        "READING#HORIZON",
        "READING#IDEA_INDEX",
        "READING#0161d408f99efdfd",
        "BOOK#0161d408f99efdfd",
        "BROADCAST_ORIGIN#bluesky",
        "BROADCAST_ORIGIN#x",
        "VOICEFIDELITY#scoreboard",
        "VOTES#challenges",
        "VOTES#experiment_library",
        "VOTES#ladder_replicator",
        "VOTES#predict_week",
        "VOTES#rate_limit",
    ],
    "SITE_API_INDEX_READ_PARTITIONS": [
        "READING_SESSION",
        "READING_STATUS#reading",
        "READING_STATUS#want",
        "READING_STATUS#finished",
        "READING_STATUS#abandoned",
    ],
    "SITE_API_AI_READ_PARTITIONS": [
        "USER#matthew",
        "USER#matthew#SOURCE#computed_metrics",
        "COACH#sleep_coach",
        "COACH#explorer_coach",
    ],
    "PROGRESS_VIEWER_READ_PARTITIONS": [
        "USER#matthew#SOURCE#progress_photos",
        "USER#matthew#SOURCE#withings",
        "USER#matthew#SOURCE#measurements",
    ],
}


def _read_partitions(name):
    """A module-level tuple from role_policies_serve.py, by AST (no CDK import needed)."""
    tree = ast.parse(_read(_SERVE_POLICIES))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError(f"{name} not found in role_policies_serve.py")


def _statement_uses(sid_fn, constant):
    """True when `def <sid_fn>(` passes `constant` to its DynamoDB read condition."""
    src = _read(_SERVE_POLICIES)
    start = src.index(f"def {sid_fn}(")
    nxt = src.find("\ndef ", start + 1)
    return f"_leading_keys({constant})" in src[start : nxt if nxt > 0 else len(src)]


def _module_file(mod):
    base = os.path.join(_LAMBDAS, *mod.split("."))
    for cand in (base + ".py", os.path.join(base, "__init__.py")):
        if os.path.isfile(cand):
            return cand
    return None


def _import_closure(root):
    """{path: ast} for every lambdas/ module `root` can import, lazy imports included."""
    seen, todo = {}, [_module_file(root)]
    while todo:
        path = todo.pop()
        if not path or path in seen:
            continue
        tree = ast.parse(_read(path))
        seen[path] = tree
        pkg = os.path.relpath(os.path.dirname(path), _LAMBDAS).replace(os.sep, ".")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                todo += [_module_file(a.name) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = pkg.split(".")[: len(pkg.split(".")) - (node.level - 1)]
                    base = ".".join([*parts, base]) if base else ".".join(parts)
                todo.append(_module_file(base))
                todo += [_module_file(f"{base}.{a.name}") for a in node.names]
    return seen


def _strings(tree):
    """Every str literal, and every f-string rendered with _UNKNOWN for its holes."""
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            yield "".join(str(v.value) if isinstance(v, ast.Constant) else _UNKNOWN for v in node.values)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def _probe(s):
    """A concrete key for a pattern: the owner id for a USER# hole, `x` for any other."""
    if s.startswith("USER#" + _UNKNOWN):
        s = "USER#matthew" + s[len("USER#" + _UNKNOWN) :]
    s = s.replace(_UNKNOWN, "x")
    return s + "x" if s.endswith("#") else s


def _reached_partitions(root):
    """{probe_key: first site} for every partition the closure of `root` names."""
    from experiment import phase_taxonomy  # noqa: PLC0415

    head = re.compile(r"^[A-Z][A-Z0-9_]*(#|$)")
    reached = {}
    for path, tree in _import_closure(root).items():
        rel = os.path.relpath(path, _LAMBDAS)
        if rel == _CLASSIFIER:
            continue
        for s in _strings(tree):
            if " " in s or len(s) > 120 or not head.match(s) or s in ("USER#", "USER#" + _UNKNOWN):
                continue
            if any(s.startswith(p) for p in _NAMED_NOT_READ):
                continue
            key = _probe(s)
            if not s.startswith("USER#"):
                try:
                    phase_taxonomy.classify(key, "")
                except KeyError:
                    continue  # not a registered partition: a sort key, a label, a constant
            reached.setdefault(key, rel)
    return reached


def _uncovered(keys, patterns):
    return sorted(k for k in keys if not any(fnmatch(k, p) for p in patterns))


# The two public site roles, by the closure each Lambda actually executes.
_CLOSURE_ROLES = {
    "SITE_API_READ_PARTITIONS": ("site_api", "web.site_api_lambda"),
    "SITE_API_AI_READ_PARTITIONS": ("site_api_ai", "web.site_api_ai_lambda"),
}


def test_every_partition_a_public_site_role_reaches_is_granted():
    """#5543 box 4: a route that reads a partition outside its role's allowlist reds here.

    One test over both roles (not a parametrize): it reports every offender at once."""
    problems = []
    for constant, (fn, root) in _CLOSURE_ROLES.items():
        assert _statement_uses(fn, constant), f"{fn}()'s DynamoDBRead must be conditioned on {constant}"
        patterns = _read_partitions(constant)
        reached = _reached_partitions(root)
        assert len(reached) >= 10, f"{root}: only {len(reached)} partitions reached — the closure walk went blind"
        for key in _uncovered(reached, patterns):
            problems.append(f"{fn}: reaches {key!r} (named in lambdas/{reached[key]}) — not in {constant}")
    assert not problems, (
        "A public site Lambda names a partition its role cannot read; the read will AccessDenied in "
        "production. Add the family to the allowlist in cdk/stacks/role_policies_serve.py (an IAM change: "
        "LifePlatformServe), or, if the code only names it and never reads it, to _NAMED_NOT_READ with "
        "the reason:\n  " + "\n  ".join(problems)
    )


def test_every_observed_live_read_is_granted_and_the_viewer_reads_three():
    """The empirical half, plus the progress viewer, whose reach is exact and small enough to pin.

    The viewer's closure is mostly site_api_common, so the closure scan would credit it with
    every family the site names; its own module is the honest measure. Its read sites are the
    photo index query and two site_api_common helpers, each with a literal source."""
    problems = []
    for constant, observed in _OBSERVED_READS.items():
        problems += [f"{constant}: live read {k!r} not granted" for k in _uncovered(observed, _read_partitions(constant))]
    assert _statement_uses("site_api", "SITE_API_INDEX_READ_PARTITIONS"), "the GSI statement must carry its own scope"
    assert _statement_uses("progress_viewer", "PROGRESS_VIEWER_READ_PARTITIONS")

    viewer = _read(os.path.join(_WEB, "progress_viewer_lambda.py"))
    sources = re.findall(r"_(?:query_source|latest_item_asof|latest_item)\(\s*\"([a-z_]+)\"", viewer)
    index_pk = re.search(r'^INDEX_PK = f"\{USER_PREFIX\}([a-z_]+)"', viewer, re.M)
    assert index_pk, "progress_viewer_lambda.INDEX_PK moved — re-derive the viewer's reach"
    reached = {f"USER#matthew#SOURCE#{s}" for s in [*sources, index_pk.group(1)]}
    n_reads = len(re.findall(r"\b(?:table\.(?:query|get_item)|_query_source|_latest_item_asof|_latest_item)\(", viewer))
    assert n_reads == 3, (
        f"progress_viewer_lambda.py has {n_reads} DynamoDB read sites, baseline 3 — a read was added/removed. "
        "Add its partition to PROGRESS_VIEWER_READ_PARTITIONS (LifePlatformWeb), then update this baseline."
    )
    granted = set(_read_partitions("PROGRESS_VIEWER_READ_PARTITIONS"))
    problems += [f"progress_viewer reads {k!r} — not granted" for k in sorted(reached - granted)]
    problems += [f"progress_viewer grants {k!r} — not read (the grant is wider than the page)" for k in sorted(granted - reached)]
    assert not problems, "\n".join(problems)


def test_the_read_allowlists_keep_out_the_partitions_no_route_serves():
    """Non-vacuity: the scope actually excludes the families #5543 exists to protect, and a
    dropped family is caught by the reach check (the mutation, run in-process)."""
    private = ["PERSONA#elena", "NARRATIVE#arc", "SYSTEM#dlq-ledger", "SUBSCRIBE#x", "CACHE#x", "COACHSIM#x", "PULSE", "EVALRET#board_ask"]
    for constant in ("SITE_API_READ_PARTITIONS", "SITE_API_AI_READ_PARTITIONS", "PROGRESS_VIEWER_READ_PARTITIONS"):
        patterns = _read_partitions(constant)
        assert "*" not in patterns and not any(p in ("USER#*", "USER#matthew*") for p in patterns), f"{constant} is a whole-table grant"
        leaked = [k for k in private if any(fnmatch(k, p) for p in patterns)]
        assert not leaked, f"{constant} grants {leaked} — no public route reads these"
    # Mutation: drop COACH#* from the site-api list and the reach check must name a coach partition.
    reached = _reached_partitions("web.site_api_lambda")
    mutated = [p for p in _read_partitions("SITE_API_READ_PARTITIONS") if p != "COACH#*"]
    assert any(k.startswith("COACH#") for k in _uncovered(reached, mutated)), "dropping COACH#* went unnoticed — the reach check is blind"
