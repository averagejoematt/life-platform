"""Deterministic meal grouper (Phase 1) — pure functions over a day's food_log.

System of record for the derived meal layer. Groups raw MacroFactor food entries
into the realistic meals they were eaten as, as a *derived projection* — raw is
never mutated (Invariant 1), every meal is `inferred` + `confidence` (Invariant 2),
and every entry lands in exactly one group so `sum(rollups) == raw totals`
(Invariant 3, conservation-of-food).

No I/O beyond reading config/food_vocabulary.json. No AWS, no model calls. The
LLM namer (Phase 2) only decorates residual novel clusters; it is not imported here.

Locked parameters (SPEC §13): GAP_MIN=15 · CONF_MIN=0.7.

Gap segmentation mirrors the algorithm in `get_glucose_meal_response`
(mcp/tools_cgm.py) exactly — span-from-meal-start, `> gap`. That inline copy
should be refactored to import `segment_by_time_gap` here in a follow-up so there
is a single source of truth (Session 2 / MCP touch — out of scope for Session 1).
"""

import hashlib
import json
import os

from meal_templates_seed import ALGO_VERSION, KNOWN_ANCHOR_SETS, get_seed_templates

GAP_MIN = 15
CONF_MIN = 0.7
MEAL_CALORIE_THRESHOLD = 400  # kcal — eating occasions below this are snacks (matches ingestion)

MACRO_FIELDS = ["calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugars_g"]

NON_MEAL_ROLES = {"beverage", "supplement"}
SNACKISH_ROLES = {"snack_core", "fruit", "nut_seed", "treat", "veg", "fat", "dairy", "base"}
# Classes that stay STANDALONE snacks even when co-timestamped with a meal — unless the
# token is a listed modifier of a matched template (e.g. cool_whip belongs to the dessert).
PEELABLE_ROLES = {"snack_core", "beverage", "treat", "supplement"}
BASE_CAN_ANCHOR = {"oats"}


# ── vocabulary ───────────────────────────────────────────────────────────────
def _vocab_candidates():
    """Search order for food_vocabulary.json. In the bundled lambdas/ tree the file is
    staged alongside this module; locally it lives in repo config/."""
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.environ.get("FOOD_VOCAB_PATH"),
        os.path.join(here, "food_vocabulary.json"),  # layer: alongside the module
        os.path.join(os.path.dirname(here), "config", "food_vocabulary.json"),  # repo: ../config
    ]


_VOCAB_CACHE = None


def load_vocab(path=None):
    """Load and cache the canonical food vocabulary, searching layer + repo paths."""
    global _VOCAB_CACHE
    if path is None and _VOCAB_CACHE is not None:
        return _VOCAB_CACHE
    candidates = [path] if path else _vocab_candidates()
    for cand in candidates:
        if cand and os.path.exists(cand):
            with open(cand) as fh:
                v = json.load(fh)
            if path is None:
                _VOCAB_CACHE = v
            return v
    raise FileNotFoundError(f"food_vocabulary.json not found in any of: {[c for c in candidates if c]}")


def canonicalize_name(name, vocab):
    """Raw food name → canonical token. Exact alias first, then substring rules, then slug."""
    if not name:
        return "unknown"
    raw = name.strip()
    aliases = vocab.get("aliases", {})
    if raw in aliases:
        return aliases[raw]
    low = raw.lower()
    for sub, tok in vocab.get("substring_rules", []):
        if sub in low:
            return tok
    # slug fallback — deterministic, keeps the entry conserved even if unknown
    import re

    s = re.sub(r"\(.*?\)", " ", low)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    stop = {"raw", "cooked", "fresh", "the", "with", "and", "or"}
    toks = [t for t in s.split() if t and t not in stop]
    return "_".join(toks[:2]) if toks else "unknown"


def role_of(token, vocab):
    return vocab.get("tokens", {}).get(token, {}).get("role", "other")


def normalize(entries, vocab=None):
    """Annotate each entry with its canonical token + role. Pure: returns NEW dicts,
    never mutates the input (no-mutation invariant — the grouper emits zero writes
    to the raw source)."""
    vocab = vocab or load_vocab()
    out = []
    for idx, e in enumerate(entries):
        tok = canonicalize_name(e.get("food_name"), vocab)
        out.append(
            {
                "idx": idx,
                "food_name": e.get("food_name"),
                "time": e.get("time"),
                "token": tok,
                "role": role_of(tok, vocab),
                "macros": {f: _num(e.get(f)) for f in MACRO_FIELDS},
            }
        )
    return out


def _num(v):
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


