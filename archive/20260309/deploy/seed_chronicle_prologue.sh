#!/bin/bash
# Seed Week 0 prologue into DynamoDB for chronicle continuity
# The Lambda reads previous installments from this partition
#
# Usage: bash deploy/seed_chronicle_prologue.sh

set -euo pipefail

REGION="us-west-2"
TABLE="life-platform"

echo "Seeding Week 0 prologue into DynamoDB..."

# Read the prologue content
CONTENT=$(cat blog/week-00.html | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")

aws dynamodb put-item \
    --table-name "$TABLE" \
    --region "$REGION" \
    --item "{
        \"PK\": {\"S\": \"USER#matthew#SOURCE#chronicle\"},
        \"SK\": {\"S\": \"DATE#2026-02-28\"},
        \"date\": {\"S\": \"2026-02-28\"},
        \"source\": {\"S\": \"chronicle\"},
        \"week_number\": {\"N\": \"0\"},
        \"title\": {\"S\": \"Before the Numbers\"},
        \"stats_line\": {\"S\": \"\"},
        \"content_markdown\": {\"S\": \"Prologue — Elena introduces herself, the series, and Matthew. Sets up the central question: What happens when a person who has been losing the fight against himself decides to let algorithms into the ring? Elena is skeptical of optimization culture but intrigued by Matthew's system because it tracks vulnerability (journals, mood, avoidance flags) not just metrics. She has full access to everything. The deal is simple: she writes what she sees.\"},
        \"word_count\": {\"N\": \"1650\"},
        \"has_board_interview\": {\"BOOL\": false},
        \"series_title\": {\"S\": \"The Measured Life\"},
        \"author\": {\"S\": \"Elena Voss\"},
        \"generated_at\": {\"S\": \"2026-02-28T19:00:00Z\"}
    }" \
    --no-cli-pager

echo "✓ Week 0 prologue seeded"
echo "  PK: USER#matthew#SOURCE#chronicle"
echo "  SK: DATE#2026-02-28"
echo ""
echo "  The Lambda will pick this up as previous context for Week 1."
