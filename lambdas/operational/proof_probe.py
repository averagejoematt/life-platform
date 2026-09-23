"""proof_probe.py — the `## Proof probe` grammar: how an instrument issue names the live read it closes on (#4022).

THE PROBLEM
  A `closure:live-proof` issue stays open until its first non-degraded live output
  (`scripts/closure_contract.py`, #3595). Every such issue already carries a dated
  "stays open on …" comment naming exactly what to read — a DDB key, an `/api/*` field,
  a CI job, a metric — and a human session re-reads each note, runs the read by hand and
  writes the `**Live proof:**` line. Sessions AP and AQ spent their turns on precisely this.
  This module makes that note machine-readable, so the nightly
  (`operational.closure_probe_qa`, riding qa-smoke) can do the read itself.

THE GRAMMAR (the whole of it — one section in the issue body)

    ## Proof probe
    - probe: api_field `/api/calibration` `platform.strata.weekly_prescriptions.n` >= 1
    - probe: qa_check `data:coach_ensemble_phase_stamp_coverage` non_degraded
    - expires: 2026-10-18
    - residual: not-work — every other box is met (comment 2026-09-23)

  One or more `probe:` lines (ALL must read true — AND semantics), exactly one `expires:`
  date (UTC; past it the probe stops being evaluated and becomes a needs-human line), and an
  optional `residual:` line copied into the closing comment — it must carry a home (`#N` or
  `not-work — …`), the closure contract's residual rule applied at filing time.

  probe line:  `probe: <kind> `<address>` [`<field path>`] <predicate> [<value>]`

  KINDS (PROBE_KINDS) — each is a read the qa-smoke nightly can make deterministically:
    api_field          address = a site path starting `/api/` (GET against the live site)
    ddb_key            address = `<pk> | <sk>` on the platform table (GetItem)
    s3_key             address = an object key in the platform bucket (the JSON body)
    ci_job             address = `<workflow file> :: <job name>` — the latest COMPLETED run
                       of that workflow on `main`; the observed value is the job's conclusion
    cloudwatch_metric  address = `<namespace> :: <metric> [:: Dim=Val,Dim=Val]`; the
                       observed value is the Maximum over the trailing 24 h
    qa_check           address = a qa-smoke check id (`Check.name`) from the SAME run; the
                       observed value is its status: ok | warn | fail | paused

  FIELD PATH — dotted keys, `[N]` indexes, `[*]` = ANY element (the predicate holds for at
  least one). Omitted = the whole document / value.

  PREDICATES — exists | equals <v> | >= <n> (also `≥`, `gte`) | non_degraded.
    `non_degraded` = observed, and not in DEGRADED_VALUES (so a qa_check `warn`, a ci_job
    `failure`, an `"unavailable"` status string are NOT a pass).

WHAT A READING IS
  evaluate() returns one of four verdicts, and ONLY `true` may close an issue:
    true      the predicate held on an observed value
    false     observed, predicate did not hold (the planted negative control)
    absent    the address/field is not there (404, missing key, null)
    degraded  the read itself failed or returned a degraded value — "could not look" is
              never a pass (ADR-104)

PRIVACY
  Issue bodies and comments are PUBLIC (the repo is public). A probe may name a private
  DDB/S3 address, so the closing comment renders the OBSERVED VALUE only for kinds whose
  value is already public (`PUBLIC_VALUE_KINDS`); for the rest it states which predicate held
  (`present`, `>= 1 held`), never the number. `equals` restates the probe's own (public) value.

Leaf module: stdlib only. Imported by `operational.closure_probe_qa` (the Lambda leg) and,
by file path, by `scripts/closure_contract.py` — the ONE parser; neither side re-types it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, List, Optional, Tuple

INSTRUMENT_LABEL = "closure:live-proof"  # == closure_contract.INSTRUMENT_LABEL (asserted by test)
SECTION_HEADING_RE = re.compile(r"^\s{0,3}##\s+Proof probe\s*$", re.I | re.M)
_NEXT_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S", re.M)

PROBE_KINDS = ("api_field", "ddb_key", "s3_key", "ci_job", "cloudwatch_metric", "qa_check")
PUBLIC_VALUE_KINDS = frozenset({"api_field", "ci_job", "cloudwatch_metric", "qa_check"})
PREDICATES = ("exists", "equals", "gte", "non_degraded")
_PREDICATE_ALIASES = {
    "exists": "exists",
    "equals": "equals",
    "==": "equals",
    ">=": "gte",
    "≥": "gte",
    "gte": "gte",
    "non_degraded": "non_degraded",
    "non-degraded": "non_degraded",
}
VALUE_PREDICATES = ("equals", "gte")

# A value that is PRESENT but says the thing it describes is not working. Lower-cased compare.
DEGRADED_VALUES = frozenset(
    {
        "",
        "degraded",
        "error",
        "errored",
        "fail",
        "failed",
        "failure",
        "warn",
        "warning",
        "paused",
        "unavailable",
        "unknown",
        "unevaluable",
        "stale",
        "timed_out",
        "cancelled",
        "skipped",
        "n/a",
        "none",
        "null",
        "false",
    }
)

VERDICT_TRUE, VERDICT_FALSE, VERDICT_ABSENT, VERDICT_DEGRADED = "true", "false", "absent", "degraded"
MAX_PROBES_PER_ISSUE = 5

_PROBE_LINE_RE = re.compile(
    r"^\s*[-*]\s*probe:\s*(?P<kind>[a-z_]+)\s+`(?P<address>[^`]+)`"
    r"(?:\s+`(?P<field>[^`]+)`)?"
    r"\s+(?P<pred>exists|equals|==|>=|≥|gte|non[_-]degraded)"
    r"(?:\s+(?:`(?P<vq>[^`]*)`|(?P<v>\S+)))?\s*$",
    re.I,
)
_EXPIRES_RE = re.compile(r"^\s*[-*]\s*expires:\s*(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\s*$", re.I)
_RESIDUAL_RE = re.compile(r"^\s*[-*]\s*residual:\s*(?P<text>.+?)\s*$", re.I)
_BULLET_KEY_RE = re.compile(r"^\s*[-*]\s*(?P<key>[a-z_]+):", re.I)
# A residual's home — the closure contract's own grammar (check_residual_queue.py, #1340):
# a carrier `#N`, or `not-work — <home>` (hyphen / en-dash / em-dash).
_RESIDUAL_HOME_RE = re.compile(r"#\d+|\bnot-work\s*[—–-]", re.I)
_PATH_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+|\*)\]")


@dataclass(frozen=True)
class Probe:
    kind: str
    address: str
    field_path: str
    predicate: str
    value: Optional[str]

    def describe(self) -> str:
        """The probe restated in its own grammar (what the closing comment quotes)."""
        s = f"{self.kind} `{self.address}`"
        if self.field_path:
            s += f" `{self.field_path}`"
        s += f" {self.predicate}"
        if self.value is not None:
            s += f" `{self.value}`"
        return s


@dataclass
class ProbeBlock:
    probes: List[Probe] = field(default_factory=list)
    expires: Optional[date] = None
    residual: Optional[str] = None
    errors: List[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return bool(self.probes) and self.expires is not None and not self.errors


def section_text(body: str) -> Optional[str]:
    """The `## Proof probe` section's text (heading excluded), or None when there is none."""
    m = SECTION_HEADING_RE.search(body or "")
    if not m:
        return None
    rest = (body or "")[m.end() :]
    nxt = _NEXT_HEADING_RE.search(rest)
    return rest[: nxt.start()] if nxt else rest


