## SCHEMA.md Addition — Labs Source

Add this section after the existing source field references:

---

### labs
Blood work and lab results from clinical testing. Each draw date gets its own item.
Supports multiple lab providers and platforms (Function Health, Inside Tracker, GP panels, etc.)

**Key Pattern:**
- PK: `USER#matthew#SOURCE#labs`
- SK: `DATE#YYYY-MM-DD` (per draw date) or `META#<platform>-<year>` (platform summary)

**Draw-Level Fields (SK = DATE#YYYY-MM-DD):**
| Field | Type | Description |
|-------|------|-------------|
| `date` | string | Draw date (YYYY-MM-DD) |
| `source` | string | Always "labs" |
| `lab_provider` | string | Lab that ran tests (e.g., "Quest Diagnostics") |
| `ordering_platform` | string | Service that ordered tests (e.g., "Function Health") |
| `ordering_physician` | string | Ordering physician name |
| `specimen_id` | string | Lab specimen/accession number |
| `lab_ref` | string | Lab reference number |
| `collected_utc` | string | ISO timestamp of blood draw |
| `reported_utc` | string | ISO timestamp of final report |
| `fasting` | boolean | Whether patient was fasting |
| `biomarker_count` | number | Total biomarkers in this draw |
| `out_of_range_count` | number | Count of out-of-range results |
| `biomarkers` | list | Array of biomarker objects (see below) |
| `urinalysis` | map | Optional urinalysis results |
| `genetics` | map | Optional genetic marker results |

**Biomarker Object:**
| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Biomarker name (e.g., "ApoB") |
| `value` | number/string | Result value (string for qualitative like "<10") |
| `unit` | string | Unit of measurement |
| `reference_range` | string | Normal range (e.g., "3.8-10.8") |
| `flag` | string | "normal", "high", or "low" |
| `category` | string | Grouping category (see list below) |
| `notes` | string | Optional clinical context |

**Categories:**
`autoimmunity`, `blood`, `blood_type`, `electrolytes`, `environmental_toxins`, `fatty_acids`, `heart`, `hormones`, `immune`, `inflammation`, `iron`, `kidney`, `liver`, `male_health`, `metabolic`, `nutrients`, `pancreas`, `prostate`, `stress`, `thyroid`

**Meta-Level Fields (SK = META#<platform>-<year>):**
| Field | Type | Description |
|-------|------|-------------|
| `platform` | string | Testing platform name |
| `test_dates` | list | Dates of blood draws |
| `total_biomarkers` | number | Total unique biomarkers tested |
| `out_of_range` | number | Total out-of-range results |
| `biological_age_offset_years` | number | Biological vs chronological age delta |
| `clinician_summary` | string | Clinician notes summary |
| `supplements_recommended` | map | Top 5 and full supplement list |
| `foods_enjoy_top5` | list | Top 5 recommended foods |
| `foods_limit_top5` | list | Top 5 foods to limit |
| `focus_areas` | list | Clinical priority areas with severity and recommendations |

---

Add `labs` to the Valid source identifiers line:
```
Valid source identifiers: `whoop`, `withings`, `strava`, `todoist`, `apple_health`, `hevy`, `eightsleep`, `chronicling`, `macrofactor`, `garmin`, `habitify`, `labs`
```
