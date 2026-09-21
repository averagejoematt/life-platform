"""census_probe.py — the bounded read budget the two nightly census legs share (#3615).

WHY THIS EXISTS SEPARATELY FROM EITHER LEG
  #3615 adds two walks to qa-smoke's ONE existing nightly invocation: the hook ×
  artifact liveness matrix and the week-narration agreement gate. Both fetch a handful
  of live surfaces, both must stay key-bounded, and both run inside a Lambda with a
  240s ceiling that already spends most of it on the checks that were there first.

  A per-leg fetch helper would have given each leg its own timeout, its own cache and
  its own idea of "too long", and the two legs read several of the SAME urls
  (`/api/journey` is a week-narrating surface AND the producer the rate-consumer rule
  grades). One budget, shared, means a url is fetched at most once per run and the two
  legs cannot collectively overrun the invocation.

THE DEFERRED VERDICT IS NOT A PASS AND NOT A FAIL
  When the wall-clock budget is spent, `get()` stops issuing requests and returns a
  `deferred` result. A deferred cell is reported as a WARN naming the budget — never as
  green (that would be a check that cannot fail, #2934's class) and never as a red (the
  artifact was not observed, so there is no evidence against it). The two legs are
  ordered so the cheapest, most load-bearing reads happen first.

Leaf module: stdlib only, no AWS, no imports from the operational package — so the
registries and both qa modules can depend on it without a cycle. Unit-tested directly
in tests/test_hook_registry_3615.py with an injected opener (no network).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

#: Per-request ceiling. Every probed surface is a static file or a cached read path;
#: the slowest observed (2026-09-21, from the repo host) was under 1.5s. Six seconds
#: is that with room for a cold CloudFront path, and small enough that a hung surface
#: costs one cell rather than the leg.
DEFAULT_TIMEOUT_SECONDS = 6.0

#: Wall-clock ceiling for ALL census fetching in one qa-smoke invocation. The sweep's
#: own Lambda timeout is 240s (cdk/stacks/operational_stack.py) and the pre-existing
#: checks own most of it, so the census gets a minute and reports what it could not
#: reach rather than taking the invocation down with it.
DEFAULT_BUDGET_SECONDS = 60.0

USER_AGENT = "life-platform-qa-smoke-census"


class Fetched:
    """One probe result. `deferred` means the budget was spent BEFORE the request."""

    __slots__ = ("url", "status", "body", "error", "deferred")

    def __init__(self, url: str, status: int = 0, body: str = "", error: str = "", deferred: bool = False):
        self.url = url
        self.status = status
        self.body = body
        self.error = error
        self.deferred = deferred

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error

    def json(self) -> Any:
        """Parsed body, or None when it is not JSON (never raises — a probe is not a parser)."""
        try:
            return json.loads(self.body)
        except Exception:  # noqa: BLE001 — a malformed body is a finding for the caller, not a crash
            return None

    def __repr__(self) -> str:  # pragma: no cover — diagnostics only
        return f"Fetched({self.url!r}, status={self.status}, deferred={self.deferred}, error={self.error!r})"


class ProbeBudget:
    """Cached, wall-clock-bounded GETs.

    `opener(url, timeout)` is the seam: production passes None (urllib), tests pass a
    function returning `(status, body)` or raising. Every url is fetched at most once
    per instance, so two legs naming the same surface cost one read.
    """

    def __init__(
        self,
        *,
        total_seconds: float = DEFAULT_BUDGET_SECONDS,
        per_request_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        opener: Optional[Callable[[str, float], tuple]] = None,
        clock: Optional[Callable[[], float]] = None,
    ):
        self.total_seconds = float(total_seconds)
        self.per_request_seconds = float(per_request_seconds)
        self._opener = opener
        self._clock = clock or time.monotonic
        self._started = self._clock()
        self._cache: dict[str, Fetched] = {}
        self.requests = 0
        self.deferred = 0

    @property
    def elapsed(self) -> float:
        return self._clock() - self._started

    @property
    def exhausted(self) -> bool:
        return self.elapsed >= self.total_seconds

    def get(self, url: str) -> Fetched:
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        if self.exhausted:
            self.deferred += 1
            # NOT cached: a deferred result is an absence of evidence, and caching it
            # would make a later (cheaper) run of the same url inherit the non-verdict.
            return Fetched(url, deferred=True, error=f"census read budget of {self.total_seconds:.0f}s spent")
        self.requests += 1
        try:
            status, body = self._open(url)
            result = Fetched(url, status=int(status), body=str(body))
        except Exception as exc:  # noqa: BLE001 — a probe never raises into the sweep
            result = Fetched(url, error=str(exc)[:160])
        self._cache[url] = result
        return result

    def _open(self, url: str) -> tuple:
        if self._opener is not None:
            return self._opener(url, self.per_request_seconds)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=self.per_request_seconds) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            # A 404/405 is DATA here, not an error: a door that answers "use POST" is
            # alive, and a door that answers 404 is the finding this census exists for.
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            return exc.code, body
