#!/usr/bin/env python3
"""
seed_genome.py — Seed genome SNP clinical interpretations into Life Platform DynamoDB.

Source: Comprehensive SNP report (49 pages, ~78 distinct SNP entries)
Report date: June 2020 (file created 2020-06-19)
Genotyping source: Consumer genomics (e.g. 23andMe/AncestryDNA raw data)

Stores ONLY clinical interpretations and actionable insights — no raw genotype files.
Each SNP includes: gene, rsID, genotype, summary, impact category, risk level,
and actionable recommendations.

Schema:
  PK: USER#matthew#SOURCE#genome
  SK: GENE#<gene_name>#SNP#<rsid>

Usage:
  python3 seed_genome.py          # dry run
  python3 seed_genome.py --write  # write to DynamoDB
"""

import boto3
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal

TABLE_NAME = "life-platform"
REGION = "us-west-2"
USER = "matthew"
SOURCE = "genome"
PK = f"USER#{USER}#SOURCE#{SOURCE}"
NOW = datetime.now(timezone.utc).isoformat()


def snp(gene, rsid, genotype, summary, category, risk_level, details=None,
        actionable_recs=None, related_biomarkers=None, related_snps=None):
    """Build a SNP interpretation entry."""
    entry = {
        "pk": PK,
        "sk": f"GENE#{gene}#SNP#{rsid}",
        "gene": gene,
        "rsid": rsid,
        "genotype": genotype,
        "summary": summary,
        "category": category,
        "risk_level": risk_level,
        "updated_at": NOW,
        "report_date": "2020-06-19",
        "report_type": "comprehensive_snp_interpretation",
    }
    if details:
        entry["details"] = details
    if actionable_recs:
        entry["actionable_recs"] = actionable_recs
    if related_biomarkers:
        entry["related_biomarkers"] = related_biomarkers
    if related_snps:
        entry["related_snps"] = related_snps
    return entry


