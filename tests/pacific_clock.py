"""tests/pacific_clock.py — freeze the PACIFIC clock a module actually calls (#2811).

WHY THIS EXISTS. The repo's frozen-clock idiom is
``monkeypatch.setattr(mod, "datetime", _FrozenDatetime)`` — it pins the ``datetime``
name *in that module's namespace*, which is exactly right for `datetime.now(...)` and
exactly useless for `pacific_today()`: that function lives in `common.pacific_time` and
reads ITS OWN `datetime`, which the patch never reaches. `latest_readings.py`'s
docstring already records the shape ("monkeypatching that module's `datetime` cannot
reach a second module's own import"), measured as 0 days against a 14-day-old weigh-in.

#2811 moved the fleet's day derivations onto `pacific_today()` / `pacific_now()`, so
every suite that pins a clock must pin THOSE names too, in the same module namespace,
derived from the SAME instant — otherwise the frozen test drifts against the real wall
clock and the suite goes non-deterministic (green all day, red after 5pm PT).

Use it right beside the existing patch:

    monkeypatch.setattr(mod, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, mod, _FrozenDatetime)
"""

from datetime import datetime, timezone

from common.pacific_time import PACIFIC

_NAMES = ("pacific_now", "pacific_today")


def pacific_instant(frozen) -> datetime:
    """The Pacific-frame instant a frozen clock represents.

    ``frozen`` may be the `_FrozenDatetime` CLASS the suite patched in (read through
    its own ``now()``, so the helper never needs to know the suite's constant name) or
    a plain datetime. A tz-less value is read as UTC — `parse_iso_utc`'s semantic, the
    one this repo already committed to (#1964).
    """
    instant = frozen.now(timezone.utc) if isinstance(frozen, type) else frozen
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(PACIFIC)


def freeze_pacific(monkeypatch, module, frozen) -> datetime:
    """Pin ``module``'s `pacific_now`/`pacific_today` to ``frozen``'s Pacific instant.

    Only names the module actually imported are patched — a module that uses one and
    not the other is normal, and `raising=False` would hide a typo, so `hasattr` gates
    it instead. Returns the pinned Pacific instant so a caller can assert against it.
    """
    pt = pacific_instant(frozen)
    for name in _NAMES:
        if hasattr(module, name):
            monkeypatch.setattr(module, name, (lambda: pt) if name == "pacific_now" else (lambda: pt.strftime("%Y-%m-%d")))
    return pt
