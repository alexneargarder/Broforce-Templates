#!/usr/bin/env bash
#
# sync-targets.sh - propagate canonical build files from Broforce-Templates
# to the consumer repos that carry copies of them.
#
# Usage: sync-targets.sh [-n|--dry-run] [--check] [-r|--repo NAME]... [-h|--help]
#
#   -n, --dry-run     Report what would change and print a unified diff for each
#                     differing file. Writes nothing. Always exits 0.
#       --check       Like --dry-run but without diffs; exits 1 if any existing
#                     copy differs from the canonical file. For scripting/CI.
#   -r, --repo NAME   Restrict the sync to consumer NAME. Repeatable. NAME must
#                     be one of the consumers listed in this script.
#   -h, --help        Show this help and exit.
#
# Synced files (canonical copies live in this directory), each checked at a
# fixed location inside every consumer repo:
#   Scripts/BroforceModBuild.targets
#   LocalBroforcePath.example.props
#   Scripts/Makefile.common
#   Scripts/BroforceMods.DotSettings
#
# A file that does not exist in a consumer is reported as "missing" and is never
# created - copy it in by hand if that repo should carry it. A consumer that is
# not checked out on this machine is reported as "absent" and skipped.

set -euo pipefail

# Authoritative list of repos that carry synced copies of the build files;
# adding a new consumer means adding its directory name here.
CONSUMERS=(
    BroforceMods
    Bro-Maker
    Bro-Maker-abilities
    RocketLib
    Rogueforce
    Mods-Broforce
    VojkanBroforceMods
    CustomBros
)

# Fixed location of each synced file inside a consumer repo; the canonical copy
# is the same basename in this directory.
SYNC_PATHS=(
    "Scripts/BroforceModBuild.targets"
    "LocalBroforcePath.example.props"
    "Scripts/Makefile.common"
    "Scripts/BroforceMods.DotSettings"
)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOS_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
# When run from a worktree (<repo>/.worktrees/<name>/Scripts) the grandparent is
# the .worktrees directory; walk out to the real repos root.
if [[ "$(basename "$REPOS_DIR")" == ".worktrees" ]]; then
    REPOS_DIR="$(dirname "$(dirname "$REPOS_DIR")")"
fi

usage() {
    awk 'NR > 2 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"
}

die() {
    echo "error: $*" >&2
    exit 1
}

is_consumer() {
    local candidate="$1" consumer
    for consumer in "${CONSUMERS[@]}"; do
        [[ "$consumer" == "$candidate" ]] && return 0
    done
    return 1
}

