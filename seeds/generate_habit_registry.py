#!/usr/bin/env python3
"""Generate DynamoDB-formatted habit_registry and save as expression-attribute-values JSON."""
import json, os

def to_ddb(val):
    """Convert Python value to DynamoDB typed JSON."""
    if val is None:
        return {"NULL": True}
    if isinstance(val, bool):
        return {"BOOL": val}
    if isinstance(val, (int, float)):
        return {"N": str(val)}
    if isinstance(val, str):
        return {"S": val}
    if isinstance(val, list):
        return {"L": [to_ddb(v) for v in val]}
    if isinstance(val, dict):
        return {"M": {k: to_ddb(v) for k, v in val.items()}}
    return {"S": str(val)}

# ═══════════════════════════════════════════════════════════════════════════════
# COMPLETE HABIT REGISTRY — 65 habits
# ═══════════════════════════════════════════════════════════════════════════════

habits = {

# ── BATCH 1: MVPs + Vices (15) ────────────────────────────────────────────────

"Out Of Bed Before 5am": {
    "tier": 1, "category": "discipline", "vice": False, "status": "active",
    "applicable_days": "weekdays", "target_frequency": 5, "p40_group": "Discipline",
    "science": "Consistent wake time is the single strongest circadian anchor. Waking before dawn enables morning light exposure at the optimal window and creates a forcing function for evening sleep discipline.",
    "board_member": "Huberman",
    "why_matthew": "The 5am wake creates the container for your entire morning stack. Without it, everything downstream compresses or gets skipped. On weekends, sleeping to 6-6:30am when recovery demands it is a feature, not a failure.",
    "maps_to_primary": "discipline", "maps_to_secondary": ["sleep", "cognitive"],
    "expected_impact": "Morning journal completion, morning stack adherence, sleep onset consistency",
    "evidence_strength": "strong", "friction_level": "high",
    "synergy_group": "morning_stack", "optimal_sequence": "First domino — everything else follows from this",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Primary Exercise": {
    "tier": 0, "category": "training", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 6, "p40_group": "Performance",
    "science": "Exercise is the single highest-ROI longevity intervention. 150 min/week Zone 2 + 2-3x strength is the minimum effective dose for all-cause mortality reduction. Acute effects: BDNF, GLUT4 translocation, cortisol regulation.",
    "board_member": "Attia",
    "why_matthew": "In a 500+ cal deficit, exercise preserves lean mass while losing fat. Without it, you lose muscle alongside fat, tanking metabolic rate and making regain more likely. The non-negotiable that protects the composition of your weight loss.",
    "maps_to_primary": "training", "maps_to_secondary": ["metabolic", "recovery", "mood", "longevity"],
    "expected_impact": "Whoop strain, Strava training load, glucose disposal, next-day HRV, DEXA lean mass",
    "evidence_strength": "strong", "friction_level": "high",
    "synergy_group": None, "optimal_sequence": "After morning light + caffeine. Not within 3hrs of bed.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Walk 5k": {
    "tier": 0, "category": "training", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Performance",
    "science": "NEAT accounts for more daily caloric expenditure than formal exercise. Walking 5k burns 250-400 kcal. Walking speed is the strongest all-cause mortality predictor in gait research.",
    "board_member": "Attia",
    "why_matthew": "At your current weight, the caloric cost of walking is substantial — free deficit without recovery cost. Also your thinking time, podcast time, and the habit that keeps gait metrics strong.",
    "maps_to_primary": "metabolic", "maps_to_secondary": ["mood", "longevity", "cognitive"],
    "expected_impact": "Steps, NEAT calories, walking speed trend, glucose TIR, gait metrics",
    "evidence_strength": "strong", "friction_level": "medium",
    "synergy_group": None, "optimal_sequence": "Post-meal walking improves glucose disposal. Morning or lunch preferred.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Calorie Goal": {
    "tier": 0, "category": "nutrition", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Nutrition",
    "science": "Energy balance is the primary driver of weight change. Sustained 1500 kcal deficit at 1800 kcal/day targets ~3 lbs/week. Protein prioritization (190g) during deficit preserves lean mass.",
    "board_member": "Attia",
    "why_matthew": "This is the engine of your transformation. 117 lbs to lose means roughly 40 weeks of consistent deficit. Every day at target is a day closer to 185. The checkbox is the commitment signal — real tracking happens in MacroFactor.",
    "maps_to_primary": "metabolic", "maps_to_secondary": ["discipline"],
    "expected_impact": "Withings weight trend, energy balance, body composition trajectory",
    "evidence_strength": "strong", "friction_level": "medium",
    "synergy_group": "nutrition_stack", "optimal_sequence": "Log meals in real-time, not retrospectively.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Intermittent Fast 16:8": {
    "tier": 1, "category": "nutrition", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 6, "p40_group": "Nutrition",
    "science": "Time-restricted eating improves insulin sensitivity, reduces late-night caloric intake, and simplifies meal planning during deficit. Autophagy upregulation begins around 14-16 hours. Primary benefit during a cut is behavioral: removes 4+ hours of eating decisions.",
    "board_member": "Attia",
    "why_matthew": "At 1800 cal/day, the eating window compresses meals into a window where you can feel satisfied rather than grazing. The fast also forces the morning stack to happen on an empty stomach, which is better for cortisol/exercise timing.",
    "maps_to_primary": "metabolic", "maps_to_secondary": ["discipline", "nutrition"],
    "expected_impact": "CGM fasting glucose, glucose variability, MacroFactor meal timing",
    "evidence_strength": "moderate", "friction_level": "medium",
    "synergy_group": "nutrition_stack", "optimal_sequence": "Break fast after morning exercise for enhanced GLUT4 uptake.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Morning Sunlight / Luminette Glasses": {
    "tier": 0, "category": "recovery", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Recovery",
    "science": "Morning bright light (10,000+ lux within 30-60 min of waking) is the master circadian zeitgeber. Sets cortisol pulse timing, determines melatonin onset 14-16 hours later. Single most impactful zero-cost intervention for sleep quality.",
    "board_member": "Huberman",
    "why_matthew": "Seattle winter means months of insufficient morning light. Your Eight Sleep data should show sleep onset latency correlating with this habit. The upstream domino for your entire sleep architecture. Luminette glasses remove the weather excuse.",
    "maps_to_primary": "sleep", "maps_to_secondary": ["mood", "recovery"],
    "expected_impact": "Sleep onset latency, deep sleep %, melatonin timing, next-night Eight Sleep score",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": "morning_stack", "optimal_sequence": "Within 30 min of waking, before caffeine. Minimum 10 min.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Hydrate 3L": {
    "tier": 0, "category": "nutrition", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Nutrition",
    "science": "At higher body weights, water requirements increase proportionally. 3L targets adequate hydration for a 250+ lb active male in deficit. Dehydration impairs cognitive performance at just 1-2% body weight loss. Galpin: BW (lbs)/2 = oz per day, plus 16-24oz per hour of exercise.",
    "board_member": "Galpin",
    "why_matthew": "During caloric deficit, thirst signals are blunted and easy to confuse with hunger. Proper hydration reduces phantom hunger, supports kidney function during high protein intake (190g), and keeps blood markers accurate for lab draws.",
    "maps_to_primary": "metabolic", "maps_to_secondary": ["cognitive", "training"],
    "expected_impact": "Apple Health water intake, energy levels, exercise performance, hunger management",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": "nutrition_stack", "optimal_sequence": "16oz on waking. Front-load before noon. Taper after 6pm.",
    "graduation_criteria": "90%+ over 60 days", "scoring_weight": 1.0
},

"No alcohol": {
    "tier": 0, "category": "vice", "vice": True, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Discipline",
    "science": "Even moderate alcohol (1-2 drinks) suppresses REM sleep by 20-40%, raises resting HR 3-7 bpm for 24-48 hours, impairs HRV recovery. No safe dose for longevity — the J-curve is a confound artifact.",
    "board_member": "Walker_Sleep",
    "why_matthew": "Your alcohol-sleep correlation tool already shows the impact. At 1800 cal/day, even two beers is 300 cal of zero-nutrition intake undermining both deficit and recovery. Every drink night shows up as worse HRV, worse recovery, worse sleep efficiency.",
    "maps_to_primary": "sleep", "maps_to_secondary": ["recovery", "metabolic", "discipline"],
    "expected_impact": "REM %, HRV, resting HR, Whoop recovery, next-day energy, deficit adherence",
    "evidence_strength": "strong", "friction_level": "high",
    "synergy_group": None, "optimal_sequence": None,
    "relapse_context_matters": True, "graduation_criteria": None, "scoring_weight": 1.0
},

"No marijuana": {
    "tier": 0, "category": "vice", "vice": True, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Discipline",
    "science": "Cannabis disrupts REM sleep architecture and impairs next-day executive function, motivation, and dopamine baseline. Regular use creates a dopamine deficit state making discipline-dependent habits harder.",
    "board_member": "Huberman",
    "why_matthew": "The discipline multiplier — when this streak is intact, every other habit becomes easier because baseline dopamine and motivation circuitry is functioning properly. When it breaks, you see the cascade: late-night eating, morning sluggishness, skipped exercise.",
    "maps_to_primary": "discipline", "maps_to_secondary": ["sleep", "mood", "cognitive", "metabolic"],
    "expected_impact": "REM %, next-day journal mood, morning stack completion, calorie goal adherence",
    "evidence_strength": "moderate", "friction_level": "high",
    "synergy_group": None, "optimal_sequence": None,
    "relapse_context_matters": True, "graduation_criteria": None, "scoring_weight": 1.0
},

"No sweets": {
    "tier": 1, "category": "vice", "vice": True, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Nutrition",
    "science": "Refined sugar causes rapid glucose spikes (>30 mg/dL) followed by reactive hypoglycemia, driving cravings 2-3 hours later. Habitual sugar downregulates dopamine receptors. During deficit, sugar calories have zero satiety value per calorie.",
    "board_member": "Attia",
    "why_matthew": "Your CGM makes this visible in real-time. At 1800 cal/day, 200 cal of sweets means 200 cal less of protein or fiber-rich food that would keep you full. Discipline and satiety play, not a moral one.",
    "maps_to_primary": "metabolic", "maps_to_secondary": ["nutrition", "discipline"],
    "expected_impact": "CGM glucose spikes, glucose variability (SD), calorie goal adherence",
    "evidence_strength": "strong", "friction_level": "medium",
    "synergy_group": "nutrition_stack", "optimal_sequence": None,
    "relapse_context_matters": True, "graduation_criteria": None, "scoring_weight": 1.0
},

"No solo takeout": {
    "tier": 1, "category": "vice", "vice": True, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Nutrition",
    "science": "Restaurant/takeout meals average 200-400 more calories than home-prepared for similar portions. Sodium 2-3x higher, driving water retention that masks true weight loss. Macro tracking accuracy drops significantly with restaurant food.",
    "board_member": "Attia",
    "why_matthew": "Solo takeout is the impulsive 'I don't feel like cooking' pattern that undermines the deficit. Shared takeout with your girlfriend is social with different dynamics. The 'solo' qualifier catches avoidance/comfort patterns, not all eating out.",
    "maps_to_primary": "nutrition", "maps_to_secondary": ["metabolic", "discipline"],
    "expected_impact": "MacroFactor calorie accuracy, sodium intake, weekly weight trend consistency",
    "evidence_strength": "moderate", "friction_level": "medium",
    "synergy_group": "nutrition_stack", "optimal_sequence": None,
    "relapse_context_matters": True, "graduation_criteria": None, "scoring_weight": 1.0
},

"No Fried Food": {
    "tier": 2, "category": "vice", "vice": True, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Nutrition",
    "science": "Fried foods are calorie-dense (oil absorption adds 100-300 cal), pro-inflammatory (oxidized seed oils), and low-satiety per calorie. During deficit, a poor caloric investment.",
    "board_member": "Attia",
    "why_matthew": "Guardrail, not daily battle. If you're meal-prepping and eating at home, fried food rarely comes up. Tier 2 because hitting calorie and protein targets matters more than any single food avoidance.",
    "maps_to_primary": "nutrition", "maps_to_secondary": ["metabolic"],
    "expected_impact": "Caloric budget efficiency, inflammation markers over time",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "nutrition_stack", "optimal_sequence": None,
    "relapse_context_matters": False, "graduation_criteria": "90%+ over 60 days", "scoring_weight": 1.0
},

"No mindless scrolling": {
    "tier": 1, "category": "vice", "vice": True, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Discipline",
    "science": "Social media exploits variable-ratio dopamine reinforcement — same mechanism as slot machines. Creates low-grade dopamine drip that reduces motivation for effortful activities. Evening scrolling delays sleep onset and suppresses melatonin.",
    "board_member": "Huberman",
    "why_matthew": "The time thief. Every 30 min of scrolling is 30 min not spent on deep work, exercise, reading, or journaling. Directly competes with your evening wind-down — scrolling instead of Evening Breathwork or reading cascades to sleep and recovery.",
    "maps_to_primary": "cognitive", "maps_to_secondary": ["discipline", "sleep", "mood"],
    "expected_impact": "Deep Work Block completion, evening routine adherence, sleep onset latency",
    "evidence_strength": "moderate", "friction_level": "high",
    "synergy_group": None, "optimal_sequence": None,
    "relapse_context_matters": False, "graduation_criteria": None, "scoring_weight": 1.0
},

"No porn": {
    "tier": 1, "category": "vice", "vice": True, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Discipline",
    "science": "Pornography activates supranormal dopamine responses that progressively downregulate receptor sensitivity. Associated with decreased motivation, impaired real-world intimacy. Recovery of dopamine baseline takes 30-90 days of abstinence.",
    "board_member": "Huberman",
    "why_matthew": "Dopamine hygiene habit — protecting reward circuitry so natural rewards (exercise, social connection, creative work, relationship) register at full strength. Like No marijuana, a multiplier that makes other habits easier when the streak is intact.",
    "maps_to_primary": "discipline", "maps_to_secondary": ["mood", "cognitive"],
    "expected_impact": "Baseline motivation, relationship quality, dopamine sensitivity",
    "evidence_strength": "moderate", "friction_level": "medium",
    "synergy_group": None, "optimal_sequence": None,
    "relapse_context_matters": True, "graduation_criteria": None, "scoring_weight": 1.0
},

"No Phone 30 Mins Before Bed": {
    "tier": 1, "category": "vice", "vice": True, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Recovery",
    "science": "Screen use within 30 min of sleep delays melatonin onset by 30-60 min (blue light at close range), increases cognitive arousal. The pre-sleep buffer is the highest-leverage modifiable sleep hygiene behavior after consistent wake time and morning light.",
    "board_member": "Walker_Sleep",
    "why_matthew": "Your Eight Sleep data can validate directly — nights with early phone-down should show shorter onset latency and better deep sleep. Combined with red light glasses and evening breathwork, completes the sleep wind-down stack.",
    "maps_to_primary": "sleep", "maps_to_secondary": ["recovery", "discipline"],
    "expected_impact": "Sleep onset latency, first-cycle deep sleep %, Eight Sleep score",
    "evidence_strength": "strong", "friction_level": "medium",
    "synergy_group": "sleep_stack", "optimal_sequence": "After Evening Journal, phone on charger outside bedroom.",
    "relapse_context_matters": False, "graduation_criteria": "90%+ over 60 days", "scoring_weight": 1.0
},

# ── BATCH 2: Supplements (20) ─────────────────────────────────────────────────

"Creatine": {
    "tier": 1, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "Most studied sports supplement. Increases phosphocreatine stores, supports lean mass retention during deficit, emerging cognitive benefits. One of the few supplements with unambiguous evidence across multiple domains.",
    "board_member": "Attia",
    "why_matthew": "During deficit, creatine is protective — helps preserve the muscle you're working to keep. 5g/day, no loading, no cycling. Cognitive benefit is a bonus during demanding work weeks.",
    "maps_to_primary": "training", "maps_to_secondary": ["cognitive", "longevity"],
    "expected_impact": "Strength performance, lean mass retention on DEXA, cognitive clarity",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": "daily_supps", "optimal_sequence": "Timing doesn't matter. With any meal.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Omega 3": {
    "tier": 1, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "EPA/DHA (2-4g combined) reduces systemic inflammation, improves TG/HDL ratio, supports cell membrane fluidity, cardioprotective. EPA specifically has antidepressant effects at 1g+ doses.",
    "board_member": "Attia",
    "why_matthew": "Your genome shows cardiovascular risk markers and labs track lipids longitudinally. Omega 3 is the supplement most likely to move your TG/HDL ratio over time. Anti-inflammatory effect supports recovery from training.",
    "maps_to_primary": "longevity", "maps_to_secondary": ["recovery", "mood", "metabolic"],
    "expected_impact": "Triglycerides, TG/HDL ratio, hs-CRP, mood stability",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": "daily_supps", "optimal_sequence": "With a fat-containing meal for absorption.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Vitamin D": {
    "tier": 1, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "Vitamin D3 (2000-5000 IU/day) essential for calcium metabolism, immune function, mood regulation. Deficiency 40-50% at northern latitudes. Seattle (47N) produces zero cutaneous vitamin D October-March. Target 40-60 ng/mL.",
    "board_member": "Attia",
    "why_matthew": "Living in Seattle makes this non-optional. Lab trends track 25-OH Vitamin D to confirm range. Combined with Morning Sunlight habit, covers both circadian and nutritional aspects. Take with K2 and fat-containing meal.",
    "maps_to_primary": "longevity", "maps_to_secondary": ["mood", "recovery"],
    "expected_impact": "25-OH Vitamin D lab levels, immune function, mood (especially winter)",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": "daily_supps", "optimal_sequence": "Morning with breakfast. Pair with K2.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Multivitamin": {
    "tier": 2, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "During caloric restriction, micronutrient gaps more likely. Multivitamin serves as nutritional insurance. Evidence in well-nourished populations is weak, but during a 1500 kcal deficit the insurance argument is stronger.",
    "board_member": "Attia",
    "why_matthew": "At 1800 cal/day, you're eating significantly less food than your body is sized for. The multi fills gaps — especially minerals like selenium, manganese. Insurance policy, not performance play.",
    "maps_to_primary": "nutrition", "maps_to_secondary": ["longevity"],
    "expected_impact": "Micronutrient sufficiency, general health insurance",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "daily_supps", "optimal_sequence": "With largest meal for absorption.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Probiotics": {
    "tier": 2, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "Gut microbiome diversity correlates with metabolic health, immune function, mood via gut-brain axis. Evidence is strain-specific and mixed. Fermented foods may be superior to supplements for microbiome diversity.",
    "board_member": "Huberman",
    "why_matthew": "During high-protein deficit, GI comfort matters for adherence. Track whether GI comfort changes on vs off. Candidate for reassessment — consider adding fermented foods as food-first approach.",
    "maps_to_primary": "metabolic", "maps_to_secondary": ["mood"],
    "expected_impact": "GI comfort, digestion quality (subjective journal signal)",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "daily_supps", "optimal_sequence": "With food.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"L-Threonate": {
    "tier": 1, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "Only magnesium form shown to cross the blood-brain barrier effectively. Supports GABA signaling, reduces sleep onset latency, improves sleep quality. Huberman's top sleep supplement recommendation. 80% of Americans are magnesium deficient.",
    "board_member": "Huberman",
    "why_matthew": "Sleep stack anchor. Combined with Apigenin and Glycine, this is Huberman's exact recommended pre-sleep protocol. Your Eight Sleep onset latency data should correlate with adherence to this trio. At your training volume, magnesium depletion through sweat is real.",
    "maps_to_primary": "sleep", "maps_to_secondary": ["recovery", "cognitive"],
    "expected_impact": "Sleep onset latency, deep sleep %, Eight Sleep score, cognitive clarity",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "sleep_supps", "optimal_sequence": "30-60 min before bed. With Apigenin + Glycine.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Apigenin": {
    "tier": 1, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "Flavonoid (50mg) that modulates GABA-A receptors. Reduces sleep onset latency and anxiety without grogginess. Part of Huberman's sleep triad. No tolerance, no dependence.",
    "board_member": "Huberman",
    "why_matthew": "Gentlest member of your sleep stack — best risk/reward ratio. If you only take one sleep supplement on a given night, this is the one.",
    "maps_to_primary": "sleep", "maps_to_secondary": ["mood"],
    "expected_impact": "Sleep onset latency, subjective sleep quality",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "sleep_supps", "optimal_sequence": "30-60 min before bed. With L-Threonate and Glycine.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Glycine": {
    "tier": 1, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "2-3g before bed lowers core body temperature — primary physiological trigger for sleep onset. Also supports collagen synthesis. Synergistic with Eight Sleep cooling.",
    "board_member": "Huberman",
    "why_matthew": "Beautiful synergy with Eight Sleep — both work by lowering core temperature. Your sleep environment analysis should show that Glycine nights + optimal Eight Sleep temp produce best deep sleep. Collagen synthesis bonus for joint health during heavy training.",
    "maps_to_primary": "sleep", "maps_to_secondary": ["recovery"],
    "expected_impact": "Core temp drop, sleep onset latency, deep sleep %, Eight Sleep efficiency",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "sleep_supps", "optimal_sequence": "30-60 min before bed. Completes Huberman triad.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Theanine": {
    "tier": 2, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "L-Theanine (100-200mg) promotes alpha brain waves, reduces anxiety without sedation. Synergistic with caffeine. Huberman warns some people get disruptive vivid dreams — individual response varies.",
    "board_member": "Huberman",
    "why_matthew": "Monitor your response — if Eight Sleep data shows no difference or worse sleep on Theanine nights, candidate for removal. Check with supplement correlation tool.",
    "maps_to_primary": "sleep", "maps_to_secondary": ["cognitive", "mood"],
    "expected_impact": "Subjective anxiety, sleep onset (watch for vivid dream disruption)",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "sleep_supps", "optimal_sequence": "AM with caffeine for focus OR PM for sleep. Pick one.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Inositol": {
    "tier": 2, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "Myo-inositol (2-4g) supports insulin signaling, serotonin receptor sensitivity, has anxiolytic properties. Evidence for metabolic benefit in insulin-resistant populations.",
    "board_member": "Huberman",
    "why_matthew": "During deficit and metabolic transformation, insulin sensitivity is a key lever. CGM data should show whether it's helping glucose disposal. If taking for sleep/anxiety, Eight Sleep correlation is the validation tool.",
    "maps_to_primary": "metabolic", "maps_to_secondary": ["sleep", "mood"],
    "expected_impact": "Glucose variability, insulin sensitivity (CGM proxy), sleep quality if PM",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "daily_supps", "optimal_sequence": "PM if for sleep, AM if for metabolic.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"NAC": {
    "tier": 2, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "N-Acetyl Cysteine (600-1200mg) is a glutathione precursor — body's master antioxidant. Supports liver detoxification, reduces oxidative stress from training, evidence for reducing rumination/compulsive behavior.",
    "board_member": "Attia",
    "why_matthew": "Glutathione support during caloric deficit and high training load makes mechanistic sense. Behavioral benefit (reducing rumination) may support discipline stack. Liver function labs over time are the validation marker.",
    "maps_to_primary": "longevity", "maps_to_secondary": ["recovery", "mood"],
    "expected_impact": "Liver function markers (AST, ALT), oxidative stress, rumination",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "daily_supps", "optimal_sequence": "Empty stomach or light meal. AM preferred.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Zinc Picolinate": {
    "tier": 2, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "Zinc (15-30mg) supports immune function, testosterone production, wound healing. Athletes lose zinc through sweat. Picolinate has superior bioavailability. Excess (>40mg) can deplete copper.",
    "board_member": "Attia",
    "why_matthew": "During deficit + heavy training, zinc depletion through sweat is real. Supports immune resilience and testosterone maintenance during weight loss. Watch copper ratio.",
    "maps_to_primary": "recovery", "maps_to_secondary": ["longevity"],
    "expected_impact": "Immune resilience, testosterone levels, zinc lab levels",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "daily_supps", "optimal_sequence": "With dinner. Separate from calcium/iron by 2 hours.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Basic B Complex": {
    "tier": 2, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "B vitamins are cofactors in energy metabolism, methylation, neurotransmitter synthesis. Depletion risk increases during caloric restriction. B12 and folate important for homocysteine management. MTHFR variants may require methylated forms.",
    "board_member": "Attia",
    "why_matthew": "Your genome includes MTHFR variants — check whether you need methylated forms. Homocysteine lab trend is the validation metric. During deficit, B depletion contributes to fatigue and cognitive fog.",
    "maps_to_primary": "metabolic", "maps_to_secondary": ["cognitive", "longevity"],
    "expected_impact": "Homocysteine levels, energy, cognitive clarity, methylation support",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "daily_supps", "optimal_sequence": "Morning with food. B6 can be stimulating.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Lions Mane": {
    "tier": 2, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 5, "p40_group": "Supplements",
    "science": "Stimulates nerve growth factor (NGF) synthesis, supporting neuroplasticity and cognitive function. Emerging evidence, not yet confirmed in large RCTs.",
    "board_member": "Huberman",
    "why_matthew": "Cognitive performance matters for your Senior Director role. Emerging-evidence supplement — take it, don't stress if missed. Candidate for N=1 experiment validation.",
    "maps_to_primary": "cognitive", "maps_to_secondary": ["longevity"],
    "expected_impact": "Subjective cognitive clarity, focus during deep work",
    "evidence_strength": "emerging", "friction_level": "low",
    "synergy_group": "nootropic_stack", "optimal_sequence": "Morning, with or without food.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Cordyceps": {
    "tier": 2, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 5, "p40_group": "Supplements",
    "science": "May improve oxygen utilization and aerobic performance. Also supports ATP production and has adaptogenic properties. Evidence promising but limited.",
    "board_member": "Galpin",
    "why_matthew": "If you're doing Zone 2, cordyceps theoretically supports the aerobic engine. Evidence is thin. Good N=1 candidate: track HR recovery on vs off weeks. Low downside, unclear upside.",
    "maps_to_primary": "training", "maps_to_secondary": ["metabolic"],
    "expected_impact": "Aerobic performance, HR recovery, Zone 2 efficiency",
    "evidence_strength": "emerging", "friction_level": "low",
    "synergy_group": "nootropic_stack", "optimal_sequence": "Morning, pre-exercise if possible.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Reishi": {
    "tier": 2, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 5, "p40_group": "Supplements",
    "science": "Adaptogenic mushroom with immunomodulatory and calming properties. Traditional use for sleep and stress. Limited clinical evidence.",
    "board_member": "Attia",
    "why_matthew": "Lowest-evidence mushroom supplement. If taking Lions Mane + Cordyceps + Reishi daily, consider whether total cost and pill burden is justified. Candidate for pausing.",
    "maps_to_primary": "sleep", "maps_to_secondary": ["mood"],
    "expected_impact": "Subjective calm, sleep quality (weak expected signal)",
    "evidence_strength": "emerging", "friction_level": "low",
    "synergy_group": "nootropic_stack", "optimal_sequence": "Evening.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Green Tea Phytosome": {
    "tier": 2, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "EGCG in phytosome form supports fat oxidation, thermogenesis, and has antioxidant properties. Modest effect on fat loss (1-2 lbs over 12 weeks).",
    "board_member": "Attia",
    "why_matthew": "During deficit, marginal fat oxidation support is welcome. Insurance, not primary lever. Weight trend is the macro signal; this supplement won't be visible in it.",
    "maps_to_primary": "metabolic", "maps_to_secondary": ["longevity"],
    "expected_impact": "Marginal fat oxidation support, antioxidant status",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "daily_supps", "optimal_sequence": "Morning with food. Contains caffeine.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"L Glutamine": {
    "tier": 2, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 5, "p40_group": "Supplements",
    "science": "Supports gut barrier integrity, immune function during heavy training, muscle recovery. Most abundant amino acid. At 190g protein/day, likely getting adequate glutamine from food.",
    "board_member": "Galpin",
    "why_matthew": "At 190g protein/day, supplemental benefit is likely marginal. Keep if GI comfort is noticeably better. Candidate for 'do I actually need this?' conversation.",
    "maps_to_primary": "recovery", "maps_to_secondary": ["metabolic"],
    "expected_impact": "GI comfort, immune function during hard training blocks",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "daily_supps", "optimal_sequence": "Post-workout or with meal.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Collagen": {
    "tier": 2, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 5, "p40_group": "Supplements",
    "science": "Collagen peptides (10-15g) support joint cartilage, tendon health, skin elasticity. 15g + vitamin C 30-60 min before exercise increases collagen synthesis in tendons/ligaments (Baar research).",
    "board_member": "Galpin",
    "why_matthew": "Long game supplement for you. Losing 117 lbs means significant skin adaptation. Collagen + vitamin C supports the process. Joint protection during high training volume is secondary benefit. Take before training with vitamin C.",
    "maps_to_primary": "longevity", "maps_to_secondary": ["training", "recovery"],
    "expected_impact": "Joint comfort, skin elasticity during weight loss, tendon health",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "daily_supps", "optimal_sequence": "30-60 min before exercise with vitamin C.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Electrolytes": {
    "tier": 1, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Supplements",
    "science": "Sodium, potassium, magnesium depleted through sweat, caloric restriction, and high water intake. Most people training in deficit are electrolyte depleted. Symptoms: fatigue, cramps, headaches, reduced performance.",
    "board_member": "Galpin",
    "why_matthew": "Caloric deficit + hard training + 3L water + sweating = quadruple depletion vector. Fatigue and headaches during deficit may be electrolyte-driven, not calorie-driven. Directly affects training performance and daily energy.",
    "maps_to_primary": "training", "maps_to_secondary": ["recovery", "cognitive"],
    "expected_impact": "Training performance, energy levels, muscle cramps, headache frequency",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": "daily_supps", "optimal_sequence": "Morning on waking. Second serving during/after training.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Protein Supplement": {
    "tier": 1, "category": "supplement", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 6, "p40_group": "Nutrition",
    "science": "Whey/casein supports 190g daily target critical for lean mass preservation during deficit. A protein shake (120-150 cal for 30g) is the most calorie-efficient way to close the gap.",
    "board_member": "Galpin",
    "why_matthew": "At 1800 cal with 190g protein target, you need ~42% calories from protein. Extremely high density. A shake is often the only way to close the gap without exceeding calories. Nutrition tool, not a supplement.",
    "maps_to_primary": "nutrition", "maps_to_secondary": ["training"],
    "expected_impact": "MacroFactor protein hit rate, lean mass retention, satiety",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": "nutrition_stack", "optimal_sequence": "Post-training or where protein gap is largest.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

# ── BATCH 3a: Recovery, Performance, Mindfulness (14) ─────────────────────────

"Cold Shower": {
    "tier": 2, "category": "recovery", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 5, "p40_group": "Recovery",
    "science": "Deliberate cold exposure (1-3 min, 50-60F) increases norepinephrine 200-300% and sustains elevated dopamine for hours. Do NOT use immediately post-strength — blunts hypertrophy signaling.",
    "board_member": "Huberman",
    "why_matthew": "Discipline signal and mood anchor. The morning cold shock resets your neurochemistry. At 5x/week, adaptation benefits without daily pressure. If skipped all week, the Board should ask: avoiding discomfort broadly, or deliberate choice?",
    "maps_to_primary": "mood", "maps_to_secondary": ["recovery", "discipline", "metabolic"],
    "expected_impact": "Journal morning energy, mood scores, HRV (next-day), alertness",
    "evidence_strength": "moderate", "friction_level": "high",
    "synergy_group": "recovery_stack", "optimal_sequence": "Morning, after waking. NOT post-strength. OK after Zone 2.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Sauna": {
    "tier": 2, "category": "recovery", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 3, "p40_group": "Recovery",
    "science": "Sauna 3-4x/week at 80C+ for 15-20 min associated with 40% reduction in all-cause mortality (Laukkanen, 2015). Increases growth hormone, improves cardiovascular compliance, activates heat shock proteins.",
    "board_member": "Attia",
    "why_matthew": "At 3x/week target, this stops being a daily guilt trip and matches the evidence. Rotate recovery modalities based on training load. Cardiovascular benefit is the long-term play.",
    "maps_to_primary": "longevity", "maps_to_secondary": ["recovery", "sleep"],
    "expected_impact": "HRV trend, cardiovascular health, post-training recovery",
    "evidence_strength": "strong", "friction_level": "medium",
    "synergy_group": "recovery_stack", "optimal_sequence": "Post-training or evening. Heat first, then cold.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Normatec Legs": {
    "tier": 2, "category": "recovery", "vice": False, "status": "active",
    "applicable_days": "post_training", "target_frequency": 3, "p40_group": "Recovery",
    "science": "Pneumatic compression enhances venous return, reduces perceived DOMS. Evidence mixed for objective performance improvement. Best as passive recovery on training days.",
    "board_member": "Galpin",
    "why_matthew": "Recovery convenience tool — use on training days while reading or journaling. At 3x/week post-training, it becomes a habit stack. The real value is making you sit still and recover.",
    "maps_to_primary": "recovery", "maps_to_secondary": ["training"],
    "expected_impact": "Subjective DOMS, next-day training readiness",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "recovery_stack", "optimal_sequence": "Post-training evening. Stack with reading.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Theragun": {
    "tier": 2, "category": "recovery", "vice": False, "status": "active",
    "applicable_days": "post_training", "target_frequency": 3, "p40_group": "Recovery",
    "science": "Percussive therapy increases local blood flow, reduces perceived tension, may reduce DOMS. Similar evidence to foam rolling. Best for targeted muscle groups post-training.",
    "board_member": "Galpin",
    "why_matthew": "Use when you need it, not as a daily checkbox. Post-training on the muscle groups you worked. System only counts it on days you exercised, removing false-failure noise on rest days.",
    "maps_to_primary": "recovery", "maps_to_secondary": ["training"],
    "expected_impact": "Subjective muscle tension, DOMS management",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "recovery_stack", "optimal_sequence": "Post-training, target worked groups. 60-90s per group.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Mobility": {
    "tier": 1, "category": "training", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 6, "p40_group": "Performance",
    "science": "Daily mobility work (10-15 min) preserves range of motion, prevents movement compensations that lead to injury. Loss of hip, thoracic, and ankle mobility is a primary aging marker that's fully preventable.",
    "board_member": "Galpin",
    "why_matthew": "At 250+ lbs with heavy training volume, joint stress is real. Mobility protects your ability to keep training — injury insurance. Your gait analysis shows asymmetry data; mobility directly addresses movement quality. 10 minutes is enough.",
    "maps_to_primary": "training", "maps_to_secondary": ["longevity", "recovery"],
    "expected_impact": "Gait asymmetry, injury prevention, training ROM, squat/deadlift quality",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": None, "optimal_sequence": "Pre-training warm-up or standalone morning/evening.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Secondary Exercise": {
    "tier": 2, "category": "training", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 3, "p40_group": "Performance",
    "science": "A second daily movement session (easy cardio, yoga, active recovery) adds NEAT, supports blood flow recovery, provides mental reset. Not a second hard session.",
    "board_member": "Attia",
    "why_matthew": "At 3x/week, captures the days where you do an evening walk, yoga, or active recovery. Shouldn't feel like a second obligation. On rest days this might BE the only session. Don't force on hard training days.",
    "maps_to_primary": "training", "maps_to_secondary": ["metabolic", "recovery"],
    "expected_impact": "NEAT calories, step count, movement score, active recovery",
    "evidence_strength": "strong", "friction_level": "medium",
    "synergy_group": None, "optimal_sequence": "Afternoon or evening, 4+ hours after primary.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Meditate": {
    "tier": 2, "category": "recovery", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 4, "p40_group": "Wellbeing",
    "science": "Mindfulness meditation (10+ min) reduces cortisol, improves prefrontal cortex function, increases HRV. NSDR is the highest-ROI protocol. Consistency (4+ days/week) matters more than duration.",
    "board_member": "Huberman",
    "why_matthew": "Your meditation correlation tool can validate whether meditation days predict better HRV, lower stress, better sleep. At 4x/week, achievable without pressure. NSDR after lunch could help afternoon energy dips.",
    "maps_to_primary": "recovery", "maps_to_secondary": ["mood", "cognitive", "sleep"],
    "expected_impact": "Garmin stress, HRV, Apple Health mindful minutes, journal stress",
    "evidence_strength": "strong", "friction_level": "medium",
    "synergy_group": None, "optimal_sequence": "Post-lunch NSDR or morning for focus.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Morning Breathwork": {
    "tier": 2, "category": "recovery", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 4, "p40_group": "Wellbeing",
    "science": "Morning sympathetic-activating breathwork (Wim Hof, cyclic hyperventilation) increases alertness, adrenaline, cortisol — appropriate for morning cortisol window. Provides deliberate stress inoculation building resilience.",
    "board_member": "Huberman",
    "why_matthew": "Pairs with morning stack — light, cold, breathwork creates cortisol + norepinephrine + dopamine cocktail. At 4x/week, 'when I have time' addition. On rushed mornings, prioritize light and exercise over breathwork.",
    "maps_to_primary": "mood", "maps_to_secondary": ["discipline", "cognitive"],
    "expected_impact": "Morning alertness, stress resilience, journal energy scores",
    "evidence_strength": "moderate", "friction_level": "medium",
    "synergy_group": "morning_stack", "optimal_sequence": "After waking, before or after cold.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Evening Breathwork": {
    "tier": 2, "category": "recovery", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 4, "p40_group": "Recovery",
    "science": "Evening parasympathetic breathwork (physiological sigh, box breathing, 4-7-8) downregulates the autonomic nervous system, reduces cortisol, prepares for sleep. Physiological sigh is the fastest real-time stress reduction tool.",
    "board_member": "Huberman",
    "why_matthew": "Bridge between active day and sleep stack. Combined with No Phone and sleep supplements, completes wind-down transition. Eight Sleep onset latency should correlate with breathwork evenings. Even 5 minutes counts.",
    "maps_to_primary": "sleep", "maps_to_secondary": ["recovery", "mood"],
    "expected_impact": "Sleep onset latency, first-cycle deep sleep, evening heart rate",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "sleep_stack", "optimal_sequence": "30-60 min before bed. After journal, before supps.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Red Light Therapy On Face": {
    "tier": 2, "category": "hygiene", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 4, "p40_group": "Hygiene",
    "science": "Red/near-infrared light (630-850nm) stimulates mitochondrial function, increases ATP production, promotes collagen synthesis. Moderate evidence for anti-aging skin benefits.",
    "board_member": "Huberman",
    "why_matthew": "During significant weight loss, skin quality and collagen support matter. Complements collagen supplementation. At 4x/week, 10-15 min while doing something else. Cumulative exposure, not daily necessity.",
    "maps_to_primary": "longevity", "maps_to_secondary": ["recovery"],
    "expected_impact": "Skin quality (subjective, long-term), collagen support during weight loss",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": None, "optimal_sequence": "Morning or evening. Stack with seated activities.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Nighttime Red Light Blocking Glasses": {
    "tier": 1, "category": "recovery", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Recovery",
    "science": "Blue/green light after sunset suppresses melatonin 50%+. Red-tinted glasses filter this spectrum, preserving natural melatonin rise 2-3 hours before sleep. Second most important light behavior after morning bright light.",
    "board_member": "Huberman",
    "why_matthew": "Evening counterpart to Morning Sunlight — bookending your circadian protocol. In Seattle winters indoors under artificial light from 4pm, these protect 5-6 hours of melatonin production. Eight Sleep should show better onset latency on glasses-wearing nights.",
    "maps_to_primary": "sleep", "maps_to_secondary": ["recovery"],
    "expected_impact": "Sleep onset latency, melatonin timing, Eight Sleep score, deep sleep first cycle",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": "sleep_stack", "optimal_sequence": "Put on at sunset or 2-3 hours before bed.",
    "graduation_criteria": "90%+ over 60 days", "scoring_weight": 1.0
},

"Daytime Glasses Blue Light Blocking": {
    "tier": 2, "category": "hygiene", "vice": False, "status": "active",
    "applicable_days": "weekdays", "target_frequency": 5, "p40_group": "Hygiene",
    "science": "Daytime blue blockers reduce eye strain from screens but do NOT block melatonin-suppressing wavelengths — daytime blue light is actually beneficial for circadian rhythm. Primarily comfort, not circadian.",
    "board_member": "Huberman",
    "why_matthew": "As a Senior Director on screens all day, eye comfort is real. But don't confuse with nighttime glasses. Weekday/work-hours only. If these reduce headaches or eye fatigue, keep; if not, candidate for graduation.",
    "maps_to_primary": "cognitive", "maps_to_secondary": [],
    "expected_impact": "Eye strain, headache frequency (subjective)",
    "evidence_strength": "emerging", "friction_level": "low",
    "synergy_group": None, "optimal_sequence": "During screen work. Remove for outdoor time.",
    "graduation_criteria": "If no subjective benefit after 30 days, consider pausing", "scoring_weight": 0.5
},

"Mouthwash": {
    "tier": 2, "category": "hygiene", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Hygiene",
    "science": "Reduces oral bacterial load and supports gum health. Some antibacterial mouthwashes may disrupt oral nitric oxide production, affecting blood pressure. Use nitric-oxide-friendly formulas.",
    "board_member": "Attia",
    "why_matthew": "Basic oral hygiene. Use nitric-oxide-friendly mouthwash (avoid daily chlorhexidine). Oral microbiome health is an emerging longevity marker. Candidate for graduation once automatic.",
    "maps_to_primary": "longevity", "maps_to_secondary": [],
    "expected_impact": "Oral health, potential BP interaction",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "hygiene_stack", "optimal_sequence": "After brushing, morning and/or evening.",
    "graduation_criteria": "90%+ over 60 days", "scoring_weight": 0.5
},

# ── BATCH 3b: Journaling, Data, Growth, Skincare (15) ─────────────────────────

"Morning Journal": {
    "tier": 1, "category": "growth", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 6, "p40_group": "Wellbeing",
    "science": "Morning journaling activates prefrontal cortex, creates cognitive frame for the day. Gratitude practice is the single highest-ROI positive psychology intervention (Seligman PERMA). Morning pages surface anxiety before it drives unconscious behavior.",
    "board_member": "Jocko",
    "why_matthew": "Where the subjective layer lives. Without entries, the enrichment pipeline has no data, mood/stress/energy trends go blank, and the Board loses your inner state. The act of writing is the intervention.",
    "maps_to_primary": "mood", "maps_to_secondary": ["cognitive", "discipline"],
    "expected_impact": "Journal insights quality, mood trend data, avoidance flag detection, BoD specificity",
    "evidence_strength": "strong", "friction_level": "medium",
    "synergy_group": "morning_stack", "optimal_sequence": "After morning light and breathwork, before deep work. 5-10 min.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Evening Journal": {
    "tier": 1, "category": "growth", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 6, "p40_group": "Wellbeing",
    "science": "Evening reflection provides cognitive closure reducing rumination and improving sleep onset. Writing down worries externalizes them — Pennebaker's research shows expressive writing reduces intrusive thoughts.",
    "board_member": "Jocko",
    "why_matthew": "Captures what the morning entry can't — how the day actually went vs how you planned it. The delta between morning intention and evening reflection is a powerful signal. Gives the enrichment pipeline a full narrative arc.",
    "maps_to_primary": "mood", "maps_to_secondary": ["sleep", "discipline"],
    "expected_impact": "Journal enrichment quality, sleep onset (cognitive closure), pattern detection",
    "evidence_strength": "strong", "friction_level": "medium",
    "synergy_group": "sleep_stack", "optimal_sequence": "Before sleep stack. Part of wind-down routine.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Mood log": {
    "tier": 2, "category": "data", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Data",
    "science": "Ecological momentary assessment — logging mood in real-time produces more accurate emotional data. Enables subjective-objective correlation engine (mood vs HRV, recovery, sleep).",
    "board_member": "Huberman",
    "why_matthew": "Bridges the gap between 'Whoop says recovery 85%' and 'I actually feel terrible.' Sleep state misperception and subjective-objective divergences are the most clinically interesting signals. Keep logging even on neutral days — that's the baseline.",
    "maps_to_primary": "mood", "maps_to_secondary": ["data"],
    "expected_impact": "Journal correlation quality, mood trend accuracy, BoD context",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": None, "optimal_sequence": "Same time daily. Evening preferred for day-summary.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Food Journal": {
    "tier": 1, "category": "data", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Data",
    "science": "Self-monitoring of food intake is the single strongest predictor of weight loss success (Burke et al. 2011). Logging increases awareness and reduces mindless eating.",
    "board_member": "Attia",
    "why_matthew": "This IS your deficit. Without complete logging, MacroFactor data is wrong, energy balance is wrong, calorie goal is meaningless, glucose meal response can't attribute spikes. The data integrity habit — makes everything downstream trustworthy.",
    "maps_to_primary": "nutrition", "maps_to_secondary": ["metabolic", "data"],
    "expected_impact": "MacroFactor completeness, energy balance accuracy, glucose meal response quality",
    "evidence_strength": "strong", "friction_level": "medium",
    "synergy_group": "nutrition_stack", "optimal_sequence": "Log meals in real-time, not retrospectively.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Whoop Journal": {
    "tier": 2, "category": "data", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 5, "p40_group": "Data",
    "science": "Captures binary behavioral signals that feed Whoop's recovery prediction model. Enriches coaching accuracy and provides a second subjective data stream.",
    "board_member": "Attia",
    "why_matthew": "Data hygiene — more complete journal means better recovery predictions. 30-second tap exercise. Candidate for graduation once automatic.",
    "maps_to_primary": "data", "maps_to_secondary": ["recovery"],
    "expected_impact": "Whoop recovery prediction accuracy, behavioral signal capture",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": None, "optimal_sequence": "Morning when Whoop prompts. 30 seconds.",
    "graduation_criteria": "90%+ over 60 days", "scoring_weight": 0.5
},

"Weigh In": {
    "tier": 1, "category": "data", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Data",
    "science": "Daily weighing with rolling averages is superior to weekly weigh-ins for weight management. Day-to-day fluctuations are noise; 7-day and 30-day trend is signal.",
    "board_member": "Attia",
    "why_matthew": "Feeds your weight trajectory, energy balance, and health trajectory tools. Missing days make the trend line less accurate. Same time, same conditions (post-bathroom, pre-food). The act of measuring matters.",
    "maps_to_primary": "data", "maps_to_secondary": ["metabolic"],
    "expected_impact": "Withings completeness, weight trend accuracy, health trajectory",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": "morning_stack", "optimal_sequence": "First thing after waking, after bathroom, before food.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Deep Work Block": {
    "tier": 1, "category": "growth", "vice": False, "status": "active",
    "applicable_days": "weekdays", "target_frequency": 5, "p40_group": "Growth",
    "science": "3-4 hours of uninterrupted cognitively demanding work produces more output than 8 hours of context-switching (Cal Newport). Prefrontal focus capacity is limited and degrades across the day. Morning deep work after cortisol peak is optimal.",
    "board_member": "Jocko",
    "why_matthew": "As a Senior Director, your leverage comes from thinking clearly, not meeting attendance. Deep work blocks protect highest-value cognitive time. When Google Calendar arrives, we can correlate meeting density with deep work and recovery. The 5am wake creates the time.",
    "maps_to_primary": "cognitive", "maps_to_secondary": ["discipline", "growth"],
    "expected_impact": "Professional output quality, skill development, journal satisfaction",
    "evidence_strength": "strong", "friction_level": "high",
    "synergy_group": None, "optimal_sequence": "First 2-3 hours after morning routine. Before meetings.",
    "graduation_criteria": None, "scoring_weight": 1.0
},

"Read A Book (10+ Pages)": {
    "tier": 2, "category": "growth", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 5, "p40_group": "Growth",
    "science": "10+ pages/day compounds to 20-30 books/year. Evening reading supports wind-down as phone replacement — directly competing with No mindless scrolling.",
    "board_member": "Jocko",
    "why_matthew": "Reading is the positive replacement for scrolling. Every night you read instead of scroll, you build the sleep stack AND growth stack. 10 pages is deliberately low-bar. The habit is about opening the book.",
    "maps_to_primary": "growth", "maps_to_secondary": ["sleep", "cognitive"],
    "expected_impact": "Books completed per year, evening routine quality, screen time reduction",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": "sleep_stack", "optimal_sequence": "Evening, after phone goes down. Under warm lighting.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Read News": {
    "tier": 2, "category": "growth", "vice": False, "status": "active",
    "applicable_days": "weekdays", "target_frequency": 5, "p40_group": "Growth",
    "science": "Deliberate, time-boxed news reading (15-20 min) provides context without anxiety spiral. Choose 2-3 quality sources over social media feeds.",
    "board_member": "Jocko",
    "why_matthew": "As a Senior Director, you need to be informed without being consumed. Time-box to morning or lunch, 15-20 min max. Tier 2 because missing a day has zero health impact — professional hygiene only.",
    "maps_to_primary": "cognitive", "maps_to_secondary": ["growth"],
    "expected_impact": "Professional context, informed decision-making",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": None, "optimal_sequence": "Morning with coffee or lunch break. NOT before bed.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Skill development": {
    "tier": 2, "category": "growth", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 3, "p40_group": "Growth",
    "science": "Deliberate practice and continuous skill acquisition maintain neuroplasticity. 30 min/day compounds significantly. Learning generates BDNF and supports cognitive longevity.",
    "board_member": "Jocko",
    "why_matthew": "Could be platform engineering, leadership, coding, or any compounding skill. At 3x/week, realistic alongside training and work. Life Platform sessions count. Track in journal for enrichment pipeline.",
    "maps_to_primary": "growth", "maps_to_secondary": ["cognitive"],
    "expected_impact": "Professional development, neuroplasticity, journal satisfaction themes",
    "evidence_strength": "strong", "friction_level": "medium",
    "synergy_group": None, "optimal_sequence": "During deep work blocks or dedicated evening time.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Write": {
    "tier": 2, "category": "growth", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 3, "p40_group": "Growth",
    "science": "Creative/expressive writing beyond journaling — blog posts, essays, documentation. Writing clarifies thinking, builds communication skills. Distinct from journaling: outward-facing creation, not inward-facing reflection.",
    "board_member": "Jocko",
    "why_matthew": "The habit you mentioned wanting as a reminder, not a daily expectation. At 3x/week, stays visible without guilt. Over time, if you find a rhythm, frequency can increase.",
    "maps_to_primary": "growth", "maps_to_secondary": ["cognitive"],
    "expected_impact": "Creative output, communication skill, knowledge sharing",
    "evidence_strength": "moderate", "friction_level": "medium",
    "synergy_group": None, "optimal_sequence": "During deep work blocks.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Social Gratitude Touchpoint": {
    "tier": 2, "category": "growth", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 4, "p40_group": "Wellbeing",
    "science": "Seligman PERMA: Relationships are the #1 predictor of sustained wellbeing. A daily gratitude touchpoint strengthens social bonds and activates prosocial neural circuits.",
    "board_member": "Huberman",
    "why_matthew": "Your social isolation risk tool exists for a reason. This is the proactive side — reaching out rather than waiting. At 4x/week, a reminder to connect. Journal enrichment captures social quality that this habit feeds.",
    "maps_to_primary": "mood", "maps_to_secondary": ["longevity"],
    "expected_impact": "Social connection trend, journal social quality, PERMA wellbeing",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": None, "optimal_sequence": "Morning or lunch — a quick text takes 30 seconds.",
    "graduation_criteria": None, "scoring_weight": 0.5
},

"Morning Skincare": {
    "tier": 2, "category": "hygiene", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Hygiene",
    "science": "Morning skincare (cleanser, moisturizer, SPF) protects against UV damage and supports skin barrier. SPF daily is highest-evidence anti-aging dermatological intervention.",
    "board_member": "Attia",
    "why_matthew": "During 117 lb weight loss, skin is adapting continuously. SPF every day — even in Seattle. Strong graduation candidate once habitualized.",
    "maps_to_primary": "longevity", "maps_to_secondary": [],
    "expected_impact": "Skin health during weight loss (long-term, subjective)",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": "hygiene_stack", "optimal_sequence": "After shower, before leaving house. 2 minutes.",
    "graduation_criteria": "90%+ over 60 days", "scoring_weight": 0.5
},

"Evening Skincare": {
    "tier": 2, "category": "hygiene", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Hygiene",
    "science": "Evening skincare removes daily pollutants and applies active ingredients during overnight repair window. Retinol is gold-standard anti-aging active.",
    "board_member": "Attia",
    "why_matthew": "Pairs with evening routine. Apply retinol at night when skin repair is most active. Combined with collagen supplementation and red light therapy, comprehensive skin longevity approach during transformation.",
    "maps_to_primary": "longevity", "maps_to_secondary": [],
    "expected_impact": "Skin health during weight loss (long-term, subjective)",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": "hygiene_stack", "optimal_sequence": "Part of evening wind-down. After washing face.",
    "graduation_criteria": "90%+ over 60 days", "scoring_weight": 0.5
},

"Body Skincare": {
    "tier": 2, "category": "hygiene", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 5, "p40_group": "Hygiene",
    "science": "Full-body moisturization supports skin elasticity and barrier function. Particularly relevant during major weight loss where skin is stretching and contracting.",
    "board_member": "Attia",
    "why_matthew": "Specifically relevant to your weight loss — 117 lbs puts extraordinary demand on skin elasticity. Combined with collagen, hydration, and red light therapy, completes the skin support protocol. Post-shower is natural trigger.",
    "maps_to_primary": "longevity", "maps_to_secondary": [],
    "expected_impact": "Skin elasticity during weight loss (long-term, subjective)",
    "evidence_strength": "moderate", "friction_level": "low",
    "synergy_group": "hygiene_stack", "optimal_sequence": "Post-shower when skin is damp.",
    "graduation_criteria": "90%+ over 60 days", "scoring_weight": 0.5
},

"Floss": {
    "tier": 2, "category": "hygiene", "vice": False, "status": "active",
    "applicable_days": "daily", "target_frequency": 7, "p40_group": "Hygiene",
    "science": "Flossing reduces periodontal disease risk. Emerging research links periodontal bacteria to Alzheimer's, cardiovascular inflammation, and systemic inflammation.",
    "board_member": "Attia",
    "why_matthew": "Oral-systemic health connection is real — hs-CRP and cardiovascular markers are downstream of periodontal health. 60-second habit that should be completely automatic. Strong graduation candidate.",
    "maps_to_primary": "longevity", "maps_to_secondary": [],
    "expected_impact": "Periodontal health, systemic inflammation (long-term)",
    "evidence_strength": "strong", "friction_level": "low",
    "synergy_group": "hygiene_stack", "optimal_sequence": "Evening before brushing.",
    "graduation_criteria": "90%+ over 60 days", "scoring_weight": 0.5
},

}

# ═══════════════════════════════════════════════════════════════════════════════
# Convert to DynamoDB JSON and write file
# ═══════════════════════════════════════════════════════════════════════════════

habit_registry_ddb = {}
for name, data in habits.items():
    habit_registry_ddb[name] = to_ddb(data)

output = {":r": {"M": habit_registry_ddb}}

# Write to working directory for aws cli
outdir = "/tmp"
os.makedirs(outdir, exist_ok=True)
outpath = os.path.join(outdir, "habit_registry_values.json")
with open(outpath, "w") as f:
    json.dump(output, f)

# Also write a summary
print(f"Generated registry for {len(habits)} habits")
print(f"Output: {outpath} ({os.path.getsize(outpath):,} bytes)")

# Tier summary
tiers = {0: [], 1: [], 2: []}
vices = []
for name, data in habits.items():
    tiers[data["tier"]].append(name)
    if data.get("vice"):
        vices.append(name)

print(f"\nTier 0 (non-negotiable): {len(tiers[0])}")
print(f"Tier 1 (high priority):  {len(tiers[1])}")
print(f"Tier 2 (aspirational):   {len(tiers[2])}")
print(f"Vices:                   {len(vices)}")
print(f"Total:                   {sum(len(v) for v in tiers.values())}")
