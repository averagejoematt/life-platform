"""The ONE loader for the plan root (``user_goals``): a public part and a private part (owner ruling 2026-11-11, item 2).

WHY TWO PARTS. The repo is public. ``config/user_goals.json`` holds ONLY the fields ``goals_field_privacy`` classifies
public-safe; every other field (the private set, and anything the review does not name — fail closed) lives in a
private document that is never tracked:

  * runtime (Lambda): S3 ``config/private/user_goals_private.json`` — bucket-root ``config/`` is not public (no bucket
    policy grant, no CloudFront origin path), and the key has no repo twin, so ``config_twin_sync`` never writes it;
  * local dev: the file named by ``$LIFE_PLATFORM_GOALS_PRIVATE_PATH``, else ``~/.config/life-platform/
    user_goals_private.json`` — off-repo by construction.

THE CONTRACT.
  * ``load_public`` — the tracked public part (repo file when present, else the S3 twin ``config/user_goals.json``).
    A public surface or a generator of public text reads THIS, never the merged view.
  * ``load_goals`` — public deep-merged with private, for coach context only. The private part fails SOFT to absent:
    no default is ever invented that could pass for the owner's own words; a consumer that needs a private field
    sees it missing and omits what it would have said.
  * ``split`` — the classifier-driven partition the tracked file is held to (``tests/test_user_goals_split.py``).

Logs name exception TYPES only — never a key's content.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any, Optional

from common import goals_field_privacy as _gfp

logger = logging.getLogger(__name__)

PUBLIC_KEY = "config/user_goals.json"
PRIVATE_KEY = "config/private/user_goals_private.json"
PRIVATE_PATH_ENV = "LIFE_PLATFORM_GOALS_PRIVATE_PATH"
DEFAULT_PRIVATE_PATH = os.path.join("~", ".config", "life-platform", "user_goals_private.json")


def _bucket(bucket: Optional[str]) -> str:
    return bucket or os.environ.get("S3_BUCKET", "matthew-life-platform")


def _s3(s3_client: Any) -> Any:
    if s3_client is not None:
        return s3_client
    import boto3  # noqa: PLC0415 — lazy: keeps the module importable without boto3

    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))


def _in_lambda() -> bool:
    return bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def private_path() -> str:
    """The off-repo local private part's path (env override, else the per-user config dir)."""
    return os.path.expanduser(os.environ.get(PRIVATE_PATH_ENV) or DEFAULT_PRIVATE_PATH)


# ── the partition ────────────────────────────────────────────────────────────


def _leaf_classes(node: Any, path: str) -> set:
    """Every classification under ``node`` — a list of scalars is ONE leaf at the list's own path (as the review names it)."""
    if isinstance(node, dict):
        out: set = set()
        for k, v in node.items():
            out |= _leaf_classes(v, f"{path}.{k}" if path else k)
        return out or {_gfp.classify(path)}
    if isinstance(node, list) and node and all(isinstance(x, dict) for x in node):
        out = set()
        for i, v in enumerate(node):
            out |= _leaf_classes(v, f"{path}[{i}]")
        return out
    return {_gfp.classify(path)}


def split(doc: dict, _path: str = "") -> tuple:
    """``(public, private)`` — every leaf goes where ``goals_field_privacy.classify`` puts it (unnamed = private).

    A list whose items mix classes cannot be partitioned without re-indexing it, so it raises: that is a new field
    shape the review has to rule on, never something to guess."""
    pub: dict = {}
    priv: dict = {}
    for k, v in doc.items():
        path = f"{_path}.{k}" if _path else k
        if isinstance(v, dict) and v:
            p, q = split(v, path)
            if p:
                pub[k] = p
            if q:
                priv[k] = q
            continue
        classes = _leaf_classes(v, path)
        if classes == {_gfp.PUBLIC_SAFE}:
            pub[k] = copy.deepcopy(v)
        elif classes == {_gfp.PRIVATE}:
            priv[k] = copy.deepcopy(v)
        else:
            raise ValueError(f"goals field {path!r} mixes public-safe and private leaves; the privacy review must rule on it")
    return pub, priv


def merge(public: Optional[dict], private: Optional[dict]) -> dict:
    """Deep merge (dicts recurse). On a clash the PUBLIC value wins: a private document can add fields, never restate
    a published figure."""
    out = copy.deepcopy(public or {})
    for k, v in (private or {}).items():
        if k not in out:
            out[k] = copy.deepcopy(v)
        elif isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = merge(out[k], v)
    return out


def private_paths_in(doc: dict) -> list:
    """The private paths present in ``doc`` (PATHS only) — what must never be in the tracked file."""
    _pub, priv = split(doc)

    def _walk(o: Any, p: str) -> list:
        if isinstance(o, dict) and o:
            return [x for k, v in o.items() for x in _walk(v, f"{p}.{k}" if p else k)]
        return [p]

    return _walk(priv, "") if priv else []


# ── the reads ────────────────────────────────────────────────────────────────


def load_public(s3_client: Any = None, bucket: Optional[str] = None, *, prefer_repo: bool = True) -> Optional[dict]:
    """The public part: the repo file when present (scripts, tests, local runs), else the S3 twin. None on failure."""
    if prefer_repo:
        try:
            from common.repo_config import config_path  # noqa: PLC0415

            with open(config_path("user_goals.json"), encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001 — in Lambda config/ is not bundled: the S3 twin is the source
            pass
    try:
        body = _s3(s3_client).get_object(Bucket=_bucket(bucket), Key=PUBLIC_KEY)["Body"].read()
        return json.loads(body)
    except Exception as e:  # noqa: BLE001 — every caller already fails soft on a missing plan root
        logger.warning("[user_goals] public part unavailable: %s", type(e).__name__)
        return None


def load_private(s3_client: Any = None, bucket: Optional[str] = None) -> Optional[dict]:
    """The private part, or None (fail-soft: absent, never a stand-in).

    Order: the off-repo local file; else S3 — only when running in Lambda or when the caller handed an S3 client, so a
    local test or script never reaches for the live private object by accident."""
    path = private_path()
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            return doc if isinstance(doc, dict) else None
        except Exception as e:  # noqa: BLE001
            logger.warning("[user_goals] local private part unreadable: %s", type(e).__name__)
            return None
    if s3_client is None and not _in_lambda():
        return None
    try:
        body = _s3(s3_client).get_object(Bucket=_bucket(bucket), Key=PRIVATE_KEY)["Body"].read()
        doc = json.loads(body)
        return doc if isinstance(doc, dict) else None
    except Exception as e:  # noqa: BLE001 — coach context degrades to the public plan; it never fails a run
        logger.warning("[user_goals] private part unavailable (coach context uses the public plan only): %s", type(e).__name__)
        return None


def load_goals(s3_client: Any = None, bucket: Optional[str] = None, *, prefer_repo: bool = True) -> Optional[dict]:
    """The merged plan root for COACH CONTEXT (public + private). None only when the public part is unavailable."""
    pub = load_public(s3_client, bucket, prefer_repo=prefer_repo)
    if pub is None:
        return None
    return merge(pub, load_private(s3_client, bucket))
