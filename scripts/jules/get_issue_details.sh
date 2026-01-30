#!/bin/bash
# ==============================================================================
# Script: get_issue_details.sh
# Purpose: Fetch and format GitHub Issue details for Jules implementation.
#
# Usage: ./scripts/get_issue_details.sh <ISSUE_NUMBER>
# Example: ./scripts/get_issue_details.sh 181
#
# Prerequisites:
#   1. GitHub CLI (`gh`) must be installed and authenticated (`gh auth login`).
#   2. Run this script from the project root.
# ==============================================================================

# 1. Validate Input (Strict Integer Check)
if [[ ! "$1" =~ ^[0-9]+$ ]]; then
    echo "❌ Error: Issue Number must be a positive integer."
    echo "Usage: ./scripts/get_issue_details.sh <ISSUE_NUMBER>"
    exit 1
fi

ISSUE_NUM=$1
OUTPUT_DIR="temp/issues"
JSON_FILE="$OUTPUT_DIR/issue_${ISSUE_NUM}_raw.json"

# 2. Setup Workspace
mkdir -p "$OUTPUT_DIR"

echo "🔵 [1/2] Fetching issue #$ISSUE_NUM via GitHub API..."

# 3. Fetch Data
gh issue view "$ISSUE_NUM" --json number,title,body,labels > "$JSON_FILE"

# 4. Validate Fetch
if [ ! -s "$JSON_FILE" ]; then
    echo "❌ Error: Failed to fetch data. File is empty."
    echo "   - Check if Issue #$ISSUE_NUM exists."
    echo "   - Check your internet connection."
    exit 1
fi

echo "🟢 Issue data downloaded to: $JSON_FILE"
echo "🔵 [2/2] Formatting issue for Jules..."

# 5. Parse & Display
poetry run python scripts/jules/parse_issue_for_jules.py "$JSON_FILE"