# ── segmentation ─────────────────────────────────────────────────────────────
def _t2min(time_str):
    try:
        p = str(time_str).split(":")
        return int(p[0]) * 60 + int(p[1])
    except (ValueError, IndexError, AttributeError):
        return None


def segment_by_time_gap(norm_entries, gap=GAP_MIN):
    """Split entries into clusters by time gap. Mirrors get_glucose_meal_response:
    a new cluster starts when an entry is more than `gap` minutes after the current
    cluster's START (span-from-start, not gap-from-previous). Entries with no parseable
    time sort last into their own trailing cluster (kept — never dropped)."""
    timed, untimed = [], []
    for e in norm_entries:
        m = _t2min(e.get("time"))
        (timed if m is not None else untimed).append((m, e))
    timed.sort(key=lambda x: (x[0], x[1]["idx"]))

    clusters, cur, start = [], [], None
    for m, e in timed:
        if start is None or (m - start) > gap:
            if cur:
                clusters.append(cur)
            cur = [e]
            start = m
        else:
            cur.append(e)
    if cur:
        clusters.append(cur)
    if untimed:
        clusters.append([e for _, e in untimed])
    return clusters


def segment(norm_entries, vocab=None, gap=GAP_MIN):
    """Primary segmenter. Phase 0 confirmed MacroFactor carries NO meal bucket, so
    this is time-gap only; if a bucket is ever added it becomes the primary split
    and the gap demotes to refinement (SPEC §3)."""
    return segment_by_time_gap(norm_entries, gap=gap)


# ── core / template logic ────────────────────────────────────────────────────
def _anchor_heads_template(anchor, templates):
    return any(len(aset) == 1 and aset[0] == anchor for tpl in templates for aset in tpl["anchors"])


def detect_cores(cluster, templates):
    """Count distinct anchor-SETS (cores) in a cluster. Collapses KNOWN_ANCHOR_SETS
    (chicken+salmon = one core), applies template `absorbs` (yogurt bowl absorbs eggs),
    and separates orphan anchors (an anchor with no seeded template → attaches as a
    side, never its own meal). Returns (cores: list[set], orphan_anchors: set)."""
    anchors = {e["token"] for e in cluster if e["role"] == "anchor"}
    # a base may anchor a bowl only if no protein anchor present
    if not anchors:
        anchors = {e["token"] for e in cluster if e["token"] in BASE_CAN_ANCHOR}

    remaining = set(anchors)
    cores = []

    # 1. collapse known multi-protein dishes into one core
    for kset in KNOWN_ANCHOR_SETS:
        if kset <= remaining:
            cores.append(set(kset))
            remaining -= kset

    # 2. absorption: a core template can fold listed anchors into itself as members
    for tpl in templates:
        for aset in tpl["anchors"]:
            if set(aset) <= remaining:
                for ab in tpl.get("absorbs", []):
                    if ab in remaining and ab not in set(aset):
                        remaining.discard(ab)

    # 3. remaining anchors that head a template are cores; the rest are orphans
    orphans = set()
    for a in sorted(remaining):
        if _anchor_heads_template(a, templates):
            cores.append({a})
        else:
            orphans.add(a)
    return cores, orphans


def match_template(anchor_set, member_entries, templates):
    """Select the best template (anchor-required gate + key-modifier specificity gate),
    then score CONFIDENCE as coverage: the fraction of the cluster — by items AND by
    calories — explained by the template's anchor + modifier tokens (not mere anchor
    presence). A meal whose dominant mass is unseeded/unexplained (e.g. eggs as a minor
    anchor under a tuna+mayo lunch, or a lone grilled chicken + nuggets) scores low and
    falls to `uncategorized`. Returns the best match dict or None."""
    anchor_set = set(anchor_set)
    member_tokens = {e["token"] for e in member_entries}
    candidates = []
    for tpl in templates:
        matched = None
        for aset in tpl["anchors"]:
            if set(aset) <= anchor_set and (matched is None or len(aset) > len(matched)):
                matched = set(aset)
        if matched is None:
            continue
        keys = set(tpl.get("key_modifiers") or [])
        key_hit = bool(keys & member_tokens)
        if keys and not key_hit:
            continue  # specificity gate (e.g. Katsu needs panko/curry)
        overlap = len(set(tpl["modifiers"]) & member_tokens)
        if overlap < tpl["match_rule"].get("min_modifier_overlap", 0):
            continue
        specificity = len(matched) * 100 + (50 if key_hit else 0) + overlap
        candidates.append((specificity, tpl["template_id"], tpl, matched, overlap))
    if not candidates:
        return None
    # selection: most specific wins; deterministic tiebreak on template_id
    candidates.sort(key=lambda c: (-c[0], c[1]))
    _spec, _tid, tpl, matched, overlap = candidates[0]

    # ── coverage-based confidence: fraction of the cluster explained (items + calories) ──
    tpl_tokens = {t for aset in tpl["anchors"] for t in aset} | set(tpl["modifiers"])
    n = len(member_entries)
    item_frac = (sum(1 for e in member_entries if e["token"] in tpl_tokens) / n) if n else 0.0
    total_kcal = sum(e["macros"]["calories_kcal"] for e in member_entries)
    expl_kcal = sum(e["macros"]["calories_kcal"] for e in member_entries if e["token"] in tpl_tokens)
    kcal_frac = (expl_kcal / total_kcal) if total_kcal > 0 else item_frac
    confidence = round((item_frac + kcal_frac) / 2.0, 3)
    return {"template": tpl, "confidence": confidence, "anchor_set": matched, "modifier_overlap": overlap, "coverage": confidence}