SNPS = [
    # ═══════════════════════════════════════════════
    # OBESITY / METABOLISM
    # ═══════════════════════════════════════════════

    snp("ADIPOQ", "rs17300539", "G;G",
        "Lower adiponectin levels and higher risk for obesity",
        "metabolism", "unfavorable",
        details="G;G associated with lower adiponectin (anti-inflammatory, cardioprotective protein). "
                "Higher HOMA-IR, insulin, triglycerides. After weight loss, unfavorable biomarkers return "
                "at 32-week follow-up. A allele associated with longevity in centenarian studies.",
        actionable_recs=[
            "Weight loss via lifestyle changes increases adiponectin levels",
            "Exercise (various types) shown to increase adiponectin",
            "Increase MUFA intake (olive oil, avocados, nuts) — associated with reduced obesity risk for G;G",
            "Increase PUFA intake (fatty fish)",
            "Intermittent fasting shown to increase adiponectin",
            "Mediterranean diet shown to increase adiponectin in T2D patients",
        ],
        related_biomarkers=["adiponectin", "insulin", "triglycerides", "HOMA-IR"]),

    snp("FTO", "rs9939609", "A;T",
        "Intermediate increased risk of obesity and type 2 diabetes due to high ghrelin production",
        "metabolism", "unfavorable",
        details="FTO is the major genetic risk factor for obesity. A;T heterozygous = intermediate risk. "
                "A allele associated with higher ghrelin (hunger hormone), increased appetite.",
        actionable_recs=[
            "Protein-rich meals help suppress ghrelin",
            "Regular physical activity attenuates FTO obesity risk",
            "Higher PUFA, lower saturated fat intake recommended",
        ],
        related_biomarkers=["ghrelin", "BMI"]),

    snp("FTO", "rs1421085", "C;T",
        "1.3-fold increased risk for obesity; exercise may mitigate",
        "metabolism", "unfavorable",
        details="C;T intermediate risk. Regular exercise shown to combat negative effects of this FTO variant.",
        actionable_recs=[
            "Regular exercise — shown to reduce FTO obesity risk",
            "Higher PUFA, lower saturated fat intake",
        ]),

    snp("FTO", "rs17817449", "G;T",
        "1.3-fold increased obesity risk; saturated fat may negatively affect blood glucose/insulin",
        "metabolism", "unfavorable",
        details="Saturated fat particularly detrimental for this genotype. Higher PUFA to saturated fat "
                "ratio recommended.",
        actionable_recs=[
            "Limit saturated fat (fatty beef, pork, coconut oil, butter, cheese)",
            "Increase PUFA intake (nuts, fatty fish)",
        ],
        related_biomarkers=["glucose", "insulin"]),

    snp("FTO", "rs1558902", "A;T",
        "Higher BMI; high-protein diet may benefit weight/fat loss",
        "metabolism", "unfavorable",
        details="A allele carriers on high-protein diet (25% kcals) experienced greater weight and fat loss "
                "than on low-protein diet. Higher protein diet may be beneficial for weight reduction.",
        actionable_recs=[
            "High-protein diet (>18% kcals from protein) for weight/fat loss",
            "Consume >18% kcals from protein to offset genotype risk",
        ]),

    snp("FTO", "rs1121980", "C;T",
        "1.67-fold increased risk for obesity particularly with saturated fat",
        "metabolism", "unfavorable",
        details="Cluster of FTO polymorphisms all pointing to increased obesity risk modulated by saturated fat.",
        actionable_recs=[
            "Higher PUFA to saturated fat ratio",
            "Limit saturated fat intake",
        ]),

    snp("FTO", "rs3751812", "G;T",
        "Increased obesity risk; fiber and Mediterranean diet protective",
        "metabolism", "unfavorable",
        details="T allele carriers with adequate fiber intake had reduced obesity risk. Western diet pattern "
                "(fast food, soft drinks) particularly detrimental. Physical activity reduces risk. "
                "Mediterranean diet associated with reduced waist circumference.",
        actionable_recs=[
            "Adequate dietary fiber intake",
            "Mediterranean diet pattern",
            "Avoid Western diet pattern (fast food, soft drinks)",
            "Regular physical activity",
        ]),

    snp("IRS1", "rs2943641", "C;C",
        "Increased risk for type 2 diabetes; may benefit from high-carb/low-fat diet",
        "metabolism", "unfavorable",
        details="C;C associated with decreased IRS1 protein, higher fasting insulin, insulin resistance. "
                "POUNDS LOST trial: C;C subjects had greater IR improvements on highest carbohydrate diet. "
                "High-carb/low-fat diet improved IR and weight loss. High-quality carbs recommended.",
        actionable_recs=[
            "High-carbohydrate/low-fat diet may improve insulin resistance",
            "Choose high-quality carbohydrate foods",
            "Saturated fat particularly unfavorable — low-fat diet beneficial",
        ],
        related_biomarkers=["insulin", "HOMA-IR", "glucose"]),

    snp("GIPR", "rs2287019", "C;C",
        "Increased risk for obesity",
        "metabolism", "unfavorable",
        details="GIP receptor variant. C;C may affect incretin response and glucose-dependent insulin secretion."),

    snp("ADRB3", "rs4994", "C;T",
        "Slight difficulty losing weight without exercise; elite endurance performance in men",
        "metabolism", "mixed",
        details="C allele associated with obesity risk, higher glucose/insulin, altered lipids. "
                "However, exercise mitigates effects. Also associated with elite endurance performance in men.",
        actionable_recs=[
            "Exercise essential for weight management with this genotype",
            "Cold exposure activates brown adipose tissue (BAT) — may help via ADRB3 thermogenesis",
        ]),

    snp("MC4R", "rs2229616", "G;G",
        "Normal risk for obesity, type 2 diabetes and coronary artery disease",
        "metabolism", "neutral"),

    snp("MC4R", "rs17782313", "T;T",
        "Normal appetite regulation and obesity risk",
        "metabolism", "neutral"),

    snp("PPARG", "rs1801282", "C;C",
        "Normal risk for obesity and T2D in response to dietary fat profile",
        "metabolism", "neutral"),

    snp("PPM1K", "rs1440581", "A;A",
        "May benefit from high-fat/low-carb diet for glucose metabolism",
        "metabolism", "neutral",
        details="A allele lost more weight and improved insulin resistance on high-fat diet vs low-fat. "
                "G allele carriers may show fewer benefits from high-fat diet.",
        actionable_recs=[
            "High-fat, low-carb diet may benefit glucose metabolism for this genotype",
        ]),

    snp("UCP1", "rs1800592", "A;A",
        "Normal resting metabolic rate",
        "metabolism", "neutral"),

    snp("LPL", "rs328", "C;C",
        "Normal HDL-C and triglyceride levels",
        "lipids", "neutral"),

    snp("GCKR", "rs1260326", "C;C",
        "Normal fasting glucose and triglycerides; omega-3 intake may lower inflammation",
        "metabolism", "neutral",
        details="C;C with low omega-3 had higher CRP, fasting insulin, HOMA-IR. "
                "At higher omega-3 intake, these markers improved.",
        actionable_recs=[
            "Higher omega-3 fatty acid intake may reduce inflammation and insulin resistance",
        ],
        related_biomarkers=["CRP", "insulin", "HOMA-IR", "triglycerides"]),

    # ═══════════════════════════════════════════════
    # LIPIDS / CARDIOVASCULAR
    # ═══════════════════════════════════════════════

    snp("PPAR_alpha", "rs1800206", "C;G",
        "Increased risk for altered blood lipids and T2D with high saturated fat diet",
        "lipids", "unfavorable",
        details="Lower PPAR-alpha activity. 2-fold higher T2D risk, increased triglycerides, total cholesterol, "
                "LDL, small-dense LDL, apoB when saturated fat > PUFA. Ketogenic diet high in sat fat "
                "may be detrimental. PUFA-dominant fat intake recommended.",
        actionable_recs=[
            "Keep PUFA intake higher than saturated fat intake",
            "Ketogenic diet high in saturated fat may be detrimental — use PUFA-dominant fats",
            "Vitamin C may increase PPAR-alpha gene expression",
            "Pterostilbene (blueberries, cranberries, almonds) may be beneficial",
            "Limit: fatty beef, pork, coconut oil, butter, cheese",
            "Favor: nuts, fatty fish (salmon, herring), olive oil",
        ],
        related_biomarkers=["triglycerides", "cholesterol_total", "ldl_c", "apoB"]),

    snp("ABCG8", "rs6544713", "T;T",
        "Elevated levels of LDL cholesterol",
        "lipids", "unfavorable",
        details="ABCG8 involved in cholesterol and plant sterol metabolism. T;T associated with "
                "elevated LDL-C. Affects sterol excretion via biliary system.",
        actionable_recs=[
            "Monitor LDL-C levels regularly",
            "Consider plant sterol/stanol supplementation with physician guidance",
        ],
        related_biomarkers=["ldl_c"]),

    snp("LPA", "rs10455872", "A;A",
        "Normal plasma lipoprotein(a) levels and normal coronary heart disease risk",
        "lipids", "neutral"),

    snp("LPA", "rs3798220", "T;T",
        "Normal plasma lipoprotein(a) levels and normal coronary artery disease risk",
        "lipids", "neutral"),

    snp("PCSK9", "rs11591147", "G;G",
        "Normal LDL cholesterol and average heart disease risk",
        "lipids", "neutral"),

    snp("APOE", "rs429358/rs7412", "T;T/C;C",
        "APO-E3/E3 — Normal lipid homeostasis benchmark; normal Alzheimer's and CVD risk",
        "lipids", "neutral",
        details="E3/E3 is the reference genotype for normal lipid and cholesterol transport. "
                "Standard cardiovascular and Alzheimer's disease risk."),

    snp("HMGCR", "rs17238540", "T;T",
        "Normal response to statin treatment",
        "lipids", "neutral"),

    snp("LIPC", "rs2070895", "G;G",
        "Normal HDL-C levels",
        "lipids", "neutral"),

    snp("APOA1", "rs670", "G;G",
        "Normal risk for metabolic syndrome; plasma lipids may be less responsive to dietary fat",
        "lipids", "neutral",
        details="G;G may have less HDL response to dietary PUFA changes compared to A allele carriers.",
        actionable_recs=[
            "Omega-3 supplementation and regular exercise may still raise HDL-C",
        ]),

    snp("ACE", "rs4343", "A;G",
        "Intermediate ACE activity; may benefit from lower fat diet (<37% kcals)",
        "cardiovascular", "mixed",
        details="G;G on >37% fat diet had higher blood pressure and 4.6-fold T2D risk vs <37% fat. "
                "A;G intermediate. G allele may be protective factor in COVID-19 severity.",
        actionable_recs=[
            "Keep total fat intake below 37% of daily calories",
            "Limit saturated fat",
        ],
        related_biomarkers=["blood_pressure", "glucose"]),

    # ═══════════════════════════════════════════════
    # STATIN RESPONSE
    # ═══════════════════════════════════════════════

    snp("SLCO1B1", "rs4363657", "C;T",
        "4.5-fold increased risk for myopathy with simvastatin use",
        "statin_response", "unfavorable",
        details="Increased risk specifically with simvastatin and atorvastatin. "
                "Risk not observed with rosuvastatin or pravastatin. "
                "CoQ10 supplementation may reduce myopathy symptoms.",
        actionable_recs=[
            "If statins needed, rosuvastatin or pravastatin may be better tolerated",
            "Avoid high-dose simvastatin",
            "CoQ10 supplementation (shown to reduce statin myopathy pain by 40%)",
            "Discuss genotype with physician if statin therapy considered",
        ]),

    snp("SLCO1B1", "rs4149056", "C;T",
        "4.5-fold increased risk for myopathy with statin use (simvastatin/atorvastatin)",
        "statin_response", "unfavorable",
        details="Same SLCO1B1 gene, second variant confirming statin sensitivity. "
                "Risk is dose-dependent with simvastatin.",
        actionable_recs=[
            "Prefer rosuvastatin or pravastatin if statins required",
            "CoQ10 supplementation recommended alongside any statin",
        ]),

    snp("COQ2", "rs4693596", "C;T",
        "Normal risk for myopathy with statin use (C;C variant has 2x risk)",
        "statin_response", "neutral",
        details="C;T generally normal, but C;C has 2x statin myopathy risk."),

    # ═══════════════════════════════════════════════
    # NUTRIENT METABOLISM
    # ═══════════════════════════════════════════════

    snp("MTRR", "rs1801394", "G;G",
        "Increased risk for hyperhomocysteinemia and altered choline metabolism",
        "nutrient_metabolism", "unfavorable",
        details="Reduced MTRR enzyme affinity for MTR. Less efficient homocysteine-to-methionine "
                "conversion. May need higher choline intake above AI levels.",
        actionable_recs=[
            "Ensure adequate B12, B2 (riboflavin), and folate intake",
            "Choline intake above AI (550mg men) — eggs, meat, fish, cruciferous vegetables",
            "Betaine supplementation (1.5-6g/day) can reduce homocysteine up to 40%",
            "Monitor homocysteine levels",
        ],
        related_biomarkers=["homocysteine", "vitamin_b12"]),

    snp("MTHFR", "rs1801131/rs1801133", "A;C/C;T",
        "Compound heterozygous — decreased folate metabolism and hyperhomocysteinemia risk",
        "nutrient_metabolism", "unfavorable",
        details="One variant allele in each MTHFR SNP. rs1801133 T = thermolabile enzyme with reduced activity. "
                "Combination results in ~70% decrease in MTHFR functional efficiency. "
                "Elevated homocysteine associated with coronary artery disease, stroke, dementia.",
        actionable_recs=[
            "Supplement with 5-methylfolate (active form, bypasses MTHFR)",
            "Methylcobalamin (B12) and riboflavin (B2)",
            "Betaine (1.5-6g/day) for alternative homocysteine reduction pathway",
            "Foods rich in betaine: quinoa, spinach, beets",
            "Monitor homocysteine levels regularly",
        ],
        related_biomarkers=["homocysteine", "folate"]),

    snp("MTHFD1", "rs2236225", "C;T",
        "Increased risk of choline deficiency even at adequate dietary intake levels",
        "nutrient_metabolism", "unfavorable",
        details="Thermolabile MTHFD1 enzyme with shorter half-life. Risk for NAFLD when choline-deprived. "
                "May need choline intake above current AI. 40% reduction in colon cancer risk for T carriers.",
        actionable_recs=[
            "Choline intake above AI (550mg/day for men)",
            "Rich sources: eggs, meat, fish, cruciferous vegetables",
        ],
        related_biomarkers=["choline"]),

    snp("VitD_binding", "rs7041", "G;T",
        "Possible genetic risk for vitamin D deficiency",
        "nutrient_metabolism", "unfavorable",
        details="Less efficient vitamin D binding protein. May require higher supplementation doses "
                "to achieve same serum levels as non-carriers.",
        actionable_recs=[
            "Get 25-hydroxyvitamin D blood test to assess current levels",
            "Target 30-60 ng/mL 25-hydroxyvitamin D",
            "May need >1000 IU/day vitamin D3 supplementation",
            "Retest after supplementation to guide optimal dosage",
        ],
        related_biomarkers=["vitamin_d_25oh"]),

    snp("VitD_binding", "rs2282679", "A;C",
        "Possible genetic risk for vitamin D deficiency (second variant)",
        "nutrient_metabolism", "unfavorable",
        details="Second GC gene variant confirming vitamin D deficiency predisposition.",
        actionable_recs=[
            "Same as rs7041 — test and supplement vitamin D",
        ],
        related_biomarkers=["vitamin_d_25oh"]),

    snp("CYP2R1", "rs2060793", "G;G",
        "Possible genetic risk for lower vitamin D levels",
        "nutrient_metabolism", "unfavorable",
        details="CYP2R1 involved in vitamin D metabolism. G;G may have lower 25-hydroxyvitamin D levels.",
        actionable_recs=[
            "Three separate SNPs all point to vitamin D deficiency risk — supplementation important",
        ],
        related_biomarkers=["vitamin_d_25oh"]),

    snp("FADS2", "rs1535", "A;G",
        "26.7% poorer conversion of ALA into omega-3 EPA",
        "nutrient_metabolism", "unfavorable",
        details="G allele = elevated ALA, reduced EPA. Reduced efficiency of plant omega-3 conversion. "
                "Particularly relevant for vegetarians/vegans relying on flaxseed/chia for omega-3.",
        actionable_recs=[
            "Prioritize direct EPA/DHA sources (fish, fish oil, algae oil) over ALA",
            "Don't rely solely on flaxseed/chia for omega-3 needs",
            "Consider fish oil or algae-based omega-3 supplement",
        ],
        related_biomarkers=["omega3_index"]),

    snp("FADS1", "rs174548", "C;G",
        "Intermediate phosphatidylcholine levels",
        "nutrient_metabolism", "mixed",
        details="G allele = reduced FADS1 enzyme efficiency. May affect phosphatidylcholine and "
                "acetylcholine production. Related to memory and neurodegeneration."),

    snp("FADS1", "rs174550", "C;T",
        "Slight increased inflammation with high linoleic acid (omega-6) diet",
        "nutrient_metabolism", "unfavorable",
        details="C allele associated with increased hsCRP on high omega-6 diet. "
                "Western diet (15:1 omega-6:omega-3 ratio) favors pro-inflammatory pathway.",
        actionable_recs=[
            "Reduce omega-6 to omega-3 ratio",
            "Reduce omega-6 sources (sunflower oil, soybean oil)",
            "Increase omega-3 sources (fatty fish, fish oil)",
        ],
        related_biomarkers=["hsCRP"]),

    snp("FUT2", "rs601338", "A;A",
        "Non-secretor: lower vitamin B12 levels, altered microbiome, protection from some pathogens",
        "nutrient_metabolism", "mixed",
        details="Non-secretor status (~20% of population). Lower B12 levels. Does not express ABO(H) "
                "antigens on GI cells. Protection from certain pathogens but may have lower Bifidobacteria.",
        actionable_recs=[
            "Monitor vitamin B12 levels",
            "Consider B12 supplementation",
            "Probiotic supplementation (Bifidobacterium) may be beneficial",
        ],
        related_biomarkers=["vitamin_b12"]),

    snp("FUT2", "rs602662", "A;A",
        "Higher vitamin B12 levels (favorable variant in same gene)",
        "nutrient_metabolism", "favorable"),

    snp("SLC23A1", "rs10063949", "T;T",
        "Normal Crohn's disease risk; vitamin C transporter variant",
        "nutrient_metabolism", "neutral"),

    snp("BCMO1", "rs12934922/rs7501331", "T;T/C;C",
        "Normal conversion of beta-carotene into retinal (vitamin A)",
        "nutrient_metabolism", "neutral"),

    snp("CASR", "rs1801725", "G;T",
        "Higher serum calcium levels; potential bone and grip strength implications",
        "nutrient_metabolism", "mixed",
        details="T allele = less active calcium-sensing receptor. Higher extracellular calcium. "
                "Associated with lower grip strength in elderly, possible kidney stone risk, migraine.",
        actionable_recs=[
            "Vitamin K2 supplementation may improve calcium metabolism",
            "K2 directs calcium to bones rather than soft tissue",
            "Monitor serum calcium levels",
            "Maintain hand grip strength through resistance training",
        ],
        related_biomarkers=["calcium"]),

    snp("PEMT", "rs7946", "T;T",
        "Reduced phosphatidylcholine production in liver",
        "nutrient_metabolism", "unfavorable",
        details="PEMT enzyme with partial loss of activity. Phosphatidylcholine essential for cell membranes, "
                "liver function (VLDL secretion), and acetylcholine production (sleep, memory). "
                "Deficiency may contribute to NAFLD.",
        actionable_recs=[
            "Prioritize dietary choline: eggs, meat, fish, cruciferous vegetables",
            "Choline AI for men: 550mg/day — may need more",
            "Important for liver health and sleep quality",
        ],
        related_biomarkers=["choline"]),

    snp("VKORC1", "rs9923231", "C;T",
        "Less efficient vitamin K recycling; slightly increased warfarin sensitivity",
        "nutrient_metabolism", "mixed",
        details="Reduced VKORC1 enzyme production. If ever prescribed warfarin, lower dose may be needed. "
                "Vitamin K1 (leafy greens) and K2 (fermented foods, meat) both important.",
        actionable_recs=[
            "Ensure adequate vitamin K intake (leafy greens, natto, meat, dairy)",
            "If warfarin prescribed, inform physician of this genotype — lower dose likely needed",
        ]),

    snp("AGT", "rs5051", "C;C",
        "Salt-insensitive blood pressure; unresponsive to low sodium diet",
        "nutrient_metabolism", "neutral",
        details="C;C = normal angiotensinogen. Salt reduction primarily benefits T allele carriers. "
                "Blood pressure less responsive to sodium changes.",
        related_biomarkers=["blood_pressure"]),

    snp("TF/HFE", "rs1049296/rs1800562", "C;C/G;G",
        "Normal free iron and normal Alzheimer's disease risk",
        "nutrient_metabolism", "neutral"),

    snp("SLC30A8", "rs13266634", "C;T",
        "Slight increased risk for T2D related to zinc; C allele may need longer recovery after resistance training",
        "nutrient_metabolism", "mixed",
        details="Zinc intake may promote glucose homeostasis. C allele carriers showed more DOMS "
                "after resistance training — may require longer recovery times.",
        actionable_recs=[
            "Adequate zinc intake important for glucose homeostasis",
            "May need longer recovery between resistance training sessions",
        ]),

    # ═══════════════════════════════════════════════
    # ANTIOXIDANT / DETOX
    # ═══════════════════════════════════════════════

    snp("GSTP1", "rs1695", "A;G",
        "Intermediate glutathione S-transferase activity; may benefit from supplemental vitamin E",
        "antioxidant", "mixed",
        details="A;G = intermediate enzyme activity. G;G individuals showed anti-inflammatory benefit "
                "from low-dose vitamin E (75 IU). A;G may partially benefit."),

    snp("SOD2", "rs4880", "C;T",
        "Intermediate superoxide dismutase activity; diet-dependent disease risk",
        "antioxidant", "mixed",
        details="C = higher enzyme activity (more H2O2), T = lower activity (more superoxide). "
                "C;T intermediate. Adequate dietary antioxidants (especially lycopene) important for "
                "C allele carriers. Exercise + calorie reduction beneficial for weight management.",
        actionable_recs=[
            "Adequate dietary antioxidants essential — lycopene (tomatoes), carotenoids",
            "Don't smoke — oxidative burden particularly harmful for C allele",
            "Maintain healthy weight to reduce oxidative stress",
        ]),

    # ═══════════════════════════════════════════════
    # EXERCISE / PERFORMANCE
    # ═══════════════════════════════════════════════

    snp("ACTN3", "rs1815739", "C;T",
        "Intermediate fast-twitch muscle performance",
        "exercise", "neutral",
        details="C allele = sprint/power athlete association. T allele = endurance/fatigue resistance. "
                "C;T heterozygous = intermediate. T;T individuals sustain more muscle damage from "
                "ultra-endurance and may need more recovery. Muscle strength maintenance important for aging.",
        actionable_recs=[
            "Balanced training approach — both power and endurance work appropriate",
            "Maintain/build muscle strength for healthy aging",
        ]),

    snp("ADRB2", "rs1042713", "G;G",
        "Decreased endurance capacity",
        "exercise", "unfavorable",
        details="G allele more frequent in power athletes, less frequent in endurance athletes. "
                "G;G may naturally lean toward power/sprint activities.",
        actionable_recs=[
            "May need to emphasize endurance training more to build aerobic base",
            "Power/sprint training likely a natural strength",
        ]),

    snp("VEGFA", "rs2010963", "C;G",
        "Intermediate aerobic training response",
        "exercise", "neutral",
        details="VEGF involved in angiogenesis during exercise adaptation. G allele may have lower "
                "baseline VO2max but can improve with training intensity increases.",
        actionable_recs=[
            "Higher training intensity may improve aerobic response",
            "Aerobic potential can be enhanced through training regardless of genotype",
        ]),

    snp("PPARGC1A", "rs8192678", "G;G",
        "Normal PGC-1alpha activity; normal exercise adaptation",
        "exercise", "neutral",
        details="PGC-1alpha involved in mitochondrial biogenesis and energy metabolism. G;G is wildtype."),

    snp("HIF1A", "rs11549465", "C;C",
        "Preserves aerobic exercise response with age; more likely endurance athlete",
        "exercise", "favorable",
        details="C;C maintains response to aerobic exercise even with advancing age. "
                "More likely to be an endurance athlete profile."),

    snp("COL5A1", "rs12722", "C;T",
        "Slight increased risk for Achilles tendinopathy and soft tissue injuries",
        "exercise", "unfavorable",
        details="T allele associated with increased risk of tendon/ligament injuries including "
                "Achilles, ACL, and tennis elbow. May also increase exercise-associated muscle cramping risk.",
        actionable_recs=[
            "Prehabilitation exercises — consult PT/trainer",
            "Gradual training load progression",
            "Focus on connective tissue health — collagen, vitamin C",
        ]),

    # ═══════════════════════════════════════════════
    # SLEEP / CIRCADIAN
    # ═══════════════════════════════════════════════

    snp("DEC2", "rs121912617", "C;C",
        "Requires at least 8 hours of sleep per night",
        "sleep", "neutral",
        details="C;C = normal sleep duration requirement (7-9 hours). G allele carriers are natural "
                "short sleepers (4-6 hours) without adverse effects. Routinely sleeping <8 hours "
                "without the short-sleep variant builds sleep deficit with long-term health consequences."),

    snp("ADORA2A", "rs5751876", "C;C",
        "Less anxiety but possible sleep disturbances with caffeine",
        "sleep", "mixed",
        details="C;C associated with less caffeine-induced anxiety vs T allele. However, C;C may "
                "experience more sleep disruption from caffeine than T;T.",
        actionable_recs=[
            "May be less anxious from caffeine but sleep quality could suffer",
            "Consider caffeine curfew (no caffeine after early afternoon)",
        ]),

    snp("ADA", "rs73598374", "G;G",
        "Normal sleep depth and tolerance of sleep deprivation",
        "sleep", "neutral",
        details="G;G = normal adenosine deaminase activity. Normal deep sleep and ability to "
                "tolerate sleep deprivation. Naps may be less impactful vs A allele carriers."),

    snp("PER2", "rs121908635", "A;A",
        "Normal sleep-wake pattern (not extreme early riser)",
        "sleep", "neutral"),

    snp("MTNR1A", "rs12506228", "A;C",
        "Slight increased risk for late-onset Alzheimer's disease",
        "sleep", "unfavorable",
        details="A allele associated with fewer melatonin receptors. More amyloid-beta plaques on autopsy. "
                "Also associated with intolerance to shift work — more fatigue symptoms.",
        actionable_recs=[
            "Protect circadian rhythm — regular sleep/wake schedule",
            "Avoid shift work if possible",
            "Bright light exposure in morning, minimize blue light at night",
        ]),

    snp("MTNR1B", "rs10830963", "C;C",
        "Normal glucose tolerance with late dinner; normal T2D risk",
        "sleep", "neutral",
        details="C;C = no late-meal glucose impairment. G allele carriers should eat dinner 2-4h before bed."),

    # ═══════════════════════════════════════════════
    # CAFFEINE
    # ═══════════════════════════════════════════════

    snp("CYP1A2", "rs762551", "A;A",
        "Fast caffeine metabolizer",
        "caffeine", "favorable",
        details="A;A = fast caffeine metabolism (~1.5h half-life vs ~5h in slow metabolizers). "
                "1-3 cups coffee associated with REDUCED heart attack risk in fast metabolizers. "
                "Coffee associated with blood pressure reduction in fast metabolizers. "
                "Enhanced exercise performance with caffeine.",
        actionable_recs=[
            "Coffee consumption (1-3 cups) likely cardioprotective",
            "Caffeine can enhance exercise performance",
            "Still observe caffeine curfew for sleep quality (ADORA2A interaction)",
        ]),

    # ═══════════════════════════════════════════════
    # TASTE / FOOD PREFERENCES
    # ═══════════════════════════════════════════════

    snp("FGF21", "rs838133", "C;C",
        "Preference for salty over sweet foods",
        "taste", "neutral",
        details="C;C associated with preference for salty vs sweet. T allele associated with "
                "higher carbohydrate and lower protein/fat intake and preference for sweets."),

    snp("CD36", "rs1761667", "A;G",
        "Slight decreased ability to taste fat",
        "taste", "mixed",
        details="A allele = decreased CD36 protein = impaired fat perception. May lead to "
                "tendency to increase fat intake. G;G individuals had 8-fold greater sensitivity to fat taste.",
        actionable_recs=[
            "Be mindful of fat intake — may not perceive fat content as well",
        ]),

    snp("TAS2R38", "rs10246939/rs1726866/rs713598", "C;C/C;C/C;C",
        "Ability to taste bitter compounds (super-taster profile)",
        "taste", "favorable",
        details="Triple homozygous PAV/PAV = can taste bitter compounds like PROP, PTC, and "
                "glucosinolates in cruciferous vegetables. Tasters tend to consume fewer calories, "
                "have lower BMI. May dislike raw cruciferous vegetables.",
        actionable_recs=[
            "Cook or season cruciferous vegetables to reduce bitterness if needed",
            "Natural inclination to moderate calorie intake — leverage this",
        ]),

    snp("TAS2R16", "rs978739", "A;G",
        "Moderate ability to taste certain bitter compounds; associated with normal lifespan",
        "taste", "neutral"),

    snp("MCM6", "rs4988235", "T;T",
        "Lactose tolerant (lactase persistence) in adulthood",
        "taste", "favorable",
        details="T;T = maintains lactase production into adulthood. Can digest dairy without issues. "
                "T allele carriers on low-protein diet may have less fat loss — high-protein diet preferred."),

    snp("OR6A2", "rs72921001", "C;C",
        "Normal cilantro taste perception (does not taste like soap)",
        "taste", "neutral"),

    snp("DRD2", "rs1800497", "C;C",
        "Normal food reward/dopamine response upon eating",
        "taste", "neutral"),

    # ═══════════════════════════════════════════════
    # TELOMERES / LONGEVITY
    # ═══════════════════════════════════════════════

    snp("TERT", "rs2736100", "G;T",
        "Slightly shorter telomere length",
        "longevity", "unfavorable",
        details="Each T allele = ~75bp shorter telomeres = ~3.6 years of biological aging equivalent.",
        actionable_recs=[
            "Stress reduction (meditation, mindfulness)",
            "Diet quality — reduce sugar, processed foods, increase omega-3",
            "Regular exercise",
            "Adequate sleep",
            "Maintain healthy weight",
        ]),

    snp("TERC", "rs12696304", "C;G",
        "Slightly shorter telomere length",
        "longevity", "unfavorable",
        details="G allele = ~75bp shorter per copy = ~3.6 years aging equivalent."),

    snp("TERC", "rs10936599", "C;T",
        "Slightly shorter telomere length",
        "longevity", "unfavorable"),

    snp("ACYP2", "rs11125529", "C;C",
        "Shorter telomere length",
        "longevity", "unfavorable",
        details="Each C allele = ~66.9bp shorter = ~2.23 years aging equivalent."),

    snp("OBFC1", "rs9420907", "A;A",
        "Shorter telomere length",
        "longevity", "unfavorable"),

    snp("RTEL1", "rs755017", "A;A",
        "Shorter telomere length",
        "longevity", "unfavorable",
        details="Each A allele = ~74.1bp shorter = ~2.47 years aging equivalent."),

    snp("NAF1", "rs7675998", "G;G",
        "Normal telomere length",
        "longevity", "neutral"),

    snp("UCP2", "rs659366", "C;T",
        "Longer telomere length; intermediate longevity effect",
        "longevity", "favorable",
        details="T allele associated with increased UCP2 expression, reduced oxidative stress, "
                "longer telomeres. May protect telomeres via reduced mitochondrial ROS."),

    snp("AKT1", "rs3803304", "G;G",
        "May increase lifespan",
        "longevity", "favorable",
        details="G;G associated with increased lifespan via PI3K/AKT/mTOR pathway regulation."),

    snp("IL6", "rs1800795", "G;G",
        "Associated with longer lifespan; increased risk of certain cancers",
        "longevity", "mixed",
        details="G;G = higher IL-6 levels. More likely to reach age 90-95 in studies. "
                "But also increased risk of certain cancers (cervical, breast, colorectal, prostate). "
                "Higher IL-6 is pro-inflammatory but may have complex longevity effects.",
        actionable_recs=[
            "Anti-inflammatory diet and lifestyle to manage IL-6 levels",
            "Regular cancer screening appropriate",
        ]),

    snp("SIRT1", "rs3758391", "C;T",
        "Less mental decline with aging",
        "longevity", "favorable",
        details="T allele carriers demonstrated better cognitive function in study of 1,200+ individuals."),

    snp("FOXO3", "rs2764264", "T;T", "Normal lifespan", "longevity", "neutral"),
    snp("FOXO3", "rs9400239", "C;C", "Normal lifespan", "longevity", "neutral"),
    snp("FOXO3", "rs1935949", "C;C", "Normal lifespan", "longevity", "neutral"),
    snp("FOXO3", "rs2802292", "T;T", "Normal lifespan", "longevity", "neutral"),

    snp("KLOTHO", "rs2542052", "A;C",
        "Intermediate klotho levels",
        "longevity", "neutral",
        details="Klotho is an anti-aging protein. C allele associated with higher klotho and longer lifespan."),

    snp("TP53", "rs1042522", "G;G",
        "Normal lifespan (C allele carriers may live ~3 years longer)",
        "longevity", "neutral"),

    snp("CFH", "rs1061170", "C;T",
        "Normal lifespan; slightly increased risk for age-related macular degeneration",
        "longevity", "mixed",
        details="C allele = 2-4x greater risk of AMD. Complement factor H regulates immune/inflammatory response.",
        actionable_recs=[
            "Regular eye exams especially with aging",
            "Lutein/zeaxanthin supplementation may support macular health",
        ]),

    snp("IGF1R", "rs34516635", "G;G", "Normal lifespan", "longevity", "neutral"),
    snp("CDKN2B_AS1", "rs2811712", "A;A", "Normal risk for physical impairment with age", "longevity", "neutral"),

    # ═══════════════════════════════════════════════
    # IMMUNE / INFLAMMATION
    # ═══════════════════════════════════════════════

    snp("SH2B3", "rs3184504", "C;T",
        "Slight increased risk for celiac disease; may benefit from avoiding gluten",
        "immune", "mixed",
        details="Only one of several celiac risk SNPs. In combination with others, may indicate gluten sensitivity.",
        actionable_recs=[
            "Consider celiac panel if GI symptoms present",
            "Gluten sensitivity possible — trial elimination diet if symptomatic",
        ]),

    snp("IL1A", "rs1800587", "C;T",
        "Associated with increased viral load in SARS-CoV-1 infection",
        "immune", "mixed"),

    snp("IL18", "rs1946518", "T;T",
        "Associated with increased viral load in SARS-CoV-1 infection",
        "immune", "unfavorable",
        details="T;T = reduced IL18 production. Lower innate immune defense against viral infections."),

    snp("IL17A", "rs2275913", "A;G",
        "Reduced risk of developing acute respiratory distress syndrome",
        "immune", "favorable"),

    snp("MBL2", "rs1800450", "G;G",
        "Decreased susceptibility to SARS-CoV-1 infection",
        "immune", "favorable"),

    snp("FGL2", "rs2075761", "C;C",
        "Associated with lower viral load in SARS-CoV-1 infection",
        "immune", "favorable"),

    snp("OAS1", "rs2660", "A;A", "Normal susceptibility to SARS1", "immune", "neutral"),
    snp("TLR4", "rs4986790", "A;A", "Normal risk for septic shock", "immune", "neutral"),
    snp("TMPRSS2", "rs12329760", "C;C",
        "Normal susceptibility to A2a (D614G) strain of SARS-CoV-2",
        "immune", "neutral"),

    # ═══════════════════════════════════════════════
    # MISCELLANEOUS
    # ═══════════════════════════════════════════════

    snp("NPAS2", "rs2305160", "C;C",
        "Circadian-associated increased breast/prostate cancer risk",
        "cancer_risk", "unfavorable",
        details="NPAS2 controls genes involved in cell growth, metabolism, DNA repair. "
                "C;C associated with increased breast and prostate cancer risk via inflammation "
                "and insulin resistance pathways.",
        actionable_recs=[
            "Intermittent fasting may lower biomarkers of inflammation and insulin resistance",
            "Maintain healthy CRP and HbA1c levels",
            "Regular cancer screening",
        ]),

    snp("HSPA1L", "rs2227956", "C;T",
        "Slight susceptibility to noise-induced hearing loss",
        "miscellaneous", "unfavorable",
        details="C allele may generate more HSP70 in noisy environments. Autophagy (fasting, exercise) "
                "may help clear oxidative damage in inner ear cells.",
        actionable_recs=[
            "Ear protection in loud environments",
            "Fasting and exercise increase autophagy — may protect hearing",
        ]),

    snp("COMT", "rs4680", "A;G",
        "Intermediate dopamine levels; moderate placebo/nocebo response",
        "miscellaneous", "neutral",
        details="A;G = intermediate COMT activity. A = higher dopamine (warrior), G = lower (worrier). "
                "Affects pain sensitivity, stress response, cognition, and placebo/nocebo responses."),

    snp("BDNF", "rs6265", "G;G",
        "Normal short-term motor learning and BDNF activation",
        "miscellaneous", "neutral"),

    snp("AKT1", "rs2494732", "C;T",
        "Slightly increased risk of transient cannabis-associated psychosis",
        "miscellaneous", "mixed",
        details="C allele associated with psychotic-like symptoms during cannabis intoxication. "
                "Related to increased dopamine release."),

    snp("ALDH2", "rs671", "G;G",
        "Normal alcohol metabolism (functional ALDH2 enzyme)",
        "miscellaneous", "neutral"),

    snp("CLTCL1", "rs1061325", "T;T",
        "Ancestral genotype — may benefit from limiting processed carbs; fasted exercise beneficial",
        "metabolism", "mixed",
        details="T;T = ancestral 'hunter-gatherer' genotype. May result in raised blood sugars in modern "
                "high-carb environment. Fasted exercise improved oral glucose insulin sensitivity.",
        actionable_recs=[
            "Limit processed carbohydrate intake and added sugars",
            "Fasted exercise may improve glucose sensitivity",
        ]),

    snp("TFAP2B", "rs987237", "A;G",
        "Slight increased obesity risk; diet macronutrient response varies by genotype",
        "metabolism", "unfavorable",
        details="A;G carriers lost more weight on low-fat diet in one study. "
                "G allele carriers regained more weight on high-protein diet.",
        actionable_recs=[
            "Low-fat diet may favor weight loss for A;G genotype",
        ]),

    snp("TCF7L2", "rs7903146", "C;C", "Normal risk for type 2 diabetes", "metabolism", "neutral"),
    snp("TCF7L2", "rs12255372", "G;G", "Normal risk for type 2 diabetes", "metabolism", "neutral"),
]


