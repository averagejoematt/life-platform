"""
Seed 90 days of realistic mock MacroFactor data into DynamoDB.
Simulates Matthew's nutrition pattern: ~2200-2600 kcal/day, high protein (~180g),
moderate carbs, some variance day-to-day, plus realistic food log entries.

Run:  python3 seed_macrofactor_mock.py
"""
import boto3
import random
from datetime import date, timedelta
from decimal import Decimal

DYNAMODB_TABLE = "life-platform"
REGION         = "us-west-2"
PK             = "USER#matthew#SOURCE#macrofactor"

random.seed(42)

FOOD_TEMPLATES = [
    # breakfast
    {"food_name": "Oats (dry)", "time": "07:15", "serving_size": "100g", "calories_kcal": 389, "protein_g": 17, "carbs_g": 66, "fat_g": 7, "fiber_g": 10, "sodium_mg": 6},
    {"food_name": "Whole Milk", "time": "07:15", "serving_size": "240ml", "calories_kcal": 149, "protein_g": 8, "carbs_g": 12, "fat_g": 8, "sodium_mg": 105},
    {"food_name": "Blueberries", "time": "07:15", "serving_size": "100g", "calories_kcal": 57, "protein_g": 0.7, "carbs_g": 14, "fat_g": 0.3, "fiber_g": 2.4, "sodium_mg": 1},
    {"food_name": "Greek Yogurt (0%)", "time": "07:20", "serving_size": "200g", "calories_kcal": 118, "protein_g": 20, "carbs_g": 7, "fat_g": 0.6, "sodium_mg": 60, "calcium_mg": 200},
    {"food_name": "Honey", "time": "07:20", "serving_size": "15g", "calories_kcal": 46, "protein_g": 0.1, "carbs_g": 12, "fat_g": 0, "sugars_g": 12},
    {"food_name": "Eggs, scrambled", "time": "07:30", "serving_size": "3 large", "calories_kcal": 234, "protein_g": 18, "carbs_g": 2, "fat_g": 17, "sodium_mg": 342, "choline_mg": 380},
    # lunch
    {"food_name": "Chicken Breast (grilled)", "time": "12:30", "serving_size": "200g", "calories_kcal": 330, "protein_g": 62, "carbs_g": 0, "fat_g": 7, "sodium_mg": 148, "b3_niacin_mg": 18},
    {"food_name": "Brown Rice (cooked)", "time": "12:30", "serving_size": "200g", "calories_kcal": 218, "protein_g": 4.5, "carbs_g": 46, "fat_g": 1.6, "fiber_g": 1.8, "sodium_mg": 10},
    {"food_name": "Broccoli (steamed)", "time": "12:35", "serving_size": "150g", "calories_kcal": 51, "protein_g": 4.2, "carbs_g": 9, "fat_g": 0.6, "fiber_g": 3.4, "sodium_mg": 45, "vitamin_c_mg": 81},
    {"food_name": "Olive Oil", "time": "12:35", "serving_size": "15ml", "calories_kcal": 119, "protein_g": 0, "carbs_g": 0, "fat_g": 14, "monounsaturated_fat_g": 10, "vitamin_e_mg": 1.9},
    {"food_name": "Salmon (baked)", "time": "12:30", "serving_size": "180g", "calories_kcal": 367, "protein_g": 50, "carbs_g": 0, "fat_g": 18, "omega3_total_g": 3.6, "omega3_dha_g": 1.9, "omega3_epa_g": 1.0, "sodium_mg": 180, "vitamin_d_mcg": 16},
    {"food_name": "Sweet Potato (baked)", "time": "12:35", "serving_size": "150g", "calories_kcal": 129, "protein_g": 2.3, "carbs_g": 30, "fat_g": 0.1, "fiber_g": 3.8, "potassium_mg": 475, "vitamin_a_mcg": 960},
    # snacks
    {"food_name": "Whey Protein Shake", "time": "09:30", "serving_size": "35g scoop + 300ml water", "calories_kcal": 140, "protein_g": 27, "carbs_g": 5, "fat_g": 2, "sodium_mg": 180, "calcium_mg": 150},
    {"food_name": "Almonds", "time": "15:30", "serving_size": "30g", "calories_kcal": 173, "protein_g": 6, "carbs_g": 6, "fat_g": 15, "fiber_g": 3.5, "magnesium_mg": 76, "vitamin_e_mg": 7.3},
    {"food_name": "Apple", "time": "10:00", "serving_size": "1 medium (182g)", "calories_kcal": 95, "protein_g": 0.5, "carbs_g": 25, "fat_g": 0.3, "fiber_g": 4.4, "potassium_mg": 195},
    {"food_name": "Banana", "time": "16:00", "serving_size": "1 medium (118g)", "calories_kcal": 105, "protein_g": 1.3, "carbs_g": 27, "fat_g": 0.4, "fiber_g": 3.1, "potassium_mg": 422, "b6_pyridoxine_mg": 0.43},
    {"food_name": "Cottage Cheese (2%)", "time": "15:00", "serving_size": "200g", "calories_kcal": 180, "protein_g": 24, "carbs_g": 8, "fat_g": 5, "calcium_mg": 140, "sodium_mg": 460},
    # dinner
    {"food_name": "Lean Ground Beef (93%)", "time": "19:00", "serving_size": "200g", "calories_kcal": 300, "protein_g": 44, "carbs_g": 0, "fat_g": 14, "iron_mg": 3.8, "zinc_mg": 8.4, "sodium_mg": 160, "b12_cobalamin_mcg": 2.9},
    {"food_name": "Quinoa (cooked)", "time": "19:05", "serving_size": "185g", "calories_kcal": 222, "protein_g": 8, "carbs_g": 39, "fat_g": 3.6, "fiber_g": 5.2, "magnesium_mg": 118, "phosphorus_mg": 281},
    {"food_name": "Spinach (raw)", "time": "19:05", "serving_size": "80g", "calories_kcal": 18, "protein_g": 2.3, "carbs_g": 2.8, "fat_g": 0.3, "iron_mg": 2.1, "vitamin_k_mcg": 145, "folate_mcg": 145, "magnesium_mg": 24},
    {"food_name": "Avocado", "time": "19:10", "serving_size": "100g", "calories_kcal": 160, "protein_g": 2, "carbs_g": 9, "fat_g": 15, "monounsaturated_fat_g": 10, "potassium_mg": 485, "fiber_g": 6.7},
    {"food_name": "Dark Chocolate (85%)", "time": "20:30", "serving_size": "30g", "calories_kcal": 170, "protein_g": 3, "carbs_g": 13, "fat_g": 13, "fiber_g": 3, "iron_mg": 3.1, "magnesium_mg": 65},
    # drinks
    {"food_name": "Coffee (black)", "time": "04:45", "serving_size": "350ml", "calories_kcal": 5, "protein_g": 0.3, "carbs_g": 0.8, "fat_g": 0, "caffeine_mg": 175},
    {"food_name": "Coffee (black)", "time": "09:00", "serving_size": "250ml", "calories_kcal": 3, "protein_g": 0.2, "carbs_g": 0.5, "fat_g": 0, "caffeine_mg": 125},
]

