#!/usr/bin/env bash
# Syncs build files from Broforce-Templates (canonical source)
# to all repos in ~/repos that contain copies.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOS_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

TARGETS_FILE="$SCRIPT_DIR/BroforceModBuild.targets"
EXAMPLE_PROPS="$SCRIPT_DIR/LocalBroforcePath.example.props"
MAKEFILE_COMMON="$SCRIPT_DIR/Makefile.common"

echo "Syncing build files from Broforce-Templates..."
echo ""

# Sync BroforceModBuild.targets
find "$REPOS_DIR" -maxdepth 3 -name "BroforceModBuild.targets" -type f 2>/dev/null | while read -r target; do
    [[ "$target" == "$TARGETS_FILE" ]] && continue
    repo_rel="${target#$REPOS_DIR/}"
    cp "$TARGETS_FILE" "$target"
    echo "  $repo_rel"
done

# Sync LocalBroforcePath.example.props
find "$REPOS_DIR" -maxdepth 2 -name "LocalBroforcePath.example.props" -type f 2>/dev/null | while read -r props; do
    [[ "$props" == "$EXAMPLE_PROPS" ]] && continue
    props_rel="${props#$REPOS_DIR/}"
    cp "$EXAMPLE_PROPS" "$props"
    echo "  $props_rel"
done

# Sync Makefile.common
find "$REPOS_DIR" -maxdepth 3 -name "Makefile.common" -type f 2>/dev/null | while read -r makefile; do
    [[ "$makefile" == "$MAKEFILE_COMMON" ]] && continue
    makefile_rel="${makefile#$REPOS_DIR/}"
    cp "$MAKEFILE_COMMON" "$makefile"
    echo "  $makefile_rel"
done

echo ""
echo "Done."