def parse_probe_line(line: str) -> Tuple[Optional[Probe], Optional[str]]:
    """(Probe, None) or (None, error) for one `- probe:` bullet."""
    m = _PROBE_LINE_RE.match(line or "")
    if not m:
        return None, f"unparseable probe line: {line.strip()[:120]!r}"
    kind = m.group("kind").lower()
    if kind not in PROBE_KINDS:
        return None, f"unknown probe kind {kind!r} (one of {', '.join(PROBE_KINDS)})"
    pred = _PREDICATE_ALIASES[m.group("pred").lower()]
    value = m.group("vq") if m.group("vq") is not None else m.group("v")
    if pred in VALUE_PREDICATES and value is None:
        return None, f"predicate {pred!r} needs a value"
    if pred not in VALUE_PREDICATES and value is not None:
        return None, f"predicate {pred!r} takes no value (got {value!r})"
    if pred == "gte" and _as_number(value) is None:
        return None, f"`>=` needs a numeric value (got {value!r})"
    address = m.group("address").strip()
    err = _address_error(kind, address)
    if err:
        return None, err
    field_path = (m.group("field") or "").strip()
    if field_path and not _split_path(field_path):
        return None, f"unparseable field path {field_path!r}"
    return Probe(kind, address, field_path, pred, value), None


