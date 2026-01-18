#!/bin/bash
# Syncs BroforceModBuild.targets from Broforce-Templates (canonical source)
# to all repos in ~/repos that contain a copy.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOS_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

TARGETS_FILE="$SCRIPT_DIR/BroforceModBuild.targets"
EXAMPLE_PROPS="$SCRIPT_DIR/LocalBroforcePath.example.props"

echo "Syncing build files from Broforce-Templates..."
echo ""

# Find all BroforceModBuild.targets in repos dir, excluding the source
find "$REPOS_DIR" -maxdepth 3 -name "BroforceModBuild.targets" -type f 2>/dev/null | while read -r target; do
    # Skip the source file itself
    [[ "$target" == "$TARGETS_FILE" ]] && continue

    # Get repo name for display
    repo_rel="${target#$REPOS_DIR/}"

    cp "$TARGETS_FILE" "$target"
    echo "  $repo_rel"
done

# Also sync example props to repos that have it
find "$REPOS_DIR" -maxdepth 2 -name "LocalBroforcePath.example.props" -type f 2>/dev/null | while read -r props; do
    # Skip the source file itself
    [[ "$props" == "$EXAMPLE_PROPS" ]] && continue

    props_rel="${props#$REPOS_DIR/}"

    cp "$EXAMPLE_PROPS" "$props"
    echo "  $props_rel"
done

echo ""
echo "Done."
