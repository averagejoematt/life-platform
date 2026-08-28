"""
genome_coaching.py — Genome-personalized guidance for daily brief AI context.

Reads the stored per-variant clinical interpretations from DynamoDB and maps them to
coaching deltas. Rotates which insights surface each week to prevent repetition.

#3282 — WHAT THIS MODULE MAY AND MAY NOT ASSERT.
The catalog below holds coaching text keyed by gene. Which text (if any) is emitted is
decided ONLY by the stored record's own `risk_level` label — never by the presence of
the gene, which every human has. Three rules, each of which was violated before #3282:

  1. Presence is not a phenotype. A gene row existing says nothing; the row's stored
     label says everything. Selection reads the label.
  2. Every arm the catalog defines must be reachable. An entry whose arms are a
     complementary pair (cautionary / tolerant) needs BOTH selectable, or the one that
     is reachable fires regardless of the record and the module asserts a phenotype the
     stored record contradicts.
  3. Absence is a real answer (ADR-104). A stored record whose label is not actionable
     emits NOTHING. It does not fall through to a "variant detected" line, and it does
     not invite the model to guess.

Used by: daily_brief_lambda.py (import, not standalone)
"""

import logging

from common.pacific_time import pacific_now  # #2811: the rotation week is a Pacific week

logger = logging.getLogger(__name__)

# The stored label vocabulary, per docs/SCHEMA.md's genome SNP field table. Every arm's
# `risk_levels` must be drawn from this set — a typo'd label would otherwise mint an arm
# that can never be selected, which is the #3282 defect wearing a different hat.
STORED_RISK_LABELS = ("favorable", "neutral", "unfavorable", "mixed")

# The labels that license a "you carry an actionable variant" statement. `neutral` and
# `favorable` do not: they are the record telling us there is nothing to act on, and
# ADR-104 says that is an answer, not a gap to paper over.
_ACTIONABLE = ("unfavorable", "mixed")

# Genome coaching catalog: gene → arms → coaching delta. Rotated weekly.
#
# `arms` is an ORDERED list. Each arm names the stored labels that select it, and the
# order is the precedence: the cautionary arm is declared first, so a gene carrying rows
# on both sides of the pair resolves to the cautionary arm rather than to whichever row
# the query happened to return last. Arms within an entry must have disjoint label sets
# (pinned by test) so selection is deterministic and no arm can be shadowed dead.
GENOME_INSIGHTS = [
    {
        "gene": "CYP1A2",
        "focus": "caffeine",
        "arms": [
            {
                "key": "slow_variant_coaching",
                "risk_levels": _ACTIONABLE,
                "coaching": "CYP1A2 slow metabolizer — cap caffeine at 150mg, all before 10am. Afternoon caffeine impairs sleep for this genotype.",
            },
            {
                "key": "fast_variant_coaching",
                "risk_levels": ("favorable",),
                "coaching": "CYP1A2 fast metabolizer — caffeine tolerance higher, but still cap at 300mg. Monitor HRV for individual response.",
            },
        ],
    },
    {
        "gene": "MTHFR",
        "focus": "methylation",
        "arms": [
            {
                "key": "variant_coaching",
                "risk_levels": _ACTIONABLE,
                "coaching": "MTHFR variant detected — methylfolate (L-5-MTHF) preferred over folic acid. Check folate status in labs.",
            },
        ],
    },
    {
        "gene": "FTO",
        "focus": "satiety",
        "arms": [
            {
                "key": "risk_coaching",
                "risk_levels": _ACTIONABLE,
                "coaching": "FTO risk variant — satiety signals may be weaker. Portion control and protein-first eating more critical than macro manipulation.",
            },
        ],
    },
    {
        "gene": "BDNF",
        "focus": "exercise_timing",
        "arms": [
            {
                "key": "variant_coaching",
                "risk_levels": _ACTIONABLE,
                "coaching": "BDNF val66met variant — exercise timing matters more for cognitive health. Prefer morning training for optimal BDNF release.",
            },
        ],
    },
    {
        "gene": "FADS1/FADS2",
        "focus": "omega3",
        "arms": [
            {
                "key": "variant_coaching",
                "risk_levels": _ACTIONABLE,
                "coaching": "FADS variant — ALA to EPA/DHA conversion may be impaired. Direct EPA/DHA supplementation (fish oil) more effective than plant-based omega-3.",
            },
        ],
    },
    {
        "gene": "VKORC1",
        "focus": "vitamin_k",
        "arms": [
            {
                "key": "variant_coaching",
                "risk_levels": _ACTIONABLE,
                "coaching": "VKORC1 variant — vitamin K metabolism altered. Consistent daily K2 intake important for bone health and calcium metabolism.",
            },
        ],
    },
    {
        "gene": "MTNR1B",
        "focus": "melatonin",
        "arms": [
            {
                "key": "variant_coaching",
                "risk_levels": _ACTIONABLE,
                "coaching": "MTNR1B variant — melatonin receptor sensitivity differs. Focus on light timing and sleep environment over melatonin supplementation.",
            },
        ],
    },
]