# Summary record
risk_counts = {}
for s in SNPS:
    rl = s["risk_level"]
    risk_counts[rl] = risk_counts.get(rl, 0) + 1

cat_counts = {}
for s in SNPS:
    c = s["category"]
    cat_counts[c] = cat_counts.get(c, 0) + 1

summary_item = {
    "pk": PK,
    "sk": "SUMMARY",
    "total_snps": len(SNPS),
    "risk_distribution": risk_counts,
    "category_distribution": cat_counts,
    "report_date": "2020-06-19",
    "report_type": "comprehensive_snp_interpretation",
    "report_pages": 49,
    "key_actionable_themes": [
        "Multiple FTO/obesity variants — exercise, high protein, high PUFA, low saturated fat critical",
        "Triple vitamin D deficiency risk — test and supplement aggressively",
        "MTHFR compound heterozygous + MTRR — supplement 5-methylfolate, methylcobalamin, monitor homocysteine",
        "FADS2 poor ALA conversion — prioritize direct EPA/DHA, don't rely on plant omega-3",
        "PPAR-alpha + FADS1 — avoid high saturated fat, favor PUFA; ketogenic high-sat-fat diet detrimental",
        "SLCO1B1 x2 statin sensitivity — if statins needed, rosuvastatin or pravastatin preferred, add CoQ10",
        "Multiple telomere-shortening variants — stress reduction, omega-3, exercise, sleep all critical",
        "CYP1A2 fast caffeine metabolizer — coffee likely cardioprotective at 1-3 cups",
        "5+ choline-related variants — prioritize choline intake (eggs, meat, cruciferous)",
        "ABCG8 elevated LDL — aligns with observed LDL-C climbing trend in lab draws",
    ],
    "blood_type": "A_Rh_D_Positive",
    "blood_type_date": "2010-08-19",
    "updated_at": NOW,
}


