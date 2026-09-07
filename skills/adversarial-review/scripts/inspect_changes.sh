#!/usr/bin/env bash
# ==============================================================================
# inspect_changes.sh — Change Inspector for Adversarial Review Orchestrator
#
# Provides the Principal Reviewer with an immediate, high-signal overview:
#   - Branch & Base branch
#   - Categorized changed files (Added, Modified, Deleted, Renamed)
#   - Diff statistics
#   - Intelligent review mode triggers (concurrency, config, migrations, contracts)
#   - Relevant tests mapping (updated, untouched, or missing tests)
#   - Potentially affected callers across the codebase
#   - Full unified diff
# ==============================================================================

set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Error: Not inside a git repository." >&2
    exit 1
fi

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

# --- 1. Parse Arguments ---
PRINT_DIFF=true
TARGET_DIFF=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-diff)
            PRINT_DIFF=false
            shift
            ;;
        --full-diff)
            PRINT_DIFF=true
            shift
            ;;
        -h|--help)
            echo "Usage: ./inspect_changes.sh [OPTIONS] [TARGET]"
            echo ""
            echo "Arguments:"
            echo "  TARGET       Commit range or branch (e.g. 'main...HEAD', 'HEAD~1', 'abc1234')"
            echo "               Default: Auto-detects uncommitted changes or branch diff vs main"
            echo ""
            echo "Options:"
            echo "  --no-diff    Omit the full unified diff output"
            echo "  --full-diff  Print the full unified diff output (default)"
            echo "  -h, --help   Show this help message"
            exit 0
            ;;
        *)
            TARGET_DIFF="$1"
            shift
            ;;
    esac
done

# --- 2. Resolve Branch, Base & Target Scope ---
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "HEAD")

BASE_BRANCH="main"
if ! git rev-parse --verify "refs/heads/$BASE_BRANCH" >/dev/null 2>&1 && \
   ! git rev-parse --verify "refs/remotes/origin/$BASE_BRANCH" >/dev/null 2>&1; then
    if git rev-parse --verify "refs/heads/master" >/dev/null 2>&1 || \
       git rev-parse --verify "refs/remotes/origin/master" >/dev/null 2>&1; then
        BASE_BRANCH="master"
    else
        BASE_BRANCH=""
    fi
fi

UNCOMMITTED_COUNT=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')

if [[ -n "$TARGET_DIFF" ]]; then
    MODE="EXPLICIT_TARGET"
    DIFF_SPEC="$TARGET_DIFF"
elif [[ "$UNCOMMITTED_COUNT" -gt 0 ]]; then
    MODE="WORKING_TREE"
    DIFF_SPEC="HEAD"
elif [[ -n "$BASE_BRANCH" && "$CURRENT_BRANCH" != "$BASE_BRANCH" ]]; then
    MODE="BRANCH_DIFF"
    DIFF_SPEC="$BASE_BRANCH...HEAD"
else
    MODE="LAST_COMMIT"
    DIFF_SPEC="HEAD~1..HEAD"
fi

echo "================================================================================"
echo "               ADVERSARIAL REVIEW: CHANGE INSPECTOR REPORT                      "
echo "================================================================================"
echo "Branch: $CURRENT_BRANCH"
if [[ -n "$BASE_BRANCH" ]]; then
    echo "Base:   $BASE_BRANCH"
fi
echo "Scope:  $DIFF_SPEC ($MODE)"
echo ""

# --- 3. Categorized Changed Files ---
echo "Changed files:"

ADDED_FILES=()
MODIFIED_FILES=()
DELETED_FILES=()
RENAMED_FILES=()

