#!/bin/bash
# Syncs BroforceModBuild.targets and LocalBroforcePath.example.props from
# Broforce-Templates (canonical source) to all other Broforce repos.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOS_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

TARGETS_FILE="$SCRIPT_DIR/BroforceModBuild.targets"
EXAMPLE_PROPS="$SCRIPT_DIR/LocalBroforcePath.example.props"

REPOS=(
    "BroforceMods"
    "RocketLib"
    "Bro-Maker"
)

echo "Syncing build files from Broforce-Templates..."
echo ""

for repo in "${REPOS[@]}"; do
    REPO_PATH="$REPOS_DIR/$repo"

    if [ ! -d "$REPO_PATH" ]; then
        echo "  SKIP: $repo (not found)"
        continue
    fi

    # Copy targets file
    if [ -d "$REPO_PATH/Scripts" ]; then
        cp "$TARGETS_FILE" "$REPO_PATH/Scripts/"
        echo "  $repo/Scripts/BroforceModBuild.targets"
    fi

    # Copy example props to repo root
    cp "$EXAMPLE_PROPS" "$REPO_PATH/LocalBroforcePath.example.props"
    echo "  $repo/LocalBroforcePath.example.props"
done

echo ""
echo "Done. Verify with: md5sum */Scripts/BroforceModBuild.targets */LocalBroforcePath.example.props"
