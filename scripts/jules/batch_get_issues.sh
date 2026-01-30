#!/bin/bash
# ==============================================================================
# Script: batch_get_issues.sh
# Purpose: Fetch multiple GitHub issues for Jules in one go.
#
# Usage: ./scripts/batch_get_issues.sh <ISSUE_NUM_1> <ISSUE_NUM_2> ...
# Example: ./scripts/batch_get_issues.sh 181 185 188 190
#
# Prerequisites:
#   1. GitHub CLI (`gh`) must be installed and authenticated.
#   2. Run this script from the project root.
# ==============================================================================

if [ $# -eq 0 ]; then
    echo "❌ Error: No issue numbers provided."
    echo "Usage: ./scripts/batch_get_issues.sh <ISSUE_NUM_1> <ISSUE_NUM_2> ..."
    echo "Example: ./scripts/batch_get_issues.sh 181 185 188 190"
    exit 1
fi

echo "🚀 Fetching $# issues for Jules..."
echo ""

SUCCESS_COUNT=0
FAIL_COUNT=0

for ISSUE_NUM in "$@"; do
    if [[ ! "$ISSUE_NUM" =~ ^[0-9]+$ ]]; then
        echo "⚠️  Skipping invalid issue number: $ISSUE_NUM"
        ((FAIL_COUNT++))
        continue
    fi

    echo "📋 Processing issue #$ISSUE_NUM..."
    ./scripts/jules/get_issue_details.sh "$ISSUE_NUM"

    if [ $? -eq 0 ]; then
        ((SUCCESS_COUNT++))
    else
        ((FAIL_COUNT++))
    fi
    echo ""
done

printf '%.0s=' {1..80}
echo ""
echo "✅ Successfully processed: $SUCCESS_COUNT issues"
echo "❌ Failed: $FAIL_COUNT issues"
echo ""
echo "📁 Output files are in: temp/issues/"
echo "   - Raw JSON: issue_<NUM>_raw.json"
echo "   - Formatted: issue_<NUM>.txt"