def _template_modifier_union(anchor_set, templates):
    mods = set()
    for tpl in templates:
        if any(set(aset) <= set(anchor_set) for aset in tpl["anchors"]):
            mods |= set(tpl["modifiers"])
    return mods


def classify_singleton(cluster, vocab=None):
    """Snack vs whole-meal for an anchorless cluster — by kcal + composite-name, NOT
    item count (SPEC §7). Returns 'snack' or 'uncategorized'."""
    kcal = sum(e["macros"]["calories_kcal"] for e in cluster)
    meal_tokens = [e for e in cluster if e["role"] not in NON_MEAL_ROLES]
    if not meal_tokens:
        return "snack"  # beverage/supplement only
    if kcal < MEAL_CALORIE_THRESHOLD:
        return "snack"
    if all(e["role"] in SNACKISH_ROLES for e in meal_tokens):
        return "snack"
    return "uncategorized"  # high-kcal anchorless cluster → Phase-2 LLM territory


# ── orchestration ────────────────────────────────────────────────────────────
def _signature(member_entries):
    toks = sorted(e["token"] for e in member_entries)
    # Non-cryptographic: sha1 is only a short, stable grouping signature for meal
    # dedup (not security). usedforsecurity=False documents that and satisfies S324.
    h = hashlib.sha1("|".join(toks).encode(), usedforsecurity=False).hexdigest()[:12]
    return f"{'+'.join(toks)}#{h}" if toks else f"empty#{h}"


def _rollup(member_entries):
    r = {f: 0.0 for f in MACRO_FIELDS}
    for e in member_entries:
        for f in MACRO_FIELDS:
            r[f] += e["macros"][f]
    return {f: round(v, 4) for f, v in r.items()}


def _time_window(member_entries):
    times = [e["time"] for e in member_entries if e.get("time")]
    times_sorted = sorted(times) if times else []
    return {"start": times_sorted[0] if times_sorted else None, "end": times_sorted[-1] if times_sorted else None}


def _emit(method, name, template_id, confidence, kind, members, sides):
    all_for_sig = members + sides
    g = {
        "method": method,
        "meal_name": name,
        "template_id": template_id,
        "inferred": True,
        "confidence": round(confidence, 3),
        "kind": kind,  # "meal" | "snack" | "uncategorized"
        "signature": _signature(all_for_sig),
        "time_window": _time_window(all_for_sig),
        "member_refs": [{"idx": e["idx"], "food_name": e["food_name"], "time": e["time"], "token": e["token"]} for e in members],
        "sides": [{"idx": e["idx"], "food_name": e["food_name"], "time": e["time"], "token": e["token"], "attached": True} for e in sides],
        "rollup": _rollup(all_for_sig),
        "algo_version": ALGO_VERSION,
    }
    return g


def _singleton_group(entries, vocab):
    """Emit one snack/uncategorized group for an anchorless or peeled set of entries."""
    kind = classify_singleton(entries, vocab)
    name = "Snack" if kind == "snack" else "Uncategorized"
    if kind == "snack" and len({e["token"] for e in entries}) == 1:
        disp = vocab.get("tokens", {}).get(entries[0]["token"], {}).get("display")
        name = disp or name
    conf = 0.0 if kind == "uncategorized" else 0.6
    return _emit("singleton", name, None, conf, kind, entries, [])