ALL_ITEMS = SNPS + [summary_item]


def main():
    write_mode = "--write" in sys.argv

    print("=" * 60)
    print("Life Platform — Genome SNP Seed Script")
    print("=" * 60)
    print(f"Mode: {'WRITE' if write_mode else 'DRY RUN'}")
    print(f"Table: {TABLE_NAME} ({REGION})")
    print(f"Total items: {len(ALL_ITEMS)} ({len(SNPS)} SNPs + 1 summary)")
    print()

    print(f"Risk distribution:")
    for rl, count in sorted(risk_counts.items()):
        print(f"  {rl}: {count}")
    print()
    print(f"Category distribution:")
    for cat, count in sorted(cat_counts.items()):
        print(f"  {cat}: {count}")
    print()

    unfavorable = [s for s in SNPS if s["risk_level"] == "unfavorable"]
    print(f"Unfavorable SNPs ({len(unfavorable)}):")
    for s in unfavorable:
        print(f"  {s['gene']:20s} {s['rsid']:20s} -> {s['summary'][:60]}")
    print()

    total_size = 0
    for item in ALL_ITEMS:
        raw = json.dumps(item, default=str)
        total_size += len(raw.encode("utf-8"))
    print(f"Total data size: {total_size/1024:.1f} KB ({total_size/1024/len(ALL_ITEMS):.1f} KB avg/item)")
    print()

    if not write_mode:
        print("DRY RUN — no data written. Run with --write to seed DynamoDB.")
        return

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE_NAME)

    with table.batch_writer() as batch:
        for i, item in enumerate(ALL_ITEMS):
            batch.put_item(Item=item)
            if (i + 1) % 20 == 0:
                print(f"  Written {i+1}/{len(ALL_ITEMS)}...")

    print(f"  Written {len(ALL_ITEMS)}/{len(ALL_ITEMS)}... done")
    print()
    print(f"Done! {len(ALL_ITEMS)} items written to {TABLE_NAME}.")
    print()
    print("Verification:")
    print(f'  aws dynamodb query --table-name {TABLE_NAME} --key-condition-expression "pk = :pk" \\')
    print(f'    --expression-attribute-values \'{{":pk": {{"S": "{PK}"}}}}\' \\')
    print(f'    --select COUNT --region {REGION}')


if __name__ == "__main__":
    main()