NUTRIENT_FIELDS = [
    "calories_kcal","protein_g","carbs_g","fat_g","fiber_g","alcohol_g",
    "saturated_fat_g","monounsaturated_fat_g","polyunsaturated_fat_g","trans_fat_g",
    "omega3_total_g","omega3_ala_g","omega3_dha_g","omega3_epa_g","omega6_g",
    "sugars_g","sugars_added_g","starch_g","sodium_mg","potassium_mg","calcium_mg",
    "magnesium_mg","iron_mg","zinc_mg","phosphorus_mg","selenium_mcg","manganese_mg",
    "copper_mg","vitamin_a_mcg","vitamin_c_mg","vitamin_d_mcg","vitamin_e_mg",
    "vitamin_k_mcg","b1_thiamine_mg","b2_riboflavin_mg","b3_niacin_mg",
    "b5_pantothenic_mg","b6_pyridoxine_mg","b12_cobalamin_mcg","folate_mcg",
    "caffeine_mg","cholesterol_mg","choline_mg","water_g",
]

def pick_days_foods():
    foods = [FOOD_TEMPLATES[22], FOOD_TEMPLATES[23]]  # coffees
    if random.random() < 0.6:
        foods += [FOOD_TEMPLATES[0], FOOD_TEMPLATES[1], FOOD_TEMPLATES[2], FOOD_TEMPLATES[3]]
    else:
        foods += [FOOD_TEMPLATES[5], FOOD_TEMPLATES[3]]
    if random.random() < 0.7:
        foods.append(FOOD_TEMPLATES[12])  # whey
    else:
        foods.append(random.choice([FOOD_TEMPLATES[14], FOOD_TEMPLATES[15]]))
    if random.random() < 0.55:
        foods += [FOOD_TEMPLATES[6], FOOD_TEMPLATES[7], FOOD_TEMPLATES[8], FOOD_TEMPLATES[9]]
    else:
        foods += [FOOD_TEMPLATES[10], FOOD_TEMPLATES[11]]
    foods.append(random.choice([FOOD_TEMPLATES[13], FOOD_TEMPLATES[16]]))
    if random.random() < 0.6:
        foods += [FOOD_TEMPLATES[17], FOOD_TEMPLATES[18], FOOD_TEMPLATES[19]]
    else:
        foods += [FOOD_TEMPLATES[6], FOOD_TEMPLATES[19], FOOD_TEMPLATES[20]]
    if random.random() < 0.4:
        foods.append(FOOD_TEMPLATES[21])
    return foods

def scale_food(food, scale=1.0):
    f = dict(food)
    for k in NUTRIENT_FIELDS:
        if k in f:
            f[k] = round(f[k] * scale, 2)
    return f

def sum_totals(foods):
    totals = {}
    for food in foods:
        for k in NUTRIENT_FIELDS:
            if k in food:
                totals[k] = round(totals.get(k, 0) + food[k], 2)
    return totals

def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4)))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimal(i) for i in obj]
    return obj

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)

end_date = date(2026, 2, 21)
start_date = end_date - timedelta(days=89)

print(f"Seeding 90 days of mock MacroFactor data ({start_date} → {end_date})...")
written = 0
for i in range(90):
    day = start_date + timedelta(days=i)
    date_str = day.isoformat()

    scale = random.gauss(1.0, 0.12)
    scale = max(0.7, min(1.3, scale))

    foods = pick_days_foods()
    foods = [scale_food(f, scale) for f in foods]
    totals = sum_totals(foods)

    food_log = sorted(foods, key=lambda x: x.get("time", "00:00"))

    item = {
        "pk": PK,
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "source": "macrofactor",
        "ingested_at": "2026-02-22T23:00:00Z",
        "entries_count": len(food_log),
        "food_log": food_log,
    }
    for k, v in totals.items():
        item[f"total_{k}"] = v

    table.put_item(Item=floats_to_decimal(item))
    written += 1
    if written % 10 == 0 or written == 90:
        print(f"  [{written}/90] {date_str}  cal={totals.get('calories_kcal',0):.0f}  P={totals.get('protein_g',0):.0f}g  C={totals.get('carbs_g',0):.0f}g  F={totals.get('fat_g',0):.0f}g")

print(f"\n✓ Done — {written} days seeded")
