"""tests/bundle_stubs.py — stub a bundled module that now lives inside a package (#1653).

Before the packaging move, shared modules sat flat at the bundle root, so a test could
swap one out with a single line::

    monkeypatch.setitem(sys.modules, "bedrock_client", fake)

and any `import bedrock_client` under test would pick up the fake, because a top-level
import is a plain sys.modules lookup.

That is no longer true once the module lives at ``lambdas/ai/bedrock_client.py`` and the
code under test says ``from ai import bedrock_client``. CPython's ``_handle_fromlist``
first checks whether the PARENT package already has the submodule bound as an attribute
— which it does, as soon as anything in the same interpreter has imported it for real —
and returns that attribute without ever consulting ``sys.modules["ai.bedrock_client"]``.

The failure mode is nasty precisely because it is order-dependent: run the test file
alone and the stub works (nothing imported the real module yet, so the attribute is
absent and the sys.modules entry wins); run the whole suite and an earlier test has
already bound the real submodule, the stub is silently ignored, and the "unit" test
quietly makes a live Bedrock call. That is exactly what happened during the #1653 ai/
slice — eight tests started issuing real InvokeModel calls that failed only because CI
has no credentials.

So: patch BOTH the sys.modules entry and the parent package attribute. monkeypatch
undoes both at teardown.
"""

import importlib
import sys


def stub_bundled_module(monkeypatch, dotted: str, stub) -> None:
    """Replace ``dotted`` (e.g. "ai.bedrock_client") with ``stub`` for one test.

    Patches the sys.modules entry AND the attribute on the parent package, so both
    ``import ai.bedrock_client`` and ``from ai import bedrock_client`` resolve to the
    stub regardless of what the rest of the suite has already imported.
    """
    if "." not in dotted:
        monkeypatch.setitem(sys.modules, dotted, stub)
        return

    pkg_name, _, attr = dotted.rpartition(".")
    monkeypatch.setitem(sys.modules, dotted, stub)

    # Import the parent so there is a real package object to patch. If the parent
    # genuinely does not exist, the sys.modules entry above is still the correct
    # (and only possible) stub, so this stays non-fatal.
    try:
        pkg = importlib.import_module(pkg_name)
    except ImportError:
        return
    monkeypatch.setattr(pkg, attr, stub, raising=False)