def _address_error(kind: str, address: str) -> Optional[str]:
    if kind == "api_field" and not address.startswith("/api/"):
        return "api_field address must be a site path starting `/api/`"
    if kind == "ddb_key" and len([p for p in address.split("|") if p.strip()]) != 2:
        return "ddb_key address must be `<pk> | <sk>`"
    if kind == "ci_job" and len([p for p in address.split("::") if p.strip()]) != 2:
        return "ci_job address must be `<workflow file> :: <job name>`"
    if kind == "cloudwatch_metric" and len([p for p in address.split("::") if p.strip()]) not in (2, 3):
        return "cloudwatch_metric address must be `<namespace> :: <metric> [:: Dim=Val,…]`"
    if kind == "s3_key" and (address.startswith("/") or ".." in address):
        return "s3_key address must be a bucket-relative key"
    return None


def parse_block(body: str) -> Optional[ProbeBlock]:
    """The issue body's probe block, or None when it declares no `## Proof probe` section.

    A section that is present but malformed returns a block with `errors` — never None —
    so a caller can tell "declared nothing" from "declared something unreadable"."""
    text = section_text(body)
    if text is None:
        return None
    block = ProbeBlock()
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        km = _BULLET_KEY_RE.match(line)
        key = km.group("key").lower() if km else ""
        if key == "probe":
            probe, err = parse_probe_line(line)
            if err:
                block.errors.append(err)
            elif probe is not None:
                block.probes.append(probe)
        elif key == "expires":
            parsed = expires_from_line(line)
            if parsed is None:
                block.errors.append(f"unparseable expires line: {line.strip()[:80]!r}")
            elif block.expires is not None:
                block.errors.append("more than one `expires:` line")
            else:
                block.expires = parsed
        elif key == "residual":
            rm = _RESIDUAL_RE.match(line)
            text_ = rm.group("text") if rm else ""
            if not _RESIDUAL_HOME_RE.search(text_):
                block.errors.append("residual line names no home (`#N` or `not-work — <home>`)")
            else:
                block.residual = text_
    if not block.probes and not any("probe" in e for e in block.errors):
        block.errors.append("no `- probe:` line")
    if block.expires is None and not any("expires" in e for e in block.errors):
        block.errors.append("no `- expires: YYYY-MM-DD` line")
    if len(block.probes) > MAX_PROBES_PER_ISSUE:
        block.errors.append(f"more than {MAX_PROBES_PER_ISSUE} probes")
    return block


# ── the expiry grammar (shared: scripts/obligation_carriers.py reuses it, #3597) ────────
_DAY_LITERAL_RE = re.compile(r"^\s*(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\s*$")