DRY_RUN=0
SHOW_DIFF=0
CHECK=0
SELECTED_REPOS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--dry-run)
            DRY_RUN=1
            SHOW_DIFF=1
            ;;
        --check)
            DRY_RUN=1
            CHECK=1
            ;;
        -r|--repo)
            [[ $# -ge 2 ]] || die "$1 requires a repository name"
            SELECTED_REPOS+=("$2")
            shift
            ;;
        -r=*|--repo=*)
            SELECTED_REPOS+=("${1#*=}")
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "error: unknown option: $1" >&2
            echo "" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

if [[ $CHECK -eq 1 ]]; then
    SHOW_DIFF=0
fi

for repo in ${SELECTED_REPOS[@]+"${SELECTED_REPOS[@]}"}; do
    if ! is_consumer "$repo"; then
        echo "error: unknown repo: $repo" >&2
        echo "known consumers: ${CONSUMERS[*]}" >&2
        exit 1
    fi
done

if [[ ${#SELECTED_REPOS[@]} -gt 0 ]]; then
    TARGET_REPOS=("${SELECTED_REPOS[@]}")
else
    TARGET_REPOS=("${CONSUMERS[@]}")
fi

for rel_path in "${SYNC_PATHS[@]}"; do
    canonical="$SCRIPT_DIR/$(basename "$rel_path")"
    [[ -f "$canonical" ]] || die "canonical file missing: $canonical"
done

echo "Syncing build files from Broforce-Templates..."
echo "  canonical: $SCRIPT_DIR"
echo "  repos:     $REPOS_DIR"
if [[ ${#SELECTED_REPOS[@]} -gt 0 ]]; then
    echo "  limited to: ${SELECTED_REPOS[*]}"
fi
if [[ $CHECK -eq 1 ]]; then
    echo "  (check mode - nothing will be written)"
elif [[ $DRY_RUN -eq 1 ]]; then
    echo "  (dry run - nothing will be written)"
fi
echo ""

declare -A UPDATED_COUNT=()
declare -A UNCHANGED_COUNT=()
declare -A MISSING_COUNT=()
declare -A UPDATED_PATHS=()
ABSENT_REPOS=()
PRESENT_REPOS=()
DIFFERENCES=0

for repo in "${TARGET_REPOS[@]}"; do
    repo_dir="$REPOS_DIR/$repo"

    if [[ ! -d "$repo_dir" ]]; then
        echo "$repo"
        echo "  absent        no such directory: $repo_dir"
        echo ""
        ABSENT_REPOS+=("$repo")
        continue
    fi

    echo "$repo"
    PRESENT_REPOS+=("$repo")
    UPDATED_COUNT[$repo]=0
    UNCHANGED_COUNT[$repo]=0
    MISSING_COUNT[$repo]=0
    UPDATED_PATHS[$repo]=""

    for rel_path in "${SYNC_PATHS[@]}"; do
        canonical="$SCRIPT_DIR/$(basename "$rel_path")"
        copy="$repo_dir/$rel_path"

        if [[ ! -f "$copy" ]]; then
            MISSING_COUNT[$repo]=$(( MISSING_COUNT[$repo] + 1 ))
            echo "  missing       $rel_path"
            continue
        fi

        if cmp -s "$canonical" "$copy"; then
            UNCHANGED_COUNT[$repo]=$(( UNCHANGED_COUNT[$repo] + 1 ))
            echo "  unchanged     $rel_path"
            continue
        fi

        DIFFERENCES=1
        UPDATED_COUNT[$repo]=$(( UPDATED_COUNT[$repo] + 1 ))
        UPDATED_PATHS[$repo]+="${rel_path}"$'\n'

        if [[ $DRY_RUN -eq 1 ]]; then
            echo "  would update  $rel_path"
            if [[ $SHOW_DIFF -eq 1 ]]; then
                diff -u "$copy" "$canonical" || true
            fi
        else
            if ! cp "$canonical" "$copy"; then
                die "failed to copy $canonical -> $copy"
            fi
            echo "  updated       $rel_path"
        fi
    done
    echo ""
done

echo "Summary:"
for repo in ${PRESENT_REPOS[@]+"${PRESENT_REPOS[@]}"}; do
    updated="${UPDATED_COUNT[$repo]}"
    unchanged="${UNCHANGED_COUNT[$repo]}"
    missing="${MISSING_COUNT[$repo]}"
    if [[ $DRY_RUN -eq 1 ]]; then
        line="  $repo: $updated would update, $unchanged unchanged"
    else
        line="  $repo: $updated updated, $unchanged unchanged"
    fi
    if [[ $missing -gt 0 ]]; then
        line="$line, $missing missing"
    fi
    echo "$line"

    if [[ $DRY_RUN -eq 0 && $updated -gt 0 ]]; then
        repo_dir="$REPOS_DIR/$repo"
        if git -C "$repo_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
            mapfile -t paths <<< "${UPDATED_PATHS[$repo]%$'\n'}"
            status_out="$(git -C "$repo_dir" status --short -- "${paths[@]}" || true)"
            if [[ -n "$status_out" ]]; then
                echo "$status_out" | sed 's/^/    /'
            else
                echo "    (git reports no changes)"
            fi
        else
            echo "    (not a git repository)"
        fi
    fi
done
for repo in ${ABSENT_REPOS[@]+"${ABSENT_REPOS[@]}"}; do
    echo "  $repo: absent"
done

echo ""
if [[ $CHECK -eq 1 ]]; then
    if [[ $DIFFERENCES -eq 1 ]]; then
        echo "Check failed: copies differ from canonical."
        exit 1
    fi
    echo "Check passed: all existing copies match canonical."
    exit 0
fi

echo "Done."
