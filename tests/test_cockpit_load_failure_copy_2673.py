"""#2673 — a failed cockpit request must not read as "hasn't computed yet".

When a cockpit API call failed, `/cockpit/` rendered the empty state whose copy is
for *no data has been produced yet*:

    "Today's score hasn't computed yet — the numbers refresh each morning."

That sentence claims knowledge of the backend's state that a failed request cannot
have. Two different truths — nothing exists yet, vs. the request failed — were
rendered as one sentence, on the page the subject returns to daily. The sibling
doors already get this right (`evidence.js`: "couldn't load its data just now").
Laundering an outage into a computed-zero state is what ADR-104 forbids.

The fix tags TRANSPORT failures (`err.transport`) in `getJSON` — both the `!res.ok`
branch and a network-level throw — and the empty state picks its sentence from that
flag.

Style follows tests/test_cockpit_carry_scope_guards.py: extract the SHIPPED source
and run it under node, so this exercises real code rather than a paraphrase of it.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COCKPIT_JS = os.path.join(_ROOT, "site", "assets", "js", "cockpit.js")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def _shipped_get_json() -> str:
    """The real `async function getJSON(...)` block, lifted from the shipped file."""
    src = open(_COCKPIT_JS, encoding="utf-8").read()
    m = re.search(r"^async function getJSON\(path\) \{.*?^\}", src, re.S | re.M)
    assert m, "getJSON not found in cockpit.js — the extraction, not the site, is broken"
    return m.group(0)


def _run(js: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.mjs")
        with open(p, "w", encoding="utf-8") as f:
            f.write(js)
        out = subprocess.run(["node", p], capture_output=True, text=True, timeout=30)  # nosec B603/B607
        assert out.returncode == 0, f"node failed: {out.stderr}\n{out.stdout}"
        return json.loads(out.stdout.strip().splitlines()[-1])


def test_an_http_failure_is_tagged_as_transport():
    """A 5xx must be distinguishable from an empty-but-successful payload."""
    js = f"""
globalThis.fetch = async () => ({{ ok: false, status: 503, json: async () => ({{}}) }});
{_shipped_get_json()}
let tagged = null;
try {{ await getJSON("/api/character"); }} catch (e) {{ tagged = !!e.transport; }}
console.log(JSON.stringify({{ tagged }}));
"""
    assert _run(js)["tagged"] is True, "a 503 was not tagged as a transport failure (#2673)"


def test_a_network_level_throw_is_tagged_as_transport():
    """Offline / DNS / CORS also fail the request — never 'no data yet'."""
    js = f"""
globalThis.fetch = async () => {{ throw new TypeError("Failed to fetch"); }};
{_shipped_get_json()}
let tagged = null;
try {{ await getJSON("/api/character"); }} catch (e) {{ tagged = !!e.transport; }}
console.log(JSON.stringify({{ tagged }}));
"""
    assert _run(js)["tagged"] is True, "a network-level throw was not tagged as transport (#2673)"


def test_an_empty_but_successful_payload_is_not_a_transport_failure():
    """The other half of the contract. Without this, tagging everything would pass."""
    js = f"""
globalThis.fetch = async () => ({{ ok: true, status: 200, json: async () => ({{}}) }});
{_shipped_get_json()}
let threw = false, body = null;
try {{ body = await getJSON("/api/character"); }} catch (e) {{ threw = true; }}
console.log(JSON.stringify({{ threw, empty: JSON.stringify(body) === "{{}}" }}));
"""
    r = _run(js)
    assert r["threw"] is False and r["empty"] is True, "a successful empty payload must not raise"


def _verdict_block() -> str:
    src = open(_COCKPIT_JS, encoding="utf-8").read()
    m = re.search(r'bind\("verdict"\)\.innerHTML = preC\n.*?"Today\'s score hasn\'t computed yet[^;]*;', src, re.S)
    assert m, "the verdict empty-state expression moved — update this extraction"
    return m.group(0)


def test_the_two_states_render_different_copy():
    """The actual reader-facing contract: a load failure and a not-yet-computed
    state must not produce the same sentence."""
    block = _verdict_block()
    # Drive the SHIPPED expression with each error shape, via a tiny bind() shim.
    js = f"""
const out = {{}};
function render(e, preC) {{
  const bind = () => ({{ set innerHTML(v) {{ out.copy = v; }} }});
  {block}
  return out.copy;
}}
const failed = render({{ transport: true }}, null);
const empty  = render(new Error("no sheet"), null);
console.log(JSON.stringify({{ failed, empty }}));
"""
    r = _run(js)
    assert r["failed"] != r["empty"], f"both states render identical copy: {r['failed']!r}"
    assert "hasn't computed yet" in r["empty"], r["empty"]
    assert "hasn't computed yet" not in r["failed"], f"a failed request still claims the score wasn't computed: {r['failed']!r}"
    assert "couldn't load" in r["failed"], r["failed"]
