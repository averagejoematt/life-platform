"""
genome_coaching.py — Genome-personalized guidance for daily brief AI context.

Reads genome SNP data from DynamoDB and maps to coaching deltas.
Rotates which insights surface each week to prevent repetition.

Used by: daily_brief_lambda.py (import, not standalone)
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _float(val):
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# Genome coaching rules: SNP gene → variant → coaching delta
# Rotated weekly so different insights surface each week
GENOME_INSIGHTS = [
    {
        "gene": "CYP1A2",
        "focus": "caffeine",
        "slow_variant_coaching": "CYP1A2 slow metabolizer — cap caffeine at 150mg, all before 10am. Afternoon caffeine impairs sleep for this genotype.",
        "fast_variant_coaching": "CYP1A2 fast metabolizer — caffeine tolerance higher, but still cap at 300mg. Monitor HRV for individual response.",
    },
    {
        "gene": "MTHFR",
        "focus": "methylation",
        "variant_coaching": "MTHFR variant detected — methylfolate (L-5-MTHF) preferred over folic acid. Check folate status in labs.",
    },
    {
        "gene": "FTO",
        "focus": "satiety",
        "risk_coaching": "FTO risk variant — satiety signals may be weaker. Portion control and protein-first eating more critical than macro manipulation.",
    },
    {
        "gene": "BDNF",
        "focus": "exercise_timing",
        "variant_coaching": "BDNF val66met variant — exercise timing matters more for cognitive health. Prefer morning training for optimal BDNF release.",
    },
    {
        "gene": "FADS1/FADS2",
        "focus": "omega3",
        "variant_coaching": "FADS variant — ALA to EPA/DHA conversion may be impaired. Direct EPA/DHA supplementation (fish oil) more effective than plant-based omega-3.",
    },
    {
        "gene": "VKORC1",
        "focus": "vitamin_k",
        "variant_coaching": "VKORC1 variant — vitamin K metabolism altered. Consistent daily K2 intake important for bone health and calcium metabolism.",
    },
    {
        "gene": "MTNR1B",
        "focus": "melatonin",
        "variant_coaching": "MTNR1B variant — melatonin receptor sensitivity differs. Focus on light timing and sleep environment over melatonin supplementation.",
    },
]


def build_genome_coaching_context(table, user_prefix):
    """Read genome SNPs and generate weekly-rotated coaching insights.

    Returns a string to inject into daily brief prompts, or empty string if no genome data.
    """
    try:
        from boto3.dynamodb.conditions import Key
        genome_pk = f"{user_prefix}genome"
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(genome_pk),
            Limit=100,
        )
        items = resp.get("Items", [])
        if not items:
            return ""

        # Build SNP lookup
        snps = {}
        for item in items:
            gene = item.get("gene", "")
            if gene:
                snps[gene.upper()] = item

        if not snps:
            return ""

        # Rotate which insights surface — use week number
        week_num = datetime.now(timezone.utc).isocalendar()[1]
        # Select 2-3 insights per week, rotating through the list
        start_idx = (week_num * 2) % len(GENOME_INSIGHTS)
        selected = []
        for i in range(3):
            idx = (start_idx + i) % len(GENOME_INSIGHTS)
            insight = GENOME_INSIGHTS[idx]
            gene_key = insight["gene"].split("/")[0].upper()
            if gene_key in snps:
                # Gene exists in genome data — use specific coaching
                coaching = (insight.get("variant_coaching")
                           or insight.get("risk_coaching")
                           or insight.get("slow_variant_coaching")
                           or "")
                if coaching:
                    selected.append(coaching)

        if not selected:
            return ""

        result = "GENOME-INFORMED COACHING (rotated weekly):\n" + "\n".join(f"- {s}" for s in selected[:2])
        logger.info(f"Genome coaching: {len(selected)} insights selected (week {week_num})")
        return result

    except Exception as e:
        logger.warning(f"Genome coaching failed (non-fatal): {e}")
        return ""