def parse_day_literal(text: Any) -> Optional[date]:
    """A bare `YYYY-MM-DD` calendar-day literal (UTC) → date, else None.

    Built from its parts — no instant is parsed here — and an impossible day (`2026-02-30`)
    is None, never a clamp. The ONE day parser behind every `expires:` in the closure layer:
    this module's `## Proof probe` block and #3597's residue/obligation registries."""
    m = _DAY_LITERAL_RE.match(text) if isinstance(text, str) else None
    if not m:
        return None
    try:
        return date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
    except ValueError:
        return None


def expires_from_line(line: str) -> Optional[date]:
    """The date of one `- expires: YYYY-MM-DD` bullet, or None when the line is not one."""
    em = _EXPIRES_RE.match(line or "")
    return parse_day_literal(f"{em.group('y')}-{em.group('m')}-{em.group('d')}") if em else None


def is_past(expires: Optional[date], today: date) -> bool:
    """True once `today` is strictly after `expires` — the expiry day itself is still live."""
    return expires is not None and today > expires


def is_expired(block: ProbeBlock, today: date) -> bool:
    return is_past(block.expires, today)


# ── field paths ────────────────────────────────────────────────────────────────────────
def _split_path(path: str) -> List[str]:
    tokens: List[str] = []
    for part in path.split("."):
        if not part:
            return []
        pos = 0
        for m in _PATH_TOKEN_RE.finditer(part):
            if m.start() != pos:
                return []
            tokens.append(m.group(1) if m.group(1) is not None else f"[{m.group(2)}]")
            pos = m.end()
        if pos != len(part):
            return []
    return tokens


_MISSING = object()


def resolve(doc: Any, path: str) -> List[Any]:
    """Every value `path` selects in `doc` ([*] fans out). [] when nothing is there."""
    if not path:
        return [] if doc is None else [doc]
    current: List[Any] = [doc]
    for tok in _split_path(path):
        nxt: List[Any] = []
        for node in current:
            if tok == "[*]":
                if isinstance(node, list):
                    nxt.extend(node)
                elif isinstance(node, dict):
                    nxt.extend(node.values())
            elif tok.startswith("["):
                idx = int(tok[1:-1])
                if isinstance(node, list) and -len(node) <= idx < len(node):
                    nxt.append(node[idx])
            elif isinstance(node, dict) and tok in node:
                nxt.append(node[tok])
        current = nxt
    return [v for v in current if v is not None]