if [[ "$MODE" == "WORKING_TREE" ]]; then
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        STATUS_CODE="${line:0:2}"
        FILE_PATH="${line:3}"
        FILE_PATH="${FILE_PATH%\"}"
        FILE_PATH="${FILE_PATH#\"}"

        if [[ "$STATUS_CODE" =~ \?\?|A ]]; then
            ADDED_FILES+=("$FILE_PATH")
        elif [[ "$STATUS_CODE" =~ D ]]; then
            DELETED_FILES+=("$FILE_PATH")
        elif [[ "$STATUS_CODE" =~ R ]]; then
            RENAMED_FILES+=("$FILE_PATH")
        else
            MODIFIED_FILES+=("$FILE_PATH")
        fi
    done < <(git status --porcelain)
else
    while IFS=$'\t' read -r status file1 file2; do
        [[ -z "$status" ]] && continue
        case "${status:0:1}" in
            A) ADDED_FILES+=("$file1") ;;
            M) MODIFIED_FILES+=("$file1") ;;
            D) DELETED_FILES+=("$file1") ;;
            R) RENAMED_FILES+=("$file2 (from $file1)") ;;
            *) MODIFIED_FILES+=("$file1") ;;
        esac
    done < <(git diff --name-status "$DIFF_SPEC" 2>/dev/null || true)
fi