def _group_cluster(cluster, templates, vocab):
    cores, orphans = detect_cores(cluster, templates)

    # ── no core → snack or uncategorized singleton for the whole cluster ──
    if not cores:
        return [_singleton_group(cluster, vocab)]

    # ── peel snack/beverage/treat/supplement entries that aren't a listed modifier of
    #    any core's template — they stay standalone snacks, not folded into the meal ──
    allowed_mods = set()
    for aset in cores:
        allowed_mods |= _template_modifier_union(aset, templates)
    peeled = [e for e in cluster if e["role"] in PEELABLE_ROLES and e["token"] not in allowed_mods]
    peeled_idx = {e["idx"] for e in peeled}
    meal_cluster = [e for e in cluster if e["idx"] not in peeled_idx]

    # ── assign every remaining entry to exactly one core ──
    # core descriptor: {anchor_set, members:[entries], sides:[entries], coverage:int}
    core_descs = []
    cluster_mod_tokens = {e["token"] for e in meal_cluster if e["role"] != "anchor" and e["role"] not in NON_MEAL_ROLES}
    for aset in cores:
        anchor_members = [e for e in meal_cluster if e["token"] in aset and e["role"] == "anchor"]
        cov = len(_template_modifier_union(aset, templates) & cluster_mod_tokens)
        core_descs.append({"anchor_set": set(aset), "members": list(anchor_members), "sides": [], "coverage": cov})

    # deterministic dominance order: higher coverage, then higher anchor kcal, then token
    def _kcal(d):
        return sum(e["macros"]["calories_kcal"] for e in d["members"])

    def dominant():
        return sorted(core_descs, key=lambda d: (d["coverage"], _kcal(d), sorted(d["anchor_set"])), reverse=True)[0]

    assigned_idx = {e["idx"] for d in core_descs for e in d["members"]}

    def core_lists_token(d, tok):
        return tok in _template_modifier_union(d["anchor_set"], templates)

    for e in meal_cluster:
        if e["idx"] in assigned_idx:
            continue
        # orphan anchor → side of the nearest core (shared word stem, else dominant)
        if e["role"] == "anchor" and e["token"] in orphans:
            words = set(e["token"].split("_"))
            sharing = [d for d in core_descs if words & {w for a in d["anchor_set"] for w in a.split("_")}]
            target = max(sharing, key=lambda d: (d["coverage"], _kcal(d))) if sharing else dominant()
            target["sides"].append(e)
            assigned_idx.add(e["idx"])
            continue
        # modifier / other → core whose template lists it (highest coverage), else dominant
        cands = [d for d in core_descs if core_lists_token(d, e["token"])]
        target = sorted(cands, key=lambda d: (d["coverage"], _kcal(d), sorted(d["anchor_set"])), reverse=True)[0] if cands else dominant()
        target["members"].append(e)
        assigned_idx.add(e["idx"])

    multi = len(core_descs) > 1
    groups = []
    for d in core_descs:
        m = match_template(d["anchor_set"], d["members"] + d["sides"], templates)
        if m and m["confidence"] >= CONF_MIN:
            method = "content_split+template" if multi else "template"
            groups.append(
                _emit(method, m["template"]["name"], m["template"]["template_id"], m["confidence"], "meal", d["members"], d["sides"])
            )
        else:
            conf = m["confidence"] if m else 0.0
            groups.append(_emit("uncategorized", "Uncategorized", None, conf, "uncategorized", d["members"], d["sides"]))

    # ── peeled snacks ride alongside the meal(s), counted (conservation) ──
    if peeled:
        groups.append(_singleton_group(peeled, vocab))
    return groups


def group_day(entries, vocab=None, templates=None):
    """Orchestrate: normalize → segment → per-cluster core split/match → conserve.
    Returns a list of group dicts (meals, snacks, uncategorized). Deterministic:
    identical input → identical output. Emits ZERO writes (pure)."""
    vocab = vocab or load_vocab()
    templates = templates if templates is not None else get_seed_templates()
    norm = normalize(entries, vocab)
    groups = []
    for cluster in segment(norm, vocab):
        groups.extend(_group_cluster(cluster, templates, vocab))
    raw_totals = _rollup(norm)
    assert_conservation(groups, raw_totals)
    return groups


def assert_conservation(groups, raw_totals, tol=0.01):
    """Conservation-of-food (Invariant 3): every raw entry lands in exactly one group;
    sum(group rollups) == raw daily totals to within `tol`. Raises on mismatch."""
    summed = {f: 0.0 for f in MACRO_FIELDS}
    for g in groups:
        for f in MACRO_FIELDS:
            summed[f] += g["rollup"][f]
    for f in MACRO_FIELDS:
        if abs(summed[f] - raw_totals.get(f, 0.0)) > tol:
            raise ValueError(
                f"Conservation violated for {f}: grouped={summed[f]:.4f} raw={raw_totals.get(f, 0.0):.4f} "
                f"(diff {summed[f] - raw_totals.get(f, 0.0):.4f} > tol {tol})"
            )
    return True