# ── the predicate ──────────────────────────────────────────────────────────────────────
def _as_number(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def is_degraded_value(v: Any) -> bool:
    if v is None or v is False:
        return True
    if isinstance(v, str):
        return v.strip().lower() in DEGRADED_VALUES
    if isinstance(v, dict):
        status = v.get("status") if "status" in v else v.get("state")
        return bool(v.get("degraded") is True or (isinstance(status, str) and status.strip().lower() in DEGRADED_VALUES))
    return False


def _holds(pred: str, v: Any, want: Optional[str]) -> bool:
    if pred == "exists":
        return True
    if pred == "non_degraded":
        return not is_degraded_value(v)
    if pred == "equals":
        if isinstance(v, bool):
            return str(v).lower() == str(want).strip().lower()
        nv, nw = _as_number(v), _as_number(want)
        if nv is not None and nw is not None:
            return nv == nw
        return str(v).strip() == str(want).strip()
    if pred == "gte":
        nv, nw = _as_number(v), _as_number(want)
        return nv is not None and nw is not None and nv >= nw
    return False


@dataclass(frozen=True)
class Reading:
    """What a reader observed at an address. `error` set ⇒ the read itself failed."""

    doc: Any = None
    found: bool = False
    error: str = ""
    note: str = ""  # a short provenance string the comment may carry (e.g. a CI run id)


@dataclass(frozen=True)
class Evaluation:
    probe: Probe
    verdict: str
    observed: Any
    reason: str


def evaluate(probe: Probe, reading: Reading) -> Evaluation:
    """Pure. One probe against one reading → a verdict. Only `true` may close."""
    if reading.error:
        return Evaluation(probe, VERDICT_DEGRADED, None, f"read failed: {reading.error}")
    if not reading.found:
        return Evaluation(probe, VERDICT_ABSENT, None, "address not present")
    values = resolve(reading.doc, probe.field_path)
    if not values:
        return Evaluation(probe, VERDICT_ABSENT, None, f"field {probe.field_path!r} absent or null")
    # A degraded document (e.g. an /api/ payload that says it is degraded) is never a pass,
    # whatever the field reads — the #3595 "first NON-DEGRADED live output" rule.
    if probe.field_path and is_degraded_value(reading.doc) and isinstance(reading.doc, dict):
        return Evaluation(probe, VERDICT_DEGRADED, None, "the document itself reports degraded")
    for v in values:
        if _holds(probe.predicate, v, probe.value):
            return Evaluation(probe, VERDICT_TRUE, v, "predicate held")
    if all(is_degraded_value(v) for v in values):
        return Evaluation(probe, VERDICT_DEGRADED, values[0], "only degraded values observed")
    return Evaluation(probe, VERDICT_FALSE, values[0], "predicate did not hold")


def block_verdict(evals: Iterable[Evaluation]) -> str:
    """AND over the block: true only when EVERY probe read true."""
    verdicts = [e.verdict for e in evals]
    if not verdicts:
        return VERDICT_ABSENT
    if all(v == VERDICT_TRUE for v in verdicts):
        return VERDICT_TRUE
    for v in (VERDICT_DEGRADED, VERDICT_ABSENT, VERDICT_FALSE):
        if v in verdicts:
            return v
    return VERDICT_FALSE


# ── the closing comment ────────────────────────────────────────────────────────────────
DEFAULT_RESIDUAL = (
    "not-work — the declared probe was this issue's remaining acceptance; anything it did not observe "
    "belongs on a new issue, not on this close"
)
LEG_NAME = "life-platform-qa-smoke `closure:proof_probes` leg (#4022)"


def render_observed(e: Evaluation) -> str:
    """The observed value as it may appear in a PUBLIC comment (see PRIVACY above)."""
    if e.probe.kind in PUBLIC_VALUE_KINDS:
        s = repr(e.observed) if isinstance(e.observed, str) else str(e.observed)
        return s if len(s) <= 120 else s[:117] + "…"
    if e.probe.predicate == "equals":
        return f"`{e.probe.value}`"
    if e.probe.predicate == "gte":
        return f"(value withheld — private address) >= {e.probe.value} held"
    return "(value withheld — private address) present" + (", non-degraded" if e.probe.predicate == "non_degraded" else "")


def closing_comment(evals: List[Evaluation], instant: datetime, residual: Optional[str] = None, notes: Optional[List[str]] = None) -> str:
    """The ADR-099 closing comment in the closure-contract shape, built from TRUE readings.

    `**Shipped:** / **Outcome:** realized / **Live proof:** <UTC instant> — <where> = <observed>`
    + a homed residual line — `scripts/closure_sweep.py::evaluate_issue` passes it by
    construction (tests/test_closure_proof_probe_4022.py grades it with the real sweep)."""
    stamp = instant.strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"**Shipped:** closed by the {LEG_NAME} — the probe this issue declared in its `## Proof probe` section read true.",
        f"**Outcome:** realized — every declared probe held on a live read ({len(evals)} of {len(evals)}).",
    ]
    for i, e in enumerate(evals):
        where = f"`{e.probe.address}`" + (f" `{e.probe.field_path}`" if e.probe.field_path else "")
        note = f" ({notes[i]})" if notes and i < len(notes) and notes[i] else ""
        lines.append(f"**Live proof:** {stamp} — {e.probe.kind} {where} = {render_observed(e)}{note}; probe: {e.probe.describe()}")
    lines.append(f"**Residual:** {residual or DEFAULT_RESIDUAL}")
    return "\n".join(lines)