echo "Added:"
if [[ ${#ADDED_FILES[@]} -gt 0 ]]; then
    for f in "${ADDED_FILES[@]}"; do echo "  + $f"; done
else
    echo "  (none)"
fi

echo "Modified:"
if [[ ${#MODIFIED_FILES[@]} -gt 0 ]]; then
    for f in "${MODIFIED_FILES[@]}"; do echo "  * $f"; done
else
    echo "  (none)"
fi

echo "Deleted:"
if [[ ${#DELETED_FILES[@]} -gt 0 ]]; then
    for f in "${DELETED_FILES[@]}"; do echo "  - $f"; done
else
    echo "  (none)"
fi

if [[ ${#RENAMED_FILES[@]} -gt 0 ]]; then
    echo "Renamed:"
    for f in "${RENAMED_FILES[@]}"; do echo "  -> $f"; done
fi
echo ""

ALL_CHANGED_FILES=()
if [[ ${#ADDED_FILES[@]} -gt 0 ]]; then
    for f in "${ADDED_FILES[@]}"; do ALL_CHANGED_FILES+=("$f"); done
fi
if [[ ${#MODIFIED_FILES[@]} -gt 0 ]]; then
    for f in "${MODIFIED_FILES[@]}"; do ALL_CHANGED_FILES+=("$f"); done
fi

# --- 4. Diff Statistics ---
echo "Diff statistics:"
if [[ "$MODE" == "WORKING_TREE" ]]; then
    git diff --stat HEAD 2>/dev/null || true
    if [[ ${#ADDED_FILES[@]} -gt 0 ]]; then
        echo "  (${#ADDED_FILES[@]} untracked/added file(s) outside working tree git diff)"
    fi
else
    git diff --stat "$DIFF_SPEC" 2>/dev/null || true
fi
echo ""

# --- 5. Intelligent Review Mode Triggers ---
echo "Suggested Review Modes:"
TRIGGERS_COUNT=0

files_match() {
    local pattern="$1"
    if [[ ${#ALL_CHANGED_FILES[@]} -gt 0 ]]; then
        for f in "${ALL_CHANGED_FILES[@]}"; do
            if [[ "$f" =~ $pattern ]]; then return 0; fi
        done
    fi
    return 1
}

diff_contains() {
    local regex="$1"
    if [[ "$MODE" == "WORKING_TREE" ]]; then
        git diff HEAD 2>/dev/null | grep -q -E "$regex" && return 0
        if [[ ${#ADDED_FILES[@]} -gt 0 ]]; then
            for f in "${ADDED_FILES[@]}"; do
                if [[ -f "$f" ]] && grep -q -E "$regex" "$f" 2>/dev/null; then return 0; fi
            done
        fi
        return 1
    else
        git diff "$DIFF_SPEC" 2>/dev/null | grep -q -E "$regex" && return 0
        return 1
    fi
}

if files_match "(pom\.xml|build\.gradle|package\.json|package-lock\.json|requirements.*\.txt|Pipfile|go\.mod|Cargo\.toml)"; then
    echo "  [!] DEPENDENCY REVIEW: Build / dependency manifests modified (check new deps, versions, CVEs, licenses)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if files_match "(application.*\.ya?ml|application.*\.properties|\.env.*|config\.(py|go|ts|js)|settings\.json|Config\.java)"; then
    echo "  [!] CONFIG REVIEW: Application configuration modified (verify default values, env var overrides, secrets safety)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if files_match "(db/migration/|migrations/|V[0-9]+__.*\.sql|schema\.prisma|alembic/)"; then
    echo "  [!] MIGRATION REVIEW: Database migrations / SQL changed (check Flyway checksums, query index coverage, table lock hazards)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if diff_contains "\b(synchronized|ReentrantLock|Lock|ConcurrentHashMap|AtomicReference|AtomicBoolean|AtomicInteger|AsyncKeyedLock|asyncio\.Lock|Mutex|RWMutex)\b"; then
    echo "  [!] CONCURRENCY REVIEW: Mutexes, locks, or atomic collections in diff (scrutinize deadlock, reentrancy, double release, atomicity)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if diff_contains "\b(Executor|CompletableFuture|VirtualThread|Thread\.start|run_in_threadpool|asyncio\.create_task|BackgroundTasks|goroutine|\bgo [a-zA-Z0-9_]+)\b"; then
    echo "  [!] THREAD / ASYNC LIFECYCLE REVIEW: Background tasks, thread pools, or async tasks (check unhandled errors, task cancellation, carrier pinning)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if files_match "(Controller|Resource|Endpoint|routes|api/|\.proto)" || diff_contains "(@RestController|@Controller|@Get|@Post|@Put|@Delete|@Path|@app\.(get|post|put|delete)|router\.(get|post))"; then
    echo "  [!] CONTRACT REVIEW: API controllers / routing modified (check backwards compatibility, status codes, query params, schema serialization)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if diff_contains "\b(BigDecimal|stopLoss|trailing_sl|entryPrice|orderPrice|tradedPrice|ltp|premium|lotSize|qty|pnl)\b"; then
    echo "  [!] FINANCIAL / PRECISION REVIEW: Pricing, stop-loss, or quantity logic modified (verify float safety, division by zero, domain separation)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if [[ "$TRIGGERS_COUNT" -eq 0 ]]; then
    echo "  Standard review pipeline (no specialized triggers activated)."
fi
echo ""

# --- 6. Relevant Tests Mapping ---
echo "Relevant tests:"
PROD_FILES=()

if [[ ${#ALL_CHANGED_FILES[@]} -gt 0 ]]; then
    for f in "${ALL_CHANGED_FILES[@]}"; do
        if [[ "$f" =~ Test|test|spec|\.md|\.ya?ml|\.sql|\.json|\.xml|\.properties ]]; then
            continue
        fi
        PROD_FILES+=("$f")
    done
fi

if [[ ${#PROD_FILES[@]} -eq 0 ]]; then
    echo "  (No production source files changed)"
else
    for prod in "${PROD_FILES[@]}"; do
        BASE_NAME=$(basename "$prod")
        STEM="${BASE_NAME%.*}"
        EXT="${BASE_NAME##*.}"

        MATCHING_TESTS=()

        # 1. Search tracked git files
        if [[ "$EXT" == "java" ]]; then
            while IFS= read -r t; do
                [[ -n "$t" ]] && MATCHING_TESTS+=("$t")
            done < <(git ls-files "*${STEM}Test.java" "*${STEM}IT.java" 2>/dev/null || true)
        elif [[ "$EXT" == "py" ]]; then
            while IFS= read -r t; do
                [[ -n "$t" ]] && MATCHING_TESTS+=("$t")
            done < <(git ls-files "*test_${STEM}.py" "*${STEM}_test.py" 2>/dev/null || true)
        elif [[ "$EXT" =~ ts|js ]]; then
            while IFS= read -r t; do
                [[ -n "$t" ]] && MATCHING_TESTS+=("$t")
            done < <(git ls-files "*${STEM}.spec.*" "*${STEM}.test.*" 2>/dev/null || true)
        fi

        # 2. Also check untracked added files on disk
        if [[ ${#ADDED_FILES[@]} -gt 0 ]]; then
            for added in "${ADDED_FILES[@]}"; do
                if [[ "$added" =~ ${STEM}(Test|IT|_test|\.spec|\.test) ]]; then
                    ALREADY_FOUND=false
                    if [[ ${#MATCHING_TESTS[@]} -gt 0 ]]; then
                        for existing in "${MATCHING_TESTS[@]}"; do
                            if [[ "$existing" == "$added" ]]; then ALREADY_FOUND=true; break; fi
                        done
                    fi
                    if [[ "$ALREADY_FOUND" == "false" ]]; then
                        MATCHING_TESTS+=("$added")
                    fi
                fi
            done
        fi

        if [[ ${#MATCHING_TESTS[@]} -eq 0 ]]; then
            echo "  [MISSING TEST] $prod"
            echo "                 -> No test file found matching '${STEM}Test'!"
        else
            for test_file in "${MATCHING_TESTS[@]}"; do
                IS_IN_DIFF=false
                if [[ ${#ALL_CHANGED_FILES[@]} -gt 0 ]]; then
                    for changed in "${ALL_CHANGED_FILES[@]}"; do
                        if [[ "$changed" == "$test_file" ]]; then
                            IS_IN_DIFF=true
                            break
                        fi
                    done
                fi

                if [[ "$IS_IN_DIFF" == "true" ]]; then
                    echo "  [UPDATED TEST] $prod"
                    echo "                 -> $test_file (modified / added in this change)"
                else
                    echo "  [UNTOUCHED]    $prod"
                    echo "                 -> $test_file (exists, but NOT updated in this change - check for behavioral tests)"
                fi
            done
        fi
    done
fi
echo ""

# --- 7. Potentially Affected Callers ---
echo "Potentially affected callers:"
if [[ ${#PROD_FILES[@]} -eq 0 ]]; then
    echo "  (No production source files changed)"
else
    CHECKED_SYMBOLS=0
    for prod in "${PROD_FILES[@]}"; do
        [[ $CHECKED_SYMBOLS -ge 6 ]] && break
        BASE_NAME=$(basename "$prod")
        STEM="${BASE_NAME%.*}"

        CALLERS=()
        while IFS= read -r caller; do
            [[ -n "$caller" ]] && CALLERS+=("$caller")
        done < <(git grep -l "\b${STEM}\b" -- ":!*${BASE_NAME}" ":!*${STEM}Test*" ":!*.md" 2>/dev/null | head -n 6 || true)

        if [[ ${#CALLERS[@]} -gt 0 ]]; then
            echo "  Callers of ${STEM}:"
            for c in "${CALLERS[@]}"; do
                echo "    • $c"
            done
            CHECKED_SYMBOLS=$((CHECKED_SYMBOLS + 1))
        fi
    done

    if [[ $CHECKED_SYMBOLS -eq 0 ]]; then
        echo "  (No external callers found via symbol grep)"
    fi
fi
echo ""

# --- 8. Full Diff Output ---
if [[ "$PRINT_DIFF" == "true" ]]; then
    echo "Full diff:"
    if [[ "$MODE" == "WORKING_TREE" ]]; then
        git diff HEAD 2>/dev/null || true
    else
        git diff "$DIFF_SPEC" 2>/dev/null || true
    fi
    echo ""
fi

echo "================================================================================"
echo "                     END OF CHANGE INSPECTOR REPORT                             "
echo "================================================================================"
