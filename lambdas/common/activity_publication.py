"""Publication policy for ACTIVITY — whether, when and how often a source or habit was used (owner ruling 2026-11-03).

THE RULING. "Treat journal activity and journal-derived metadata as private by default, including
structured data ... This applies to future journal-related fields too, not just these exact
endpoints. Extend the structured source-aware publication policy rather than adding
endpoint-specific keyword filters ... Ensure public aggregates cannot indirectly reveal journal
activity through counts, denominators, percentages, trends or comparisons."

``common.narrative_provenance`` already decides which source FAMILIES are private for AI-written
text. This module extends the same registry to structured activity: a public serializer that emits
per-source activity, recency, sync status, presence, counts or any aggregate over sources asks
here first, and computes over PUBLIC sources only. There is one classification, not two:

  * a SOURCE (a ``SOURCE_REGISTRY`` key, an engagement channel, a status-board row) is classified by
    ``narrative_provenance.classify`` — ``notion`` (the journal) and every owner-only partition are
    PRIVATE there already. ``ACTIVITY_ONLY_SOURCES`` adds the handful of public activity sources the
    narrative registry has never needed to name (no narrative is stamped with them), each explicitly.
    A source in NEITHER is UNCLASSIFIED and is treated as private (fail closed);
    ``tests/test_journal_activity_privacy.py`` fails when a registry source, engagement channel or
    status-board row lands without a classification, so "fail closed" never silently hides a new
    public source either.
  * a HABIT is classified by IDENTITY — its Habitify id (``habit_statuses[name].habit_id``, present
    on every stored row) in ``HABIT_FAMILIES`` / ``PUBLIC_HABIT_IDS`` — or by the owner's own registry
    field (``PROFILE#v1.habit_registry[name].publication`` = "private" | "public"), never by matching
    words in its name. Morning Journal and Evening Journal are journal activity (``journal_presence``,
    PRIVATE, whatever any registry field says). Food Journal (food logging) and Whoop Journal
    (Whoop's daily behaviour check-in) are NOT the journal: public, by the owner's confirmation. A
    habit in neither table is UNCLASSIFIED and is not published until classified (fail closed).
  * a FIELD of a habit's stored status is classified too (``HABIT_STATUS_FIELDS``): a public habit is
    published through its completion, schedule and group only. Its free text (in-app notes), tap
    instant, progress values and former names are private; an unlisted field is private.

The owner's confirmation (2026-11-03): "New or unclassified sources and fields must remain private
until explicitly approved for publication ... private data should remain available to authorized
coaching and analysis systems without becoming eligible for public publication."

OMIT, NEVER MARK. A private source or habit is left out of the public payload entirely — no row,
no "withheld" placeholder, no count of withheld items. A per-item marker would be harmless only
while it carried nothing; omission cannot drift into carrying a date or a gap, and a constant
absence says nothing about activity. Every public total, denominator, percentage, trend, ranking and
"N of M" is computed over the public set, so no public number changes with private activity.

The stored rows are never changed: the owner's tools (MCP, coaches, the daily brief) read the table
directly and keep the full picture.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from common import narrative_provenance as NP

PUBLIC = NP.PUBLIC
PRIVATE = NP.PRIVATE

# Public activity sources the narrative registry does not name (no AI text is stamped with them).
# Each is already on a public surface by an earlier decision; listing them here records it.
ACTIVITY_ONLY_SOURCES: dict[str, str] = {
    "todoist": PUBLIC,  # task completions — the status board and the values channel of the fulfillment index
    "food_delivery": PUBLIC,  # the six-monthly delivery-index CSV (status board, paused)
    "macrofactor_workouts": PUBLIC,  # the MacroFactor workout CSV drop (status board)
    "dropbox": PUBLIC,  # the MacroFactor file-drop poller (registry facets only)
    "evening_ritual": PUBLIC,  # the one-tap connection rail (ADR-124) — the fulfillment index's baseline
    "interactions": PUBLIC,  # logged social interactions — counts only on public surfaces
    "youtube": PUBLIC,  # outbound social posts (#1669): public by construction
    "bluesky": PUBLIC,
    "mastodon": PUBLIC,
    "x": PUBLIC,
    "instagram": PUBLIC,
    "tiktok": PUBLIC,
}

# Activity-only OVERRIDES of a narrative classification: a source whose DATA is owner-only but whose
# one standing activity fact carries no timing, count or cadence at all. Precedence over
# narrative_provenance, so the set is pinned by test (never a journal family) and each entry carries
# its reason. Removing an entry takes its row off the public surface.
ACTIVITY_OVERRIDES: dict[str, str] = {
    "genome": PUBLIC,  # the status board's one-time "imported" row: no date, no cadence, no count (owner to confirm)
}

# HABITS, by IDENTITY (the Habitify id every stored status carries since #4632; a rename keeps it).
# Each habit is classified explicitly; an id in neither table is UNCLASSIFIED and is not published
# until it is classified here or the owner marks it in his registry (fail closed, owner 2026-11-03).
HABIT_FAMILIES: dict[str, tuple[str, str]] = {
    # The private journal (owner ruling 2026-11-03).
    "99A94E6D-3D82-4BE9-85EF-8858CB4BA340": ("Morning Journal", "journal_presence"),
    "A862488C-8219-48EB-AD1F-90CBFDC37788": ("Evening Journal", "journal_presence"),
    # NOT the journal — public by the owner's confirmation of 2026-11-03 ("distinct from my private
    # Morning Journal and Evening Journal"). Completion is public; their free text is not (FIELDS below).
    "DBACD2CF-F839-42B2-A698-D214140EE370": ("Food Journal", "food_log_presence"),
    "F5F5B8BB-62E8-4C74-9FD8-3C6E913F1DCD": ("Whoop Journal", "habitify"),
}
# Every other habit tracked when the ruling landed, by id only (names are owner data, and some are
# never-public under the content filter, which still applies on top of this class). These were
# already published; the owner asked to "preserve useful public habit information for non-private
# activities". A habit created after 2026-11-03 is NOT here and stays private until classified.
PUBLIC_HABIT_IDS: frozenset = frozenset(
    {
        "1427C438-3012-47B6-846D-3CAEF84F4F9A",
        "16D6E3B6-7345-4AB2-8DD1-F4BBEEADB750",
        "17CF0105-E527-4C7F-BAE7-B47940678BCB",
        "1802879F-0DC4-46A9-BF6E-EA3868EBF14E",
        "1A91B93B-6375-4733-B519-729C57FA0A1B",
        "24323781-32D8-4075-A517-F50446CEDCC8",
        "3039C9BD-FE6A-4CE4-90AF-A54C4FB7B20A",
        "306691EF-799A-4B92-8AA5-336A522D6B95",
        "32A47E30-9204-4D65-AD6E-C1E23E71196B",
        "39E3B75A-DA7F-48C3-BB2C-7427176BC7DC",
        "41669374-0F05-42A1-9CE8-FCFDBDBF2F3A",
        "4285C3CF-65AB-4086-9358-F0C375F5BE05",
        "439BE0C4-6345-41BC-9E2F-A14B9B2B3026",
        "50E63E49-3A62-47E1-9A4D-2EA946822E2A",
        "52110568-62D6-4A27-9CD9-BCBF212A4362",
        "57975F3D-F7B3-4D79-8FEB-7CBC1573C226",
        "583B4591-51CB-47C8-8A21-983879C9EC8C",
        "59D681AF-67FF-4714-8AEC-D7970B9D4CEB",
        "5C5B850B-3877-401B-8133-E7617D482149",
        "61252250-ED4F-4AE6-B6E4-C33993295C05",
        "61530C7A-E0F1-4159-B461-61FFAA380B4F",
        "65B78A03-59EE-4A4F-89AB-88A14D5F7285",
        "662F9DCD-BD73-4E38-ADAC-C16DDEDB1FF1",
        "68DB1AF2-A098-449E-AEE1-536E3AEBEE64",
        "6D37F8A7-1D58-4D06-B5CB-D943730FB01D",
        "6DF2A02C-146B-41A0-841F-DACAEACF75ED",
        "6F66604E-9BC0-4492-B7DA-A7305E3C4146",
        "70DCCA67-FA0F-475A-A5A0-8E8C104F8DAB",
        "758336AB-2A0E-4333-B786-4068330985ED",
        "79D6C725-E797-4258-84F8-956DD8D27A89",
        "870441B8-B3B4-43DD-B504-CA545F646EF9",
        "880D1CCF-B241-48DE-BD23-8D8F7FCC1430",
        "8862473E-A83E-49F1-B5CB-7D6A6F82EFE4",
        "892AFAF7-BFF1-4878-937F-711E2C785ADE",
        "899BD633-8444-4FC7-8782-05B1D5CC8CED",
        "8D2F0FAE-BF17-418B-BAF9-2C245919E2ED",
        "9568D883-0C4D-4D0A-911A-8DE1E23702B2",
        "972B4A56-BDA8-438C-B24A-DF1AA3910C7F",
        "97418321-0B71-44DA-9E56-380D47B3DF82",
        "A072A66C-FDB6-4603-A46B-7C3B914E012E",
        "A3ACCC4B-A3E9-4DD9-B480-FB2EBB7DE350",
        "AA7374E9-4C8B-49C3-AB51-81D9B363EB10",
        "AA77E55C-5F91-41B1-8856-C7EDDDD8BD21",
        "BC87115D-09AD-4970-9D14-C04968E7A930",
        "C164166F-0BCC-496B-8058-EC54999BAF5C",
        "CC8BDCB6-0B93-46D2-BC5C-E2DFEF8AE5AF",
        "D013DD53-60FB-4D84-9B0D-9C8045F4242B",
        "D0651EE7-BFB4-4770-964C-9AF415A0BD84",
        "D7140A89-6ED9-4D07-975D-6A634A0A1E75",
        "DBFFC84D-BE67-44F9-B235-70DC2749A566",
        "E3B1356D-ADD0-445C-9D59-ECF5D987F968",
        "E3E96254-9BA6-4308-83A1-28CB306A00B4",
        "EE3F690D-EE0F-4EC1-96E2-390AD3E71411",
        "F1A7E0F3-1377-456F-B0FA-C43E85EA51E0",
        "F5B303EE-B418-4769-8C07-F64A55F5C0FB",
        "F92AFAEC-4B0F-43F0-8E93-42401FFF910D",
        "aab05692-d982-4d7e-be83-b1559026d8bd",
    }
)
PUBLIC_HABIT_FAMILY = "habitify"  # an ordinary tracked habit: PUBLIC in narrative_provenance
OWNER_DECLARED_PRIVATE = "owner_declared_private"  # never in NP.SOURCE_FAMILIES -> not published
UNCLASSIFIED_HABIT = "unclassified_habit"  # never in NP.SOURCE_FAMILIES -> not published (fail closed)
REGISTRY_FIELD = "publication"  # PROFILE#v1.habit_registry[name][REGISTRY_FIELD] = "private" | "public"

# FIELDS of a stored Habitify status (``habit_statuses[name]``, written by
# ingestion.habitify_lambda.transform), classified one by one. A public habit is published through its
# PUBLIC fields only — its completion, schedule and group. Free text (in-app notes), the tap instant,
# the progress values, the vendor channel and old names are private, whatever the habit (owner
# 2026-11-03: a public habit "doesn't automatically authorize publishing associated free-text
# responses or private notes"). A field not listed is private; ``tests/test_journal_activity_privacy.py``
# fails when the ingest writes a field this table does not classify.
HABIT_STATUS_FIELDS: dict[str, str] = {
    "status": PUBLIC,
    "scheduled_today": PUBLIC,
    "periodicity": PUBLIC,
    "group": PUBLIC,
    "habit_id": PUBLIC,  # an opaque identifier; read for classification, never rendered
    "current_value": PRIVATE,
    "target_value": PRIVATE,
    "status_channel": PRIVATE,
    "miss_source": PRIVATE,
    "completed_at": PRIVATE,  # the tap instant
    "aliases": PRIVATE,  # the habit's former names
    "notes": PRIVATE,  # in-app free text
    "notes_at": PRIVATE,
    "note_channel": PRIVATE,
}

_IDS_BY_NAME = {name: hid for hid, (name, _fam) in HABIT_FAMILIES.items()}


# ── sources ────────────────────────────────────────────────────────────────────────────────


def source_class(source_id: Any) -> Optional[str]:
    """PUBLIC, PRIVATE, or None (unclassified — callers treat it as private)."""
    sid = str(source_id or "").strip()
    return ACTIVITY_OVERRIDES.get(sid) or NP.classify(sid) or ACTIVITY_ONLY_SOURCES.get(sid)


def source_is_public(source_id: Any) -> bool:
    """True only for a source classified PUBLIC. Private and unclassified sources are not published."""
    return source_class(source_id) == PUBLIC


def is_private_activity_source(source_id: Any) -> bool:
    """For a tally over platform JOBS as well as sources (the daily probe names compute jobs too): True
    when the job's source (``"notion:enrichment"`` -> ``notion``) is a PRIVATE source, or a registry
    source with no classification (fail closed). A compute job that is not a source is not private
    activity and stays in the tally."""
    base = str(source_id or "").split(":", 1)[0].strip()
    cls = source_class(base)
    if cls == PRIVATE:
        return True
    if cls is None:
        from ingestion.source_registry import SOURCE_REGISTRY

        return base in SOURCE_REGISTRY
    return False


def public_sources(source_ids: Iterable[Any]) -> list:
    """``source_ids`` in their order, private and unclassified ones dropped."""
    return [s for s in source_ids if source_is_public(s)]


def public_mapping(sources: Mapping[str, Any]) -> dict:
    """A ``{source_id: ...}`` mapping restricted to public sources (order kept)."""
    return {k: v for k, v in (sources or {}).items() if source_is_public(k)}


# ── habits ─────────────────────────────────────────────────────────────────────────────────


def habit_family(name: Any, status: Any = None, registry_meta: Any = None) -> str:
    """The source family of one habit, decided by identity (never by the words in its name).

    Order: the owner's registry ``publication`` field (his explicit word wins); the Habitify id on the
    stored status, else the registry entry's ``habitify_id``; the canonical name of a NAMED id (a status
    written before ids were stored). Anything else is UNCLASSIFIED — not published (fail closed)."""
    st = status if isinstance(status, Mapping) else {}
    meta = registry_meta if isinstance(registry_meta, Mapping) else {}
    declared = str(meta.get(REGISTRY_FIELD) or "").strip().lower()
    hid = str(st.get("habit_id") or meta.get("habitify_id") or "").strip()
    if not hid and str(name or "") in _IDS_BY_NAME:
        hid = _IDS_BY_NAME[str(name)]
    if hid in HABIT_FAMILIES and HABIT_FAMILIES[hid][1] == "journal_presence":
        return "journal_presence"  # the journal is private whatever a registry field says
    if declared == PRIVATE:
        return OWNER_DECLARED_PRIVATE
    if declared == PUBLIC:
        return PUBLIC_HABIT_FAMILY
    if hid in HABIT_FAMILIES:
        return HABIT_FAMILIES[hid][1]
    if hid in PUBLIC_HABIT_IDS:
        return PUBLIC_HABIT_FAMILY
    return UNCLASSIFIED_HABIT


def habit_is_public(name: Any, status: Any = None, registry_meta: Any = None) -> bool:
    return NP.classify(habit_family(name, status, registry_meta)) == PUBLIC


def public_status_fields(status: Any) -> dict:
    """One stored status reduced to its PUBLIC fields (``HABIT_STATUS_FIELDS``; unlisted = private)."""
    st = status if isinstance(status, Mapping) else {}
    return {k: v for k, v in st.items() if HABIT_STATUS_FIELDS.get(k) == PUBLIC}


def public_habit_statuses(statuses: Any, registry: Any = None) -> dict:
    """A Habitify ``habit_statuses`` map with every non-public habit removed and every remaining
    status reduced to its public fields."""
    reg = registry if isinstance(registry, Mapping) else {}
    out = {}
    for name, st in (statuses or {}).items() if isinstance(statuses, Mapping) else ():
        if habit_is_public(name, st, reg.get(name)):
            out[name] = public_status_fields(st)
    return out


def public_group_pcts(statuses: Any, groups: Iterable[Any], registry: Any = None) -> dict:
    """``{group: pct 0-100}`` recomputed over the PUBLIC habits only — the semantics of the ingest's
    ``by_group`` (``ingestion.habitify_lambda._aggregate``: completed / scheduled habits in the
    group), so a group's share never counts a private habit in its numerator or denominator. A
    group left with no public habit is omitted (its existence would say only that private habits
    were scheduled)."""
    allowed = {str(g) for g in groups or ()}
    done: dict = {}
    possible: dict = {}
    for _name, st in public_habit_statuses(statuses, registry).items():
        st = st if isinstance(st, Mapping) else {}
        g = st.get("group") or "Other"
        if g not in allowed:
            continue
        possible[g] = possible.get(g, 0) + 1
        if st.get("status") == "completed":
            done[g] = done.get(g, 0) + 1
    return {g: round(done.get(g, 0) / n * 100) for g, n in sorted(possible.items()) if n}
