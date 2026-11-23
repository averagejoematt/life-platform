"""research/findings.py — the owner's research findings store (#6208, epic #6206, owner rulings 2026-11-22).

WHAT IT IS. One private record per research finding: the question, the verified sources it rests on, what
the evidence says and how strong it is, how far it applies to him, its limitations, its risk tier, the coach
responsible for it, a review-by date, and then an append-only history — state changes, sources added,
corrections, links to recommendations and experiments, his decisions in his own words, and personal results
copied from an experiment analysis. A finding can be traced to the recommendation or experiment it produced.

THIS MODULE IS THE REGISTRY: the vocabularies (states, event kinds, evidence strengths, risk tiers, source
kinds and designs), the row constructors, the validators, the fold that turns rows into one current view, and
the read helpers. Pure: no I/O except the explicit `read_rows` helper. The ONLY writer is the owner's MCP tool
`manage_research_finding` (`mcp/tools_research_findings.py`); `tests/test_research_findings_6208.py` holds that
by an AST sweep, and holds the publication boundary (no public-pipeline module can reach this one).

WHERE IT LIVES. Its own owner-only partition, on the charter's paved road for a new source:
    pk = USER#<user>#SOURCE#research_findings
    sk = FINDING#<finding_id>                                   the finding (written once, never rewritten)
    sk = FINDING#<finding_id>#EV#<recorded_at>#<kind>#<nnn>     one append-only event
`privacy.field_tiers.SOURCE_TIERS` (TIER_OWNER_ONLY) and `experiment.phase_taxonomy.SOURCE_CLASS` (CROSS_PHASE:
what he has read and decided outlives any cycle, exactly as the recommendation record does).

IDENTITY, NOT SUPPORT. A verified source means the identifier resolves to this record and the object came unedited
from the verifier. It does NOT show that the source supports the finding: that is the reader's own assertion
(`claim_supported_by`, `supports_note`).

THE RISK TRIPWIRE HAS KNOWN GAPS. `_TOUCH_WORDS` refuses a finding whose text names a drug, supplement, electrolyte
or intake term its declared `touches` do not cover. It is a tripwire, not a classifier: the owner's declared
`touches`, `risk_tier` and the required `risk_rationale` are the record, and a risk field can only be TIGHTENED by a
correction (a lower-risk reading is a new finding).

NO NETWORK HERE. A source arrives already verified: `scripts/research_finding_verify.py` resolves it on the
laptop (PubMed / Crossref through the exercise library's resolvers, or an allow-listed guideline page) and
prints the object this module accepts. A source without `resolved_title` and `verified_on` is refused.

The host / design / pubtype vocabularies below are COPIES of `config/evidence_source_allowlist.json` because
config/ is not staged in the Lambda bundle (`common.repo_config`). They are held EQUAL to that file by
`tests/test_research_findings_6208.py`, so the allowlist stays the one place a reviewed change is made.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from coach.persona_registry import CHAT_COACH_IDS, OPERATIONAL_COACH_IDS
from coach.recommendation_record import valid_rec_id  # read-only: the rec_id shape lives in the record's own registry
from common.pacific_time import parse_day_key

SOURCE = "research_findings"
HEAD_PREFIX = "FINDING#"
EVENT_INFIX = "#EV#"
RECORDED_BY_OWNER = "owner"

#: The coach responsible for a finding — a live persona id from the registry (a retired coach cannot own new work).
RESPONSIBLE_COACH_IDS: frozenset[str] = frozenset(OPERATIONAL_COACH_IDS) | frozenset(CHAT_COACH_IDS)

# ── states ─────────────────────────────────────────────────────────────────────────────────────
NEWLY_DISCOVERED = "newly_discovered"
UNDER_REVIEW = "under_review"
RELEVANT_NOT_ACTIONABLE = "relevant_not_actionable"
REJECTED = "rejected"
SUPERSEDED = "superseded"
DISCUSSED = "discussed"
APPROVED_FOR_EXPERIMENT = "approved_for_experiment"
DECLINED = "declined"
EXPERIMENT_IN_PROGRESS = "experiment_in_progress"
EVALUATED_SUPPORTED = "evaluated_supported"
EVALUATED_NOT_SUPPORTED = "evaluated_not_supported"
EVALUATED_INCONCLUSIVE = "evaluated_inconclusive"
OBSERVATION_PLANNED = "observation_planned"
OBSERVATION_RECORDED = "observation_recorded"
STATES: tuple[str, ...] = (
    NEWLY_DISCOVERED,
    UNDER_REVIEW,
    RELEVANT_NOT_ACTIONABLE,
    REJECTED,
    SUPERSEDED,
    DISCUSSED,
    APPROVED_FOR_EXPERIMENT,
    DECLINED,
    EXPERIMENT_IN_PROGRESS,
    EVALUATED_SUPPORTED,
    EVALUATED_NOT_SUPPORTED,
    EVALUATED_INCONCLUSIVE,
    OBSERVATION_PLANNED,
    OBSERVATION_RECORDED,
)
EVALUATED_STATES: frozenset[str] = frozenset({EVALUATED_SUPPORTED, EVALUATED_NOT_SUPPORTED, EVALUATED_INCONCLUSIVE})
_OPEN_REVIEW = (REJECTED, SUPERSEDED, DECLINED)
#: The lifecycle. Anything not listed is refused with the allowed next states named. Closed states are TERMINAL:
#: a changed view is a NEW finding (which may name the old id in its question or a source note). An approved
#: observational measurement goes through observation_planned, never approved_for_experiment.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    NEWLY_DISCOVERED: (UNDER_REVIEW, RELEVANT_NOT_ACTIONABLE, DISCUSSED, OBSERVATION_PLANNED, *_OPEN_REVIEW),
    UNDER_REVIEW: (RELEVANT_NOT_ACTIONABLE, DISCUSSED, APPROVED_FOR_EXPERIMENT, OBSERVATION_PLANNED, *_OPEN_REVIEW),
    RELEVANT_NOT_ACTIONABLE: (UNDER_REVIEW, DISCUSSED, OBSERVATION_PLANNED, *_OPEN_REVIEW),
    DISCUSSED: (UNDER_REVIEW, RELEVANT_NOT_ACTIONABLE, APPROVED_FOR_EXPERIMENT, OBSERVATION_PLANNED, *_OPEN_REVIEW),
    APPROVED_FOR_EXPERIMENT: (EXPERIMENT_IN_PROGRESS, DISCUSSED, DECLINED, SUPERSEDED),
    EXPERIMENT_IN_PROGRESS: (EVALUATED_SUPPORTED, EVALUATED_NOT_SUPPORTED, EVALUATED_INCONCLUSIVE, DECLINED, SUPERSEDED),
    OBSERVATION_PLANNED: (OBSERVATION_RECORDED, DISCUSSED, DECLINED, SUPERSEDED),
    OBSERVATION_RECORDED: (EVALUATED_SUPPORTED, EVALUATED_NOT_SUPPORTED, EVALUATED_INCONCLUSIVE, OBSERVATION_PLANNED, SUPERSEDED),
    REJECTED: (),
    SUPERSEDED: (),
    DECLINED: (),
    EVALUATED_SUPPORTED: (),
    EVALUATED_NOT_SUPPORTED: (),
    EVALUATED_INCONCLUSIVE: (),
}
#: Not live: a finding in one of these no longer blocks a new finding with the same dedupe key, owes no review,
#: and is never flagged stale.
CLOSED_STATES: frozenset[str] = frozenset(
    {REJECTED, SUPERSEDED, DECLINED, EVALUATED_SUPPORTED, EVALUATED_NOT_SUPPORTED, EVALUATED_INCONCLUSIVE}
)
REASON_REQUIRED_STATES: frozenset[str] = frozenset({REJECTED, DECLINED, SUPERSEDED})

# ── the evidence ───────────────────────────────────────────────────────────────────────────────
EVIDENCE_STRENGTHS: tuple[str, ...] = ("strong", "moderate", "weak", "insufficient")
POPULATION_MATCHES: tuple[str, ...] = ("direct", "partial", "poor")
ORIGINS: tuple[str, ...] = ("prospective", "retrospective", "simulated")
ORIGIN_SIMULATED = "simulated"

ID_KINDS: tuple[str, ...] = ("pmid", "doi", "guideline_url")
REVIEW_DEPTHS: tuple[str, ...] = ("abstract_only", "full_text")
FULL_TEXT = "full_text"
#: `config/evidence_source_allowlist.json` "designs" keys, plus a clinical guideline (a finding may rest on one).
DESIGNS: tuple[str, ...] = (
    "randomized_trial",
    "controlled_trial",
    "meta_analysis",
    "systematic_review",
    "narrative_review",
    "position_stand",
    "clinical_guideline",
)
#: Copies of the allowlist's lists (held equal by the test). A guideline URL must be on an official body's host.
GUIDELINE_HOSTS: tuple[str, ...] = ("nice.org.uk", "who.int", "heart.org", "ahajournals.org", "escardio.org", "acsm.org")
DENIED_HOSTS: tuple[str, ...] = (
    "twitter.com",
    "x.com",
    "instagram.com",
    "facebook.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "reddit.com",
    "threads.net",
    "linkedin.com",
    "medium.com",
    "substack.com",
    "blogspot.com",
    "wordpress.com",
    "tumblr.com",
    "patreon.com",
    "strongerbyscience.com",
    "t-nation.com",
)
REJECTED_PUBTYPES: tuple[str, ...] = (
    "Retracted Publication",
    "Retraction of Publication",
    "Published Erratum",
    "Comment",
    "Editorial",
    "Letter",
    "News",
    "Preprint",
)

# ── risk ───────────────────────────────────────────────────────────────────────────────────────
RISK_TIERS: dict[int, str] = {
    1: "observational",
    2: "reversible behavioural",
    3: "training or nutrition modification",
    4: "supplement or electrolyte",
    5: "medication or medical management",
}
#: What a finding touches, and the lowest risk tier that touch can carry. Declared, never inferred — but a
#: question or summary that names a supplement, an electrolyte or a medication must declare that touch.
TOUCH_MIN_TIER: dict[str, int] = {
    "observation": 1,
    "behaviour": 2,
    "sleep": 2,
    "training": 3,
    "intake_target": 3,
    "electrolytes": 4,
    "supplements": 4,
    "medication": 5,
}
TOUCHES: tuple[str, ...] = tuple(TOUCH_MIN_TIER)
#: At tier >= 3 a finding touching one of these needs clinical review before anything is tried.
CLINICAL_TOUCHES: frozenset[str] = frozenset({"intake_target", "electrolytes", "supplements", "medication"})
CLINICAL_REVIEW_TIER = 3
CLINICIAN_ONLY_TIER = 5
#: A TRIPWIRE with known gaps, not a classifier (see the module docstring). "dose-response" (a training term) is
#: deliberately not a medication word.
_TOUCH_WORDS: dict[str, re.Pattern] = {
    "supplements": re.compile(
        r"\bsupplement(?:s|ation|ing|ed)?\b|\bcreatine\b|\bvitamins?\b|\bfish[- ]oil\b|\bomega[- ]?3s?\b|\bmelatonin\b|"
        r"\bashwagandha\b|\bzinc\b",
        re.IGNORECASE,
    ),
    "electrolytes": re.compile(r"\belectrolytes?\b|\bsodium\b|\bpotassium\b|\bmagnesium\b|\bsalt(?:s|y|ed)?\b", re.IGNORECASE),
    "medication": re.compile(
        r"\bmedications?\b|\bprescri(?:be|bed|ption)s?\b|\bmetoprolol\b|\bbeta[- ]?blockers?\b|\bstatins?\b|\bnsaids?\b|"
        r"\bibuprofen\b|\banticoagul\w*|\bdos(?:e|es|age|ages)\b(?!-response)|\bdrugs?\b|\bmedicines?\b",
        re.IGNORECASE,
    ),
    "intake_target": re.compile(
        r"\bkcal\b|\bcalori\w*|\bfasting\b|\bprotein (?:target|floor)s?\b|\bcaffeine\b|\balcohol\b",
        re.IGNORECASE,
    ),
}

# ── events ─────────────────────────────────────────────────────────────────────────────────────
EVENT_STATE_CHANGE = "state_change"
EVENT_SOURCE_ADDED = "source_added"
EVENT_CORRECTION = "correction"
EVENT_LINK_RECOMMENDATION = "link_recommendation"
EVENT_LINK_EXPERIMENT = "link_experiment"
EVENT_DECISION = "decision"
EVENT_PERSONAL_RESULT = "personal_result"
EVENT_KINDS: tuple[str, ...] = (
    EVENT_STATE_CHANGE,
    EVENT_SOURCE_ADDED,
    EVENT_CORRECTION,
    EVENT_LINK_RECOMMENDATION,
    EVENT_LINK_EXPERIMENT,
    EVENT_DECISION,
    EVENT_PERSONAL_RESULT,
)
#: The experiment analysis's verdict vocabulary (`experiment.experiment_design`), copied as given.
PERSONAL_VERDICTS: tuple[str, ...] = ("supported", "contradicted", "inconclusive")
#: Head fields a correction event may restate. The id, dedupe key, origin and sources are not correctable:
#: sources grow by `source_added`, and a finding found to be about something else is superseded, not rewritten.
CORRECTABLE_FIELDS: tuple[str, ...] = (
    "question",
    "evidence_summary",
    "evidence_strength",
    "applicability",
    "limitations",
    "risk_tier",
    "touches",
    "clinical_review_required",
    "responsible_coach",
    "review_by",
    "risk_rationale",
)
#: Risk fields a correction may only TIGHTEN (raise the tier, add a touch, turn clinical review on).
RISK_FIELDS: frozenset[str] = frozenset({"risk_tier", "touches", "clinical_review_required"})
RATIONALE_MIN, RATIONALE_MAX = 20, 400
#: Whose words a `decide` event stores — generated wording is never stored as his speech.
WORDS_ARE: tuple[str, ...] = ("owner_verbatim", "owner_adopted_text", "session_summary")
#: What a `decide` event authorizes, when it authorizes a lifecycle step (nothing computes these automatically).
AUTHORIZES: tuple[str, ...] = ("observation", "verdict")
PROVENANCE_MIN, PROVENANCE_MAX = 5, 300
OBSERVATION_NOTE_MIN = 20

QUESTION_MIN, QUESTION_MAX = 20, 500
SUMMARY_MIN, SUMMARY_MAX = 20, 2000
TEXT_MAX = 1000
WORDS_MAX = 2000
REASON_MAX = 500
SURFACED_BY_MAX = 120
SOURCES_MIN, SOURCES_MAX = 1, 12
REVIEW_BY_MIN_DAYS, REVIEW_BY_MAX_DAYS = 1, 365

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FINDING_ID = re.compile(r"^rf_\d{8}_[0-9a-f]{8}$")
_DEDUPE_KEY = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_PMID = re.compile(r"^[1-9]\d{0,8}$")
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
_EXPERIMENT_ID = re.compile(r"^[a-z0-9-]{1,40}_\d{4}-\d{2}-\d{2}$")  # mcp/tools_lifestyle create_experiment: <slug>_<start>
_URL = re.compile(r"https?://([^/\s\"'<>]+)", re.IGNORECASE)
_SOURCE_KEYS = frozenset(
    {
        "id_kind",
        "id",
        "design",
        "review_depth",
        "resolved_title",
        "verified_on",
        "pubtypes",
        "claim_supported_by",
        "supports_note",
        "verification",
    }
)
#: How the recorder says the source supports the finding — asserted by a reader, never implied by a resolving id.
CLAIM_SUPPORT: tuple[str, ...] = ("abstract_read", "full_text_read")
SUPPORTS_NOTE_MIN, SUPPORTS_NOTE_MAX = 20, 400
#: The resolvers `scripts/research_finding_verify.py` fetches from, named in its verification block.
RESOLVERS: tuple[str, ...] = ("pubmed", "crossref", "guideline_page")
_VERIFICATION_KEYS = frozenset(
    {
        "resolver",
        "resolved_title",
        "first_author",
        "year",
        "fetched_at",
        "abstract_sha256",
        "stamp",
        "subject_overlap",
    }
)
_STAMP = re.compile(r"^[0-9a-f]{16}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class FindingError(ValueError):
    """A finding or event the ruling forbids — refused at write, never stored."""


# ── keys, ids, dates ───────────────────────────────────────────────────────────────────────────


def pk(user_id: str) -> str:
    return f"USER#{user_id}#SOURCE#{SOURCE}"


def finding_id_for(day: str, dedupe_key: str) -> str:
    return f"rf_{day.replace('-', '')}_{hashlib.sha256(dedupe_key.encode('utf-8')).hexdigest()[:8]}"


def valid_finding_id(finding_id: Any) -> bool:
    return bool(_FINDING_ID.match(str(finding_id or "")))


def valid_experiment_id(experiment_id: Any) -> bool:
    return bool(_EXPERIMENT_ID.match(str(experiment_id or "")))


def head_sk(finding_id: str) -> str:
    return f"{HEAD_PREFIX}{finding_id}"


def event_sk(finding_id: str, recorded_at: str, kind: str, revision: int = 1) -> str:
    return f"{HEAD_PREFIX}{finding_id}{EVENT_INFIX}{recorded_at}#{kind}#{revision:03d}"


def next_instant(previous: list[str], now: Optional[str] = None) -> str:
    """A recorded_at strictly after every earlier event of the finding. Events are replayed in sort-key order, so two acts
    in the same millisecond must not sort by their kind's name (a correction would replay before the source it needs)."""
    at = now or now_instant()
    latest = max((p for p in previous if _INSTANT.match(str(p or ""))), default="")
    if at > latest:
        return at
    bumped = datetime.strptime(latest[:23] + "000", "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc) + timedelta(milliseconds=1)
    return bumped.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def utc_today() -> str:
    """The UTC day — the frame `verified_on` is written in (the verifier stamps `fetched_at` in UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def now_instant() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _day(value: Any, name: str) -> str:
    v = str(value or "").strip()
    if not _DAY.match(v) or parse_day_key(v) is None:
        raise FindingError(f"{name} must be a real YYYY-MM-DD day")
    return v


def _days_between(a: str, b: str) -> int:
    return (parse_day_key(b) - parse_day_key(a)).days


def _text(value: Any, name: str, lo: int, hi: int) -> str:
    t = str(value or "").strip()
    if len(t) < lo or len(t) > hi:
        raise FindingError(f"{name} must be {lo}-{hi} characters")
    return t


# ── sources ────────────────────────────────────────────────────────────────────────────────────


def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _denied_hosts_in(*texts: Any) -> list[str]:
    hosts = []
    for t in texts:
        for h in _URL.findall(str(t or "")):
            h = h.lower().split(":")[0]
            if _host_matches(h, DENIED_HOSTS):
                hosts.append(h)
    return hosts


def source_key(src: dict[str, Any]) -> str:
    return f"{src.get('id_kind')}:{src.get('id')}"


def verification_stamp(id_kind: str, ident: str, resolved_title: str, fetched_at: str) -> str:
    """The stamp `scripts/research_finding_verify.py` writes and this module recomputes. It proves the four fields
    came unedited from the script's own fetch — it does NOT mean the Lambda verified anything (the Lambda makes no
    network call). A title typed or edited by hand after the fact no longer matches its stamp and is refused."""
    return hashlib.sha256(f"{id_kind}|{ident}|{resolved_title}|{fetched_at}".encode("utf-8")).hexdigest()[:16]


def _verification(v: Any, kind: str, ident: str, title: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise FindingError(
            f"source {kind}:{ident} has no verification block — run scripts/research_finding_verify.py and paste what it prints"
        )
    extra = sorted(set(v) - _VERIFICATION_KEYS)
    if extra:
        raise FindingError(f"unknown verification fields {extra}")
    if v.get("resolver") not in RESOLVERS:
        raise FindingError(f"verification.resolver must be one of {list(RESOLVERS)}")
    fetched_at = str(v.get("fetched_at") or "")
    if not _INSTANT.match(fetched_at):
        raise FindingError("verification.fetched_at must be a UTC instant (YYYY-MM-DDTHH:MM:SSZ)")
    if v.get("resolved_title") != title:
        raise FindingError("the source's resolved_title is not the title the verifier fetched — it was edited after verification")
    if not _STAMP.match(str(v.get("stamp") or "")) or v["stamp"] != verification_stamp(kind, ident, title, fetched_at):
        raise FindingError(
            f"source {kind}:{ident}: the verification stamp does not match its id, title and fetch time — the object was edited "
            "after scripts/research_finding_verify.py printed it (re-run the script)"
        )
    if v.get("abstract_sha256") is not None and not _SHA256.match(str(v["abstract_sha256"])):
        raise FindingError("verification.abstract_sha256 must be a sha256 hex digest")
    year = v.get("year")
    if year is not None and (not isinstance(year, int) or isinstance(year, bool)):
        raise FindingError("verification.year must be an integer or null")
    overlap = v.get("subject_overlap")
    if overlap is not None and not isinstance(overlap, dict):
        raise FindingError("verification.subject_overlap must be an object")  # ADVISORY: its `low` flag never refuses
    out = {k: v[k] for k in sorted(_VERIFICATION_KEYS) if k in v and v[k] is not None}
    out["first_author"] = str(v.get("first_author") or "")
    return out


def validate_source(src: Any, *, today: str) -> dict[str, Any]:
    """One verified source, normalized. Refused, with the reason, unless it is identified, verified and allow-listed."""
    if not isinstance(src, dict):
        raise FindingError("a source must be an object (run scripts/research_finding_verify.py and paste what it prints)")
    extra = sorted(set(src) - _SOURCE_KEYS)
    if extra:
        raise FindingError(f"unknown source fields {extra}; a source carries {sorted(_SOURCE_KEYS)}")
    kind = src.get("id_kind")
    if kind not in ID_KINDS:
        raise FindingError(f"source id_kind must be one of {list(ID_KINDS)}")
    ident = str(src.get("id") or "").strip()
    if kind == "pmid" and not _PMID.match(ident):
        raise FindingError(f"PMID {ident!r} is malformed")
    if kind == "doi":
        ident = ident.lower()
        if not _DOI.match(ident):
            raise FindingError(f"DOI {ident!r} is malformed (10.<registrant>/<suffix>)")
    if kind == "guideline_url":
        parsed = urllib.parse.urlparse(ident)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host:
            raise FindingError("a guideline_url must be an https URL")
        if _host_matches(host, DENIED_HOSTS):
            raise FindingError(f"source host {host} is social media / a blog — never a source")
        if not _host_matches(host, GUIDELINE_HOSTS):
            raise FindingError(f"guideline host {host} is not an allow-listed official body ({', '.join(GUIDELINE_HOSTS)})")
    if src.get("design") not in DESIGNS:
        raise FindingError(f"source design must be one of {list(DESIGNS)}")
    if src.get("review_depth") not in REVIEW_DEPTHS:
        raise FindingError(f"source review_depth must be one of {list(REVIEW_DEPTHS)}")
    title = str(src.get("resolved_title") or "")
    if not title.strip() or not str(src.get("verified_on") or "").strip():
        raise FindingError(
            f"source {kind}:{ident} is unverified — it needs resolved_title and verified_on from scripts/research_finding_verify.py"
        )
    if title != " ".join(title.split()) or len(title) > TEXT_MAX:
        raise FindingError("resolved_title must be exactly as the verifier printed it (single-spaced, at most 1000 characters)")
    verified_on = _day(src.get("verified_on"), "source verified_on")
    if verified_on > today:
        raise FindingError("source verified_on cannot be in the future")
    verification = _verification(src.get("verification"), kind, ident, title)
    if verification["fetched_at"][:10] != verified_on:
        raise FindingError("verified_on must be the day of verification.fetched_at")
    supported_by = src.get("claim_supported_by")
    if supported_by not in CLAIM_SUPPORT:
        raise FindingError(f"claim_supported_by must be one of {list(CLAIM_SUPPORT)} — say how you know the source supports the finding")
    if supported_by == "full_text_read" and src.get("review_depth") != FULL_TEXT:
        raise FindingError("claim_supported_by full_text_read needs review_depth full_text")
    note = _text(src.get("supports_note"), "supports_note", SUPPORTS_NOTE_MIN, SUPPORTS_NOTE_MAX)
    pubtypes = src.get("pubtypes") or []
    if not isinstance(pubtypes, list):
        raise FindingError("source pubtypes must be a list")
    bad = sorted(set(map(str, pubtypes)) & set(REJECTED_PUBTYPES))
    if bad:
        raise FindingError(f"source {kind}:{ident} is a rejected publication type: {', '.join(bad)}")
    denied = _denied_hosts_in(ident, title, note)
    if denied:
        raise FindingError(f"source names a denied host: {', '.join(sorted(set(denied)))}")
    out: dict[str, Any] = {
        "id_kind": kind,
        "id": ident,
        "design": src["design"],
        "review_depth": src["review_depth"],
        "resolved_title": title,
        "verified_on": verified_on,
        "claim_supported_by": supported_by,
        "supports_note": note,
        "verification": verification,
    }
    if pubtypes:
        out["pubtypes"] = [str(p) for p in pubtypes]
    return out


# ── the cross-field rules (run on a head, and again on the view a correction would produce) ────────


def check_rules(f: dict[str, Any], sources: list[dict[str, Any]]) -> None:
    """Rules 1 and 3: strong evidence needs a full text read; the risk tier, touches and clinical review agree."""
    strength = f.get("evidence_strength")
    if strength not in EVIDENCE_STRENGTHS:
        raise FindingError(f"evidence_strength must be one of {list(EVIDENCE_STRENGTHS)}")
    if strength == "strong" and not any(s.get("review_depth") == FULL_TEXT for s in sources):
        raise FindingError(
            "evidence_strength 'strong' needs at least one source read in full_text — an abstract cannot back strong evidence"
        )
    tier = f.get("risk_tier")
    if not isinstance(tier, int) or isinstance(tier, bool) or tier not in RISK_TIERS:
        raise FindingError("risk_tier must be an integer 1-5: " + "; ".join(f"{k} {v}" for k, v in RISK_TIERS.items()))
    touches = f.get("touches")
    if not isinstance(touches, list) or not touches or any(t not in TOUCH_MIN_TIER for t in touches):
        raise FindingError(f"touches must be a non-empty list drawn from {list(TOUCHES)}")
    text = (
        " ".join(str(f.get(k) or "") for k in ("question", "evidence_summary"))
        + " "
        + str((f.get("applicability") or {}).get("text") or "")
    )
    for touch, pattern in _TOUCH_WORDS.items():
        m = pattern.search(text)
        if m and touch not in touches:
            raise FindingError(f"the finding names {m.group(0)!r} — declare '{touch}' in touches")
    floor = max(TOUCH_MIN_TIER[t] for t in touches)
    if tier < floor:
        raise FindingError(f"risk_tier {tier} is below what it touches: {sorted(touches)} needs tier >= {floor} ({RISK_TIERS[floor]})")
    clinical = f.get("clinical_review_required")
    if not isinstance(clinical, bool):
        raise FindingError("clinical_review_required must be true or false")
    if not clinical and (tier > CLINICAL_REVIEW_TIER or (tier == CLINICAL_REVIEW_TIER and set(touches) & CLINICAL_TOUCHES)):
        raise FindingError(
            "clinical_review_required must be true: a tier >= 3 finding touching an intake target, electrolytes, supplements "
            "or medication needs clinical review"
        )


def _applicability(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise FindingError("applicability must be {text, population_match}")
    match = value.get("population_match")
    if match not in POPULATION_MATCHES:
        raise FindingError(f"applicability.population_match must be one of {list(POPULATION_MATCHES)}")
    return {"text": _text(value.get("text"), "applicability.text", 1, TEXT_MAX), "population_match": match}


def _coach(value: Any) -> str:
    if value not in RESPONSIBLE_COACH_IDS:
        raise FindingError(f"responsible_coach must be a live persona id from the registry: {sorted(RESPONSIBLE_COACH_IDS)}")
    return str(value)


def _review_by(value: Any, day: str) -> str:
    rb = _day(value, "review_by")
    span = _days_between(day, rb)
    if not REVIEW_BY_MIN_DAYS <= span <= REVIEW_BY_MAX_DAYS:
        raise FindingError(f"review_by must fall {REVIEW_BY_MIN_DAYS}..{REVIEW_BY_MAX_DAYS} days after the finding's day")
    return rb


def _dedupe_key(value: Any) -> str:
    k = str(value or "").strip()
    if not 3 <= len(k) <= 80 or not _DEDUPE_KEY.match(k):
        raise FindingError("dedupe_key must be a lowercase slug, 3-80 characters (a-z, 0-9, '-' or '_')")
    return k


# ── row constructors (the ONLY ones; the owner tool is their only caller) ────────────────────────


def build_finding_head(
    *,
    user_id: str,
    question: Any,
    dedupe_key: Any,
    sources: Any,
    evidence_summary: Any,
    evidence_strength: Any,
    applicability: Any,
    limitations: Any,
    risk_tier: Any,
    touches: Any,
    clinical_review_required: Any,
    risk_rationale: Any,
    responsible_coach: Any,
    review_by: Any,
    origin: Any,
    surfaced_by: Any,
    day: Any,
    recorded_at: str,
    today: str,
    source_today: Optional[str] = None,
) -> dict[str, Any]:
    """One finding. Written once, never rewritten: everything later is an appended event.

    `today` is the Pacific day (the finding's own date); `source_today` is the UTC day a source's `verified_on` is
    compared with, because the verifier stamps `fetched_at` in UTC (an evening Pacific verification is tomorrow in UTC)."""
    d = _day(day, "date")
    if d > today:
        raise FindingError("a finding's date cannot be in the future")
    if origin not in ORIGINS:
        raise FindingError(f"origin must be one of {list(ORIGINS)} (simulated findings never appear in a default list)")
    if not isinstance(sources, list) or not SOURCES_MIN <= len(sources) <= SOURCES_MAX:
        raise FindingError(f"a finding needs {SOURCES_MIN}-{SOURCES_MAX} verified sources")
    srcs = [validate_source(s, today=max(today, source_today or today)) for s in sources]
    keys = [source_key(s) for s in srcs]
    if len(set(keys)) != len(keys):
        raise FindingError("a source is listed twice")
    key = _dedupe_key(dedupe_key)
    fields: dict[str, Any] = {
        "question": _text(question, "question", QUESTION_MIN, QUESTION_MAX),
        "evidence_summary": _text(evidence_summary, "evidence_summary", SUMMARY_MIN, SUMMARY_MAX),
        "evidence_strength": evidence_strength,
        "applicability": _applicability(applicability),
        "limitations": _text(limitations, "limitations", 1, TEXT_MAX),
        "risk_tier": risk_tier,
        "touches": list(touches) if isinstance(touches, list) else touches,
        "clinical_review_required": clinical_review_required,
        "risk_rationale": _text(risk_rationale, "risk_rationale (why this risk tier)", RATIONALE_MIN, RATIONALE_MAX),
        "responsible_coach": _coach(responsible_coach),
        "review_by": _review_by(review_by, d),
    }
    check_rules(fields, srcs)
    denied = _denied_hosts_in(fields["question"], fields["evidence_summary"], fields["limitations"], fields["applicability"]["text"])
    if denied:
        raise FindingError(f"the finding cites a denied host: {', '.join(sorted(set(denied)))}")
    fid = finding_id_for(d, key)
    return {
        "pk": pk(user_id),
        "sk": head_sk(fid),
        "record_type": "research_finding",
        "finding_id": fid,
        "dedupe_key": key,
        **fields,
        "sources": srcs,
        "origin": origin,
        "surfaced_by": _text(surfaced_by, "surfaced_by", 1, SURFACED_BY_MAX),
        "day": d,
        "recorded_at": recorded_at,
        "recorded_by": RECORDED_BY_OWNER,
    }


def refuse_live_duplicate(views: list[dict[str, Any]], dedupe_key: str, *, simulated: bool) -> None:
    """Rule 2: a live finding with the same dedupe key blocks a new one, and the refusal names it and its coach.
    A simulated finding blocks only another simulated one — a rehearsal never stands in the way of the real record."""
    for v in views:
        if v.get("dedupe_key") == dedupe_key and v.get("live") and bool(v.get("simulated")) == simulated:
            raise FindingError(
                f"a live finding already answers this dedupe_key: {v['finding_id']} (state {v['state']}, responsible coach "
                f"{v.get('responsible_coach')}) — add a source or a correction to it, or close it first"
            )


def build_finding_event(
    *,
    user_id: str,
    view: dict[str, Any],
    kind: str,
    recorded_at: str,
    today: str,
    revision: int = 1,
    source_today: Optional[str] = None,
    **fields: Any,
) -> dict[str, Any]:
    """One append-only event on an existing finding, checked against its current (folded) view. `fold` replays every
    stored event through this same function, so a row that would be refused here is never applied."""
    if kind not in EVENT_KINDS:
        raise FindingError(f"event kind must be one of {list(EVENT_KINDS)}")
    fid = view.get("finding_id")
    if not valid_finding_id(fid):
        raise FindingError("the finding view is malformed")
    row: dict[str, Any] = {
        "pk": pk(user_id),
        "sk": event_sk(fid, recorded_at, kind, revision),
        "record_type": "research_finding_event",
        "finding_id": fid,
        "kind": kind,
        "recorded_at": recorded_at,
        "recorded_by": RECORDED_BY_OWNER,
    }
    if kind == EVENT_DECISION:
        _decision(row, fields)
        return row
    words = " ".join(str(fields.get("words") or "").split())[:WORDS_MAX]
    if words:
        row["words"] = words
    if kind == EVENT_STATE_CHANGE:
        _state_change(row, view, fields, today)
    elif kind == EVENT_SOURCE_ADDED:
        src = validate_source(fields.get("source"), today=max(today, source_today or today))
        if source_key(src) in {source_key(s) for s in view.get("sources") or []}:
            raise FindingError(f"source {source_key(src)} is already on the finding")
        if len(view.get("sources") or []) >= SOURCES_MAX:
            raise FindingError(f"a finding carries at most {SOURCES_MAX} sources")
        row["source"] = src
    elif kind == EVENT_CORRECTION:
        _correction(row, view, fields)
    elif kind == EVENT_LINK_RECOMMENDATION:
        rid = str(fields.get("rec_id") or "")
        if not valid_rec_id(rid):
            raise FindingError("rec_id must be a recommendation-record id (rec_<YYYYMMDD>_<coach>_<hash>)")
        if rid in (view.get("recommendations") or []):
            raise FindingError(f"{rid} is already linked")
        row["rec_id"] = rid
    elif kind == EVENT_LINK_EXPERIMENT:
        eid = str(fields.get("experiment_id") or "")
        if not valid_experiment_id(eid):
            raise FindingError("experiment_id must be an experiment id (<slug>_<YYYY-MM-DD>)")
        if _tier_of(view) == CLINICIAN_ONLY_TIER:
            raise FindingError(_CLINICIAN_ONLY)
        if view.get("state") in (OBSERVATION_PLANNED, OBSERVATION_RECORDED):
            raise FindingError("an observation takes no experiment link — an experiment goes through approved_for_experiment")
        if eid in (view.get("experiments") or []):
            raise FindingError(f"{eid} is already linked")
        row["experiment_id"] = eid
    else:  # personal_result
        _personal_result(row, view, fields)
    return row


_CLINICIAN_ONLY = (
    "a tier-5 finding (medication or medical management) can never be approved for, run as or linked to an experiment "
    "here — that decision belongs to the treating clinician"
)


def _decision(row: dict[str, Any], fields: dict[str, Any]) -> None:
    words = str(fields.get("words") or "").strip()
    if not words:
        raise FindingError("a decision carries his words, verbatim")
    if len(words) > WORDS_MAX:
        raise FindingError(f"a decision is at most {WORDS_MAX} characters")
    if fields.get("words_are") not in WORDS_ARE:
        raise FindingError(
            f"words_are must be one of {list(WORDS_ARE)} — say whose words these are, so generated wording is never stored as his speech"
        )
    row["words"] = words  # stored exactly; `words_are` says whose they are
    row["words_are"] = fields["words_are"]
    row["provenance"] = _text(
        fields.get("provenance"), "provenance (where the decision was made, e.g. a dated ruling)", PROVENANCE_MIN, PROVENANCE_MAX
    )
    authorizes = fields.get("authorizes")
    if authorizes is not None:
        if authorizes not in AUTHORIZES:
            raise FindingError(f"authorizes must be one of {list(AUTHORIZES)}")
        row["authorizes"] = authorizes
    eligible = fields.get("publication_eligible")
    if eligible is not None:
        if not isinstance(eligible, bool):
            raise FindingError("publication_eligible must be true or false")
        row["publication_eligible"] = eligible  # his explicit ruling; only publishable() reads it


def _authorized_since(view: dict[str, Any], what: str) -> bool:
    """An owner decision authorizing `what`, recorded since the finding entered its current state."""
    since = str(view.get("state_changed_at") or "")
    return any(d.get("authorizes") == what and str(d.get("recorded_at") or "") >= since for d in view.get("decisions") or [])


def _state_change(row: dict[str, Any], view: dict[str, Any], fields: dict[str, Any], today: str) -> None:
    to = fields.get("state")
    frm = view.get("state") or NEWLY_DISCOVERED
    if to not in STATES:
        raise FindingError(f"state must be one of {list(STATES)}")
    if to == frm:
        raise FindingError(f"the finding is already {to}")
    allowed = TRANSITIONS.get(frm, ())
    if to not in allowed:
        if not allowed:
            raise FindingError(
                f"{frm} is terminal — a changed view is a NEW finding (it may name {view.get('finding_id')} as its predecessor)"
            )
        raise FindingError(f"{frm} -> {to} is not allowed; from {frm} the next states are: {', '.join(allowed)}")
    tier = _tier_of(view)
    if to in (APPROVED_FOR_EXPERIMENT, EXPERIMENT_IN_PROGRESS) and tier == CLINICIAN_ONLY_TIER:
        raise FindingError(_CLINICIAN_ONLY)
    if to == EXPERIMENT_IN_PROGRESS and not view.get("experiments"):
        raise FindingError("experiment_in_progress needs a linked experiment (action='link', link_kind='experiment') first")
    if to == OBSERVATION_PLANNED:
        if list(view.get("touches") or []) != ["observation"] or not isinstance(tier, int) or tier > 2:
            raise FindingError(
                "an observation is only for a finding whose touches are exactly ['observation'] at risk tier <= 2 — anything "
                "else goes through approved_for_experiment (or a clinician)"
            )
        if view.get("experiments"):
            raise FindingError("an observation takes no experiment link — this finding already has one")
        if not _authorized_since(view, "observation"):
            raise FindingError(
                "observation_planned needs his authorization first: a decide event with authorizes='observation' and its provenance"
            )
    if to == OBSERVATION_RECORDED:
        observed_on = _day(fields.get("observed_on"), "observed_on")
        if observed_on > today or observed_on < str(view.get("day") or ""):
            raise FindingError("observed_on must fall between the finding's date and today")
        row["observed_on"] = observed_on
        row["observation_note"] = _text(fields.get("observation_note"), "observation_note", OBSERVATION_NOTE_MIN, TEXT_MAX)
    if to in EVALUATED_STATES:
        if frm == EXPERIMENT_IN_PROGRESS:
            results = view.get("personal_results") or []
            usable = results if view.get("simulated") else [r for r in results if not r.get("simulated") and r.get("experiment_id")]
            if not usable:
                raise FindingError(
                    "an evaluation needs a real personal result copied from the linked experiment's analysis (a simulated "
                    "result counts only on a simulated finding)"
                )
        elif not _authorized_since(view, "verdict"):  # from observation_recorded: never computed, only his call
            raise FindingError("evaluating an observation needs his explicit decide event with authorizes='verdict' — nothing computes it")
    reason = " ".join(str(fields.get("reason") or "").split())
    if to in REASON_REQUIRED_STATES and not reason:
        raise FindingError(f"{to} needs a reason")
    if reason:
        row["reason"] = reason[:REASON_MAX]
    if to == SUPERSEDED:
        by = str(fields.get("superseded_by") or "").strip()
        if valid_finding_id(by):
            if by == view.get("finding_id"):
                raise FindingError("a finding cannot supersede itself")
        elif not _is_source_ref(by):
            raise FindingError(
                "superseded_by must be a finding id (rf_...) or a source reference (pmid:<id> | doi:<id> | guideline_url:<url>)"
            )
        row["superseded_by"] = by
    elif fields.get("superseded_by"):
        raise FindingError("superseded_by belongs to a change to superseded only")
    row["from_state"] = frm
    row["to_state"] = to


def _is_source_ref(ref: str) -> bool:
    kind, _, ident = ref.partition(":")
    if kind == "pmid":
        return bool(_PMID.match(ident))
    if kind == "doi":
        return bool(_DOI.match(ident.lower()))
    if kind == "guideline_url":
        host = (urllib.parse.urlparse(ident).hostname or "").lower()
        return ident.startswith("https://") and _host_matches(host, GUIDELINE_HOSTS)
    return False


_LOWER_RISK = "a correction can only tighten risk — a lower-risk reading needs a new finding"


def _tighten_only(field: str, value: Any, current: Any) -> None:
    if field == "risk_tier":
        if isinstance(value, int) and not isinstance(value, bool) and isinstance(current, int) and value < current:
            raise FindingError(f"risk_tier {current} -> {value}: {_LOWER_RISK}")
    elif field == "touches":
        if isinstance(value, list) and not set(current or []) <= set(value):
            raise FindingError(f"removing {sorted(set(current or []) - set(value))} from touches: {_LOWER_RISK}")
    elif field == "clinical_review_required":
        if current is True and value is not True:
            raise FindingError(f"clearing clinical_review_required: {_LOWER_RISK}")


def _correction(row: dict[str, Any], view: dict[str, Any], fields: dict[str, Any]) -> None:
    field = fields.get("field")
    if field not in CORRECTABLE_FIELDS:
        raise FindingError(f"a correction restates one of {list(CORRECTABLE_FIELDS)} (sources grow by add_source)")
    reason = " ".join(str(fields.get("reason") or "").split())
    if not reason:
        raise FindingError("a correction needs a reason")
    value = fields.get("value")
    if field == "question":
        value = _text(value, "question", QUESTION_MIN, QUESTION_MAX)
    elif field == "evidence_summary":
        value = _text(value, "evidence_summary", SUMMARY_MIN, SUMMARY_MAX)
    elif field == "limitations":
        value = _text(value, "limitations", 1, TEXT_MAX)
    elif field == "risk_rationale":
        value = _text(value, "risk_rationale", RATIONALE_MIN, RATIONALE_MAX)
    elif field == "applicability":
        value = _applicability(value)
    elif field == "responsible_coach":
        value = _coach(value)
    elif field == "review_by":
        value = _review_by(value, str(view.get("day")))
    elif field == "touches":
        value = list(value) if isinstance(value, list) else value
    if value == view.get(field):
        raise FindingError(f"{field} already says exactly that")
    if field in RISK_FIELDS:
        _tighten_only(field, value, view.get(field))
    after = {k: view.get(k) for k in CORRECTABLE_FIELDS}
    after[field] = value
    check_rules(after, list(view.get("sources") or []))
    row.update({"field": field, "value": value, "previous": view.get(field), "reason": reason[:REASON_MAX]})


def _personal_result(row: dict[str, Any], view: dict[str, Any], fields: dict[str, Any]) -> None:
    if "evidence_strength" in fields and fields["evidence_strength"] is not None:
        raise FindingError("a personal result never changes evidence_strength — his outcome does not rewrite the external evidence")
    verdict = fields.get("verdict")
    if verdict not in PERSONAL_VERDICTS:
        raise FindingError(f"verdict must be one of {list(PERSONAL_VERDICTS)}, copied from the experiment analysis")
    simulated = fields.get("simulated")
    if not isinstance(simulated, bool):
        raise FindingError("a personal result says explicitly whether it is simulated (true / false)")
    eid = str(fields.get("experiment_id") or "")
    if eid:
        if eid not in (view.get("experiments") or []):
            raise FindingError(f"experiment {eid!r} is not linked to this finding — link it first")
        row["experiment_id"] = eid
    elif not simulated:
        raise FindingError("a real personal result names the linked experiment whose analysis it copies")
    row["verdict"] = verdict
    row["simulated"] = simulated


# ── reads ─────────────────────────────────────────────────────────────────────────────────────


def _query_all(table, key_condition) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {"KeyConditionExpression": key_condition}
    rows: list[dict[str, Any]] = []
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return rows
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def read_rows(table, user_id: str, finding_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Every row of the partition, or of one finding (its head and its events)."""
    from boto3.dynamodb.conditions import Key

    prefix = head_sk(finding_id) if finding_id else HEAD_PREFIX
    return _query_all(table, Key("pk").eq(pk(user_id)) & Key("sk").begins_with(prefix))


_HISTORY_KEYS = (
    "kind",
    "recorded_at",
    "from_state",
    "to_state",
    "reason",
    "superseded_by",
    "observed_on",
    "observation_note",
    "field",
    "value",
    "previous",
    "source",
    "rec_id",
    "experiment_id",
    "words",
    "words_are",
    "provenance",
    "authorizes",
    "verdict",
    "simulated",
    "publication_eligible",
)
#: The stored fields of each event kind that `fold` hands back to `build_finding_event` when it replays a row.
_REPLAY_FIELDS: dict[str, tuple[str, ...]] = {
    EVENT_STATE_CHANGE: ("to_state", "reason", "superseded_by", "observed_on", "observation_note", "words"),
    EVENT_SOURCE_ADDED: ("source", "words"),
    EVENT_CORRECTION: ("field", "value", "reason", "words"),
    EVENT_LINK_RECOMMENDATION: ("rec_id", "words"),
    EVENT_LINK_EXPERIMENT: ("experiment_id", "words"),
    EVENT_DECISION: ("words", "words_are", "provenance", "authorizes", "publication_eligible"),
    EVENT_PERSONAL_RESULT: ("verdict", "simulated", "experiment_id", "words"),
}


def _tier_of(view: dict[str, Any]) -> Any:
    tier = view.get("risk_tier")
    if tier is not None and not isinstance(tier, bool) and str(tier).isdigit():
        return int(str(tier))
    return tier


def _plain(value: Any) -> Any:
    """DynamoDB hands numbers back as Decimal; the validators speak int/float."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if value.__class__.__name__ == "Decimal":
        return int(value) if value == int(value) else float(value)
    return value


def _replay(view: dict[str, Any], e: dict[str, Any]) -> dict[str, Any]:
    """Re-validate one stored event against the view it would apply to (raises FindingError when it would be refused)."""
    kind = e.get("kind")
    if kind not in _REPLAY_FIELDS:
        raise FindingError(f"unknown event kind {kind!r}")
    recorded_at = str(e.get("recorded_at") or "")
    if not _INSTANT.match(recorded_at):
        raise FindingError("an event without a UTC recorded_at")
    fields = {k: e[k] for k in _REPLAY_FIELDS[kind] if k in e}
    if "to_state" in fields:
        fields["state"] = fields.pop("to_state")
    day = recorded_at[:10]  # the UTC day it was written: what "today" was, give or take the Pacific offset
    return build_finding_event(user_id="_", view=view, kind=kind, recorded_at=recorded_at, today=day, source_today=day, **fields)


def _apply(view: dict[str, Any], row: dict[str, Any]) -> None:
    kind = row["kind"]
    if kind == EVENT_STATE_CHANGE:
        view["state"], view["state_reason"] = row["to_state"], row.get("reason")
        view["state_changed_at"] = row["recorded_at"]
        view["superseded_by"] = row.get("superseded_by") if row["to_state"] == SUPERSEDED else None
        if row["to_state"] == OBSERVATION_RECORDED:
            view["observations"].append({k: row[k] for k in ("observed_on", "observation_note", "recorded_at")})
    elif kind == EVENT_SOURCE_ADDED:
        view["sources"].append(row["source"])
    elif kind == EVENT_CORRECTION:
        view[row["field"]] = row["value"]
        view["corrections"].append({k: row[k] for k in ("field", "value", "previous", "reason", "recorded_at") if k in row})
    elif kind == EVENT_LINK_RECOMMENDATION:
        view["recommendations"].append(row["rec_id"])
    elif kind == EVENT_LINK_EXPERIMENT:
        view["experiments"].append(row["experiment_id"])
    elif kind == EVENT_DECISION:
        view["decisions"].append(
            {k: row[k] for k in ("words", "words_are", "provenance", "authorizes", "publication_eligible", "recorded_at") if k in row}
        )
        if isinstance(row.get("publication_eligible"), bool):
            view["publication_eligible"] = row["publication_eligible"]
    else:
        view["personal_results"].append({k: row[k] for k in ("verdict", "simulated", "experiment_id", "words", "recorded_at") if k in row})


def fold(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows -> one current view per finding, newest first. The head is never edited; every event is REPLAYED through
    `build_finding_event` against the view it would apply to, in recorded order. A row the rules would refuse (a forged
    or malformed row, a transition out of order) is never applied: it is counted in `invalid_events` instead."""
    heads: dict[str, dict[str, Any]] = {}
    events: dict[str, list[dict[str, Any]]] = {}
    for r in rows or []:
        fid = str(r.get("finding_id") or "")
        if not valid_finding_id(fid) or r.get("tombstone"):
            continue
        if r.get("record_type") == "research_finding" and r.get("sk") == head_sk(fid):
            heads[fid] = _plain(r)
        elif r.get("record_type") == "research_finding_event" and r.get("recorded_by") == RECORDED_BY_OWNER:
            events.setdefault(fid, []).append(_plain(r))
    views = []
    for fid, head in heads.items():
        evs = sorted(events.get(fid) or [], key=lambda e: str(e.get("sk")))
        view: dict[str, Any] = {
            k: head.get(k) for k in ("finding_id", "dedupe_key", "origin", "surfaced_by", "day", "recorded_at", *CORRECTABLE_FIELDS)
        }
        view["risk_tier"] = _tier_of(view)
        view["sources"] = list(head.get("sources") or [])
        view.update(
            {
                "state": NEWLY_DISCOVERED,
                "state_reason": None,
                "state_changed_at": head.get("recorded_at"),
                "superseded_by": None,
                "recommendations": [],
                "experiments": [],
                "decisions": [],
                "observations": [],
                "publication_eligible": None,
                "personal_results": [],
                "corrections": [],
                "simulated": head.get("origin") == ORIGIN_SIMULATED,
            }
        )
        applied, invalid = [], []
        for e in evs:
            try:
                row = _replay(view, e)
            except FindingError:
                invalid.append(str(e.get("sk")))
                continue
            _apply(view, row)
            applied.append(row)
        view["live"] = view["state"] not in CLOSED_STATES
        view["clinician_hold"] = view["risk_tier"] == CLINICIAN_ONLY_TIER and view["state"] in (
            APPROVED_FOR_EXPERIMENT,
            EXPERIMENT_IN_PROGRESS,
        )
        view["invalid_events"] = {"count": len(invalid), "sks": invalid}
        view["history"] = [{k: e[k] for k in _HISTORY_KEYS if k in e} for e in applied]
        views.append(view)
    views.sort(key=lambda v: (str(v.get("day")), str(v.get("finding_id"))), reverse=True)
    return views


ORIGIN_RETROSPECTIVE = "retrospective"


def publishable(view: dict[str, Any]) -> tuple[bool, list[str]]:
    """Whether a finding's ORIGIN could ever allow it out of the owner-only store, and why not.

    Nothing calls this yet — no publish path exists and the partition is owner-only. It is here so a future publish
    path has ONE function to call. It answers the origin question only (a caller still owes the privacy tier and
    every other gate): a missing origin and a simulated finding are never publishable; a retrospective one only after
    his explicit `publication_eligible=true` decision event."""
    origin = view.get("origin")
    reasons: list[str] = []
    if origin not in ORIGINS:
        reasons.append("origin is missing or unknown")
    elif origin == ORIGIN_SIMULATED:
        reasons.append("a simulated finding is a rehearsal and is never published")
    elif origin == ORIGIN_RETROSPECTIVE and view.get("publication_eligible") is not True:
        reasons.append("a retrospective finding needs an explicit publication_eligible decision from the owner")
    return (not reasons, reasons)


def is_stale(view: dict[str, Any], today: str) -> bool:
    """Rule 6: a live finding whose review_by has passed. A closed finding owes no review."""
    return bool(view.get("live")) and str(view.get("review_by") or "9999-12-31") < today


def list_view(
    views: list[dict[str, Any]], today: str, *, include_simulated: bool = False, state: Optional[str] = None
) -> list[dict[str, Any]]:
    """The list every reader gets by default: simulated findings and simulated personal results left out, each
    finding flagged `stale` when its review is overdue."""
    out = []
    for v in views:
        if v.get("simulated") and not include_simulated:
            continue
        if state and v.get("state") != state:
            continue
        item = dict(v)
        if not include_simulated:
            item["personal_results"] = [p for p in v.get("personal_results") or [] if not p.get("simulated")]
        item["stale"] = is_stale(v, today)
        out.append(item)
    return out