# The rotation, stated once so the comment and the code cannot disagree (#3282): scan
# _ROTATION_WINDOW consecutive catalog slots, emit at most _INSIGHTS_PER_WEEK of them.
# The window exceeds the cap on purpose — under the label-driven selector a slot can
# legitimately have nothing to say, and the window keeps that from silently halving the
# week's output. Both numbers are used by the code below; neither is written twice.
_INSIGHTS_PER_WEEK = 2
_ROTATION_WINDOW = 3

# Follow LastEvaluatedKey to exhaustion. The old `Limit=100` was not a safeguard, it was
# a truncation: it returned a LastEvaluatedKey nobody read, so genes past the first page
# were invisible to the coach for a paging reason rather than a biological one. The page
# cap here is only a runaway guard, and exhausting it is logged rather than swallowed.
_MAX_QUERY_PAGES = 20


def _gene_key(insight):
    """The lookup key for a catalog entry (the first gene of a slash-joined family)."""
    return insight["gene"].split("/")[0].upper()


def select_coaching_arm(insight, records):
    """Return the coaching text the STORED records select for `insight`, or "".

    `records` is every stored row for that gene (a gene can carry several variants, and
    they do not have to agree). Selection walks the entry's arms in declaration order and
    takes the first whose `risk_levels` intersect the labels actually stored, so:

      * a gene whose rows carry no actionable label returns "" — the honest answer, not
        the first arm in an `or`-chain (ADR-104);
      * a gene with rows on both sides of a complementary pair resolves to the arm
        declared first, deterministically, instead of to whichever row DynamoDB
        happened to return last;
      * an arm is unreachable only if the catalog says so, never because of the order
        the `*_coaching` keys were spelled in.
    """
    labels = {str(r.get("risk_level") or "").strip().lower() for r in (records or []) if isinstance(r, dict)}
    labels.discard("")
    if not labels:
        return ""
    for arm in insight.get("arms") or ():
        if labels & set(arm.get("risk_levels") or ()):
            return arm.get("coaching") or ""
    return ""


def _fetch_genome_rows(table, genome_pk):
    """Every row on the genome partition, paged to exhaustion."""
    from boto3.dynamodb.conditions import Key

    items = []
    kwargs = {"KeyConditionExpression": Key("pk").eq(genome_pk)}
    for _ in range(_MAX_QUERY_PAGES):
        resp = table.query(**kwargs)
        items.extend(resp.get("Items") or [])
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            return items
        kwargs["ExclusiveStartKey"] = last_key
    logger.warning(f"Genome coaching: page cap {_MAX_QUERY_PAGES} hit with more rows pending — coverage is INCOMPLETE")
    return items


def build_genome_coaching_context(table, user_prefix):
    """Read stored variant interpretations and generate weekly-rotated coaching insights.

    Returns a string to inject into daily brief prompts, or empty string if no genome
    data — or if nothing in this week's rotation has an actionable stored label.
    """
    try:
        items = _fetch_genome_rows(table, f"{user_prefix}genome")
        if not items:
            return ""

        # Gene → ALL of its stored rows. A dict of single items dropped every row but the
        # last for any gene carrying more than one variant, and which one survived was an
        # artifact of sort-key order.
        rows_by_gene = {}
        for item in items:
            gene = item.get("gene", "")
            if gene:
                rows_by_gene.setdefault(gene.upper(), []).append(item)

        if not rows_by_gene:
            return ""

        # Rotate which insights surface — use week number. #2811: the ISO week is a
        # DAY-derived label, and the platform's weeks are Pacific ones; a UTC week
        # number rotates the insight set on Sunday at 17:00 PT instead of midnight.
        week_num = pacific_now().isocalendar()[1]
        start_idx = (week_num * _INSIGHTS_PER_WEEK) % len(GENOME_INSIGHTS)
        selected = []
        for i in range(_ROTATION_WINDOW):
            if len(selected) >= _INSIGHTS_PER_WEEK:
                break
            insight = GENOME_INSIGHTS[(start_idx + i) % len(GENOME_INSIGHTS)]
            coaching = select_coaching_arm(insight, rows_by_gene.get(_gene_key(insight)))
            if coaching:
                selected.append(coaching)

        if not selected:
            return ""

        result = "GENOME-INFORMED COACHING (rotated weekly):\n" + "\n".join(f"- {s}" for s in selected)
        # The distinct-gene count travels with the log line so coverage is checkable from
        # CloudWatch alone — the paging defect was invisible precisely because it wasn't.
        logger.info(f"Genome coaching: {len(selected)} insights selected (week {week_num}, {len(rows_by_gene)} genes read)")
        return result

    except Exception as e:
        logger.warning(f"Genome coaching failed (non-fatal): {e}")
        return ""
