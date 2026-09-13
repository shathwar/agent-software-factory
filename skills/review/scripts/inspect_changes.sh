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
EXPLICIT_BASE=""
SCOPE_DIR=""
MAX_DIFF_LINES=2000

while [[ $# -gt 0 ]]; do
    case "$1" in
        --base)
            [[ $# -lt 2 ]] && { echo "Error: --base requires a branch argument." >&2; exit 2; }
            EXPLICIT_BASE="$2"
            shift 2
            ;;
        --base=*)
            EXPLICIT_BASE="${1#*=}"
            [[ -z "$EXPLICIT_BASE" ]] && { echo "Error: --base requires a branch argument." >&2; exit 2; }
            shift
            ;;
        --scope)
            [[ $# -lt 2 ]] && { echo "Error: --scope requires a directory argument." >&2; exit 2; }
            SCOPE_DIR="$2"
            shift 2
            ;;
        --scope=*)
            SCOPE_DIR="${1#*=}"
            [[ -z "$SCOPE_DIR" ]] && { echo "Error: --scope requires a directory argument." >&2; exit 2; }
            shift
            ;;
        --max-diff-lines)
            [[ $# -lt 2 ]] && { echo "Error: --max-diff-lines requires an integer argument." >&2; exit 2; }
            MAX_DIFF_LINES="$2"
            shift 2
            ;;
        --max-diff-lines=*)
            MAX_DIFF_LINES="${1#*=}"
            shift
            ;;
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
            echo "  --base <ref>         Base branch or ref to diff working tree against (e.g. 'main')"
            echo "  --scope <dir>        Restrict caller grep to subproject directory (auto-detects .ship.json scope)"
            echo "  --max-diff-lines <N> Maximum diff lines to output before truncating (default: 2000)"
            echo "  --no-diff            Omit the full unified diff output"
            echo "  --full-diff          Print the full unified diff output (default)"
            echo "  -h, --help           Show this help message"
            exit 0
            ;;
        -*)
            echo "Error: Unknown option: $1" >&2
            exit 2
            ;;
        *)
            if [[ -n "$TARGET_DIFF" ]]; then
                echo "Error: Supply only one comparison target." >&2
                exit 2
            fi
            TARGET_DIFF="$1"
            shift
            ;;
    esac
done

if [[ -n "$TARGET_DIFF" && -n "$EXPLICIT_BASE" ]]; then
    echo "Error: Cannot supply both --base and an explicit comparison target." >&2
    exit 2
fi

# --- 2. Resolve Branch, Base & Target Scope ---
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "HEAD")

if [[ -z "$SCOPE_DIR" && -f ".ship.json" ]]; then
    DETECTED_SCOPE=$(grep -o '"scope"[[:space:]]*:[[:space:]]*"[^"]*"' .ship.json 2>/dev/null | head -n 1 | sed -E 's/.*"scope"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/' || true)
    if [[ -n "$DETECTED_SCOPE" && "$DETECTED_SCOPE" != "." ]]; then
        SCOPE_DIR="$DETECTED_SCOPE"
    fi
fi

# Preserve the exact ref: origin/main does not imply a local main branch.
BASE_BRANCH=""
BASE_REF=""

if [[ -n "$EXPLICIT_BASE" ]]; then
    for ref in "refs/heads/$EXPLICIT_BASE" "refs/remotes/origin/$EXPLICIT_BASE" "$EXPLICIT_BASE"; do
        if git rev-parse --verify "$ref^{commit}" >/dev/null 2>&1; then
            BASE_BRANCH="$EXPLICIT_BASE"
            BASE_REF="$ref"
            break
        fi
    done
    if [[ -z "$BASE_REF" ]]; then
        echo "Error: Base ref not found: $EXPLICIT_BASE" >&2
        exit 2
    fi
else
    for candidate in main master trunk develop; do
        for ref in "refs/heads/$candidate" "refs/remotes/origin/$candidate"; do
            if git rev-parse --verify "$ref^{commit}" >/dev/null 2>&1; then
                BASE_BRANCH="$candidate"
                BASE_REF="$ref"
                break 2
            fi
        done
    done
fi

INSPECT_TMP=$(mktemp -d "${TMPDIR:-/tmp}/review.XXXXXX")
trap 'rm -rf "$INSPECT_TMP"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

git status --porcelain=v1 -z --untracked-files=all > "$INSPECT_TMP/status"
EMPTY_TREE=$(git hash-object -t tree /dev/null)

if [[ -n "$TARGET_DIFF" ]]; then
    MODE="EXPLICIT_TARGET"
    DIFF_SPEC="$TARGET_DIFF"
elif [[ -n "$EXPLICIT_BASE" ]]; then
    MODE="BASE_WORKING_TREE"
    DIFF_SPEC="$BASE_REF"
elif [[ -s "$INSPECT_TMP/status" ]]; then
    MODE="WORKING_TREE"
    if git rev-parse --verify HEAD >/dev/null 2>&1; then
        DIFF_SPEC="HEAD"
    else
        DIFF_SPEC="$EMPTY_TREE"
    fi
elif [[ -n "$BASE_REF" && "$CURRENT_BRANCH" != "$BASE_BRANCH" ]]; then
    MODE="BRANCH_DIFF"
    DIFF_SPEC="$BASE_REF...HEAD"
elif git rev-parse --verify HEAD~1 >/dev/null 2>&1; then
    MODE="LAST_COMMIT"
    DIFF_SPEC="HEAD~1..HEAD"
elif git rev-parse --verify HEAD >/dev/null 2>&1; then
    MODE="ROOT_COMMIT"
    DIFF_SPEC="$EMPTY_TREE HEAD"
else
    MODE="WORKING_TREE"
    DIFF_SPEC="$EMPTY_TREE"
fi

DIFF_ARGS=("$DIFF_SPEC")
if [[ "$MODE" == "ROOT_COMMIT" ]]; then
    DIFF_ARGS=("$EMPTY_TREE" HEAD)
fi
# Required Git operations must succeed before printing a successful-looking report.
# Disable user diff drivers: inspection should not invoke external commands.
git diff --no-ext-diff --no-textconv --no-color -M "${DIFF_ARGS[@]}" -- > "$INSPECT_TMP/diff"
git diff --no-ext-diff --no-textconv --name-status -z -M "${DIFF_ARGS[@]}" -- > "$INSPECT_TMP/paths"

ADDED_FILES=()
MODIFIED_FILES=()
DELETED_FILES=()
RENAMED_FILES=()
ALL_CHANGED_FILES=()
UNTRACKED_FILES=()

add_changed_path() {
    local existing
    if [[ ${#ALL_CHANGED_FILES[@]} -gt 0 ]]; then
        for existing in "${ALL_CHANGED_FILES[@]}"; do
            [[ "$existing" == "$1" ]] && return 0
        done
    fi
    ALL_CHANGED_FILES+=("$1")
}

# NUL records preserve spaces, tabs, Unicode, and rename source/destination paths.
while IFS= read -r -d '' status; do
    IFS= read -r -d '' file1
    add_changed_path "$file1"
    case "${status:0:1}" in
        A) ADDED_FILES+=("$file1") ;;
        D) DELETED_FILES+=("$file1") ;;
        R|C)
            IFS= read -r -d '' file2
            add_changed_path "$file2"
            RENAMED_FILES+=("$file2 (from $file1)")
            ;;
        *) MODIFIED_FILES+=("$file1") ;;
    esac
done < "$INSPECT_TMP/paths"

if [[ "$MODE" == "WORKING_TREE" || "$MODE" == "BASE_WORKING_TREE" ]]; then
    git ls-files --others --exclude-standard -z > "$INSPECT_TMP/untracked"
    while IFS= read -r -d '' f; do
        UNTRACKED_FILES+=("$f")
        ADDED_FILES+=("$f")
        add_changed_path "$f"
        # --no-index returns 1 for a difference; any other failure is an error.
        result=0
        git diff --no-ext-diff --no-textconv --no-color --no-index -- /dev/null "./$f" >> "$INSPECT_TMP/diff" || result=$?
        if [[ "$result" -gt 1 ]]; then
            echo "Error: Could not inspect untracked file: $f" >&2
            exit "$result"
        fi
    done < "$INSPECT_TMP/untracked"
fi
# Statistics, triggers, and full output all use the same captured patch.
if [[ -s "$INSPECT_TMP/diff" ]]; then
    git apply --stat < "$INSPECT_TMP/diff" > "$INSPECT_TMP/stat"
else
    : > "$INSPECT_TMP/stat"
fi

echo "================================================================================"
echo "               ADVERSARIAL REVIEW: CHANGE INSPECTOR REPORT                      "
echo "================================================================================"
echo "Branch: $CURRENT_BRANCH"
if [[ -n "$BASE_BRANCH" ]]; then
    echo "Base:   $BASE_REF"
fi
echo "Scope:  $DIFF_SPEC ($MODE)"
echo ""

# --- 3. Spec & Requirements Discovery ---
echo "Spec & Requirements Discovery:"
SPEC_FOUND=false

COMMITS_TO_CHECK=""
if [[ "$MODE" == "ROOT_COMMIT" ]]; then
    COMMITS_TO_CHECK=$(git log -n 1 --oneline HEAD)
elif [[ "$MODE" == "WORKING_TREE" ]]; then
    COMMITS_TO_CHECK=$(git log -n 5 --oneline 2>/dev/null || true)
elif [[ "$MODE" == "BASE_WORKING_TREE" ]]; then
    COMMITS_TO_CHECK=$(git log "$BASE_REF..HEAD" --oneline 2>/dev/null || true)
else
    COMMITS_TO_CHECK=$(git log "$DIFF_SPEC" --oneline 2>/dev/null || true)
fi

ISSUE_REFS=$(echo "$COMMITS_TO_CHECK" | grep -o -E '(#|GH-|[A-Z]{2,10}-)[0-9]+' | sort -u | tr '\n' ' ' || true)
if [[ -n "${ISSUE_REFS// }" ]]; then
    echo "  • Linked Issues in Commits: $ISSUE_REFS"
    SPEC_FOUND=true
fi

SPEC_FILES=()
add_spec_file() {
    local f="$1"
    [[ -z "$f" ]] && return
    if [[ ${#SPEC_FILES[@]} -gt 0 ]]; then
        for existing in "${SPEC_FILES[@]}"; do
            [[ "$existing" == "$f" ]] && return
        done
    fi
    SPEC_FILES+=("$f")
}

while IFS= read -r -d '' f; do
    add_spec_file "$f"
done < <(git ls-files -z --cached --others --exclude-standard "*spec*.md" "*PRD*.md" "*RFC*.md" "docs/specs/*" "docs/rfcs/*" "docs/adr/*" ".scratch/*" "specs/*" "openspec/*" 2>/dev/null || true)

# Also check untracked or ignored scratch, spec, adr, and openspec directories on disk
for scratch_dir in .scratch scratch docs/specs specs docs/adr openspec; do
    if [[ -d "$scratch_dir" ]]; then
        while IFS= read -r -d '' sf; do
            add_spec_file "${sf#./}"
        done < <(find "$scratch_dir" -maxdepth 4 -type f \( -name "*.md" -o -name "*.txt" \) -print0 2>/dev/null || true)
    fi
done

if [[ ${#SPEC_FILES[@]} -gt 0 ]]; then
    echo "  • Available Spec / PRD Documents:"
    for sf in "${SPEC_FILES[@]}"; do
        echo "    - $sf"
    done
    SPEC_FOUND=true
fi

if [[ "$SPEC_FOUND" == "false" ]]; then
    echo "  • No explicit issue keys or spec markdown files detected."
    echo "    (If a spec exists, provide its path or summary; otherwise Stage 0 evaluates as SKIPPED)."
fi
echo ""

# --- 4. Repository Standards & Tooling ---
echo "Repository Standards & Conventions:"
STANDARDS_FOUND=false

STANDARDS_DOCS=()
add_standards_doc() {
    local f="$1"
    [[ -z "$f" ]] && return
    if [[ ${#STANDARDS_DOCS[@]} -gt 0 ]]; then
        for existing in "${STANDARDS_DOCS[@]}"; do
            [[ "$existing" == "$f" ]] && return
        done
    fi
    STANDARDS_DOCS+=("$f")
}

while IFS= read -r -d '' f; do
    add_standards_doc "$f"
done < <(git ls-files -z --cached --others --exclude-standard "*CODING_STANDARDS*" "*CONTRIBUTING*" "*STYLEGUIDE*" "docs/standards/*" 2>/dev/null || true)

if [[ ${#STANDARDS_DOCS[@]} -gt 0 ]]; then
    echo "  • Documented Standards:"
    for doc in "${STANDARDS_DOCS[@]}"; do
        echo "    - $doc"
    done
    STANDARDS_FOUND=true
fi

LINTER_CONFIGS=()
add_linter_cfg() {
    local f="$1"
    [[ -z "$f" ]] && return
    if [[ ${#LINTER_CONFIGS[@]} -gt 0 ]]; then
        for existing in "${LINTER_CONFIGS[@]}"; do
            [[ "$existing" == "$f" ]] && return
        done
    fi
    LINTER_CONFIGS+=("$f")
}

while IFS= read -r -d '' f; do
    add_linter_cfg "$f"
done < <(git ls-files -z --cached --others --exclude-standard ".eslintrc*" "eslint.config.*" "biome.json" "ruff.toml" ".ruff.toml" "pyproject.toml" ".clang-format" "checkstyle.xml" ".golangci.*" "rustfmt.toml" "mypy.ini" ".pylintrc" ".flake8" "clippy.toml" 2>/dev/null || true)

if [[ ${#LINTER_CONFIGS[@]} -gt 0 ]]; then
    echo "  • Project Linters / Formatters Configured:"
    for cfg in "${LINTER_CONFIGS[@]}"; do
        echo "    - $cfg"
    done
    STANDARDS_FOUND=true
fi

if [[ "$STANDARDS_FOUND" == "false" ]]; then
    echo "  • No custom coding standards or linter configs detected (using Fowler Code Smell baseline)."
fi
echo ""

# --- 5. Categorized Changed Files ---
echo "Changed files:"

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

# --- 6. Diff Statistics ---
echo "Diff statistics:"
cat "$INSPECT_TMP/stat"
echo ""

# --- 7. Intelligent Review Mode Triggers ---
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
    grep -q -E "$1" "$INSPECT_TMP/diff"
}

if files_match "(pom\.xml|build\.gradle(\.kts)?|package\.json|package-lock\.json|pnpm-lock\.yaml|bun\.lockb|yarn\.lock|requirements.*\.txt|Pipfile(\.lock)?|poetry\.lock|uv\.lock|go\.(mod|sum)|Cargo\.(toml|lock)|composer\.(json|lock)|Gemfile(\.lock)?)"; then
    echo "  [!] DEPENDENCY REVIEW: Build / dependency manifests modified (check new deps, versions, CVEs, licenses)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if files_match "(application.*\.ya?ml|application.*\.properties|\.env.*|config\.(py|go|ts|js)|settings\.json|Config\.java|docker-compose.*\.ya?ml|Dockerfile|Containerfile|\.dockerignore|values.*\.ya?ml|tsconfig.*\.json)"; then
    echo "  [!] CONFIG REVIEW: Application configuration modified (verify default values, env var overrides, secrets safety)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if files_match "(db/migration/|migrations/|V[0-9]+__.*\.sql|schema\.prisma|alembic/|alembic\.ini|drizzle/|drizzle\.config\.)"; then
    echo "  [!] MIGRATION REVIEW: Database migrations / SQL changed (check Flyway checksums, query index coverage, table lock hazards)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if diff_contains "\b(synchronized|ReentrantLock|Lock|ConcurrentHashMap|AtomicReference|AtomicBoolean|AtomicInteger|AsyncKeyedLock|asyncio\.(Lock|Semaphore)|Mutex|RWMutex|Semaphore|CountDownLatch|threading\.(Lock|RLock|Semaphore)|sync\.(Mutex|RWMutex|WaitGroup)|tokio::sync|std::sync::Mutex|pthread_mutex|StateFlow|SharedFlow)\b|<-chan|chan<-"; then
    echo "  [!] CONCURRENCY REVIEW: Mutexes, locks, or atomic collections in diff (scrutinize deadlock, reentrancy, double release, atomicity)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if diff_contains "\b(Executor|ThreadPoolExecutor|ProcessPoolExecutor|CompletableFuture|VirtualThread|Thread\.start|run_in_threadpool|asyncio\.(create_task|gather|run|to_thread|as_completed)|BackgroundTasks|goroutine|\bgo [a-zA-Z0-9_]+|tokio::spawn|Task\.Run|Promise\.(all|allSettled)|chan [a-zA-Z0-9_]+|Dispatchers\.(IO|Default))\b"; then
    echo "  [!] THREAD / ASYNC LIFECYCLE REVIEW: Background tasks, thread pools, or async tasks (check unhandled errors, task cancellation, carrier pinning)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if files_match "(Controller|Resource|Endpoint|routes|api/|\.proto|openapi.*\.ya?ml|swagger.*\.json|schema\.graphql.*|\.graphqls?)" || diff_contains "(@RestController|@Controller|@Get|@Post|@Put|@Delete|@Patch|@Path|@app\.(get|post|put|delete|patch)|router\.(get|post|put|delete|patch)|r\.(GET|POST|PUT|DELETE|PATCH)|fastify\.(get|post|put|delete)|publicProcedure|router\.(query|mutation)|@Query|@Mutation)"; then
    echo "  [!] CONTRACT REVIEW: API controllers / routing modified (check backwards compatibility, status codes, query params, schema serialization)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if diff_contains "\b(BigDecimal|Decimal|stopLoss|trailing_sl|entryPrice|orderPrice|tradedPrice|ltp|premium|lotSize|qty|pnl|cents|balance|ledger|subtotal|currency)\b"; then
    echo "  [!] FINANCIAL / PRECISION REVIEW: Pricing, stop-loss, or quantity logic modified (verify float safety, division by zero, domain separation)"
    TRIGGERS_COUNT=$((TRIGGERS_COUNT + 1))
fi

if [[ "$TRIGGERS_COUNT" -eq 0 ]]; then
    echo "  Standard review pipeline (no specialized triggers activated)."
fi
echo ""

# --- 8. Relevant Tests Mapping ---
echo "Relevant tests:"
PROD_FILES=()

is_test_or_doc_file() {
    local f="$1"
    local base="${f##*/}"

    # Skip dotfiles (.gitignore, .dockerignore, .env, .editorconfig, etc.)
    if [[ "$base" =~ ^\. ]]; then
        return 0
    fi
    # Skip project metadata files (LICENSE, COPYING, AUTHORS, CHANGELOG, NOTICE, README, etc.)
    if [[ "$base" =~ ^(LICENSE|COPYING|AUTHORS|CHANGELOG|NOTICE|README)(\..+)?$ ]]; then
        return 0
    fi
    # Skip build, container, and infrastructure files without standard code extensions
    if [[ "$base" =~ ^(Dockerfile|Containerfile|Makefile|Procfile|Rakefile|Gemfile|Vagrantfile)(\..+)?$ ]]; then
        return 0
    fi
    # Skip non-source/doc/config/data/asset files
    if [[ "$f" =~ \.(md|markdown|ya?ml|sql|json|xml|properties|toml|ini|txt|csv|tsv|lock|lockb|svg|png|jpe?g|gif|ico|woff2?|ttf|eot)$ ]]; then
        return 0
    fi
    # Skip test/spec directories
    if [[ "$f" =~ (^|/)(tests?|specs?|__tests__|it)(/|$) ]]; then
        return 0
    fi
    # Skip test files matching test file naming conventions
    if [[ "$f" =~ (Test|Tests|IT|_test|_spec|\.test|\.spec)\.[a-zA-Z0-9]+$ ]] || \
       [[ "$f" =~ (^|/)(test_|Test[A-Z])[^/]+\.[a-zA-Z0-9]+$ ]]; then
        return 0
    fi
    return 1
}

if [[ ${#ALL_CHANGED_FILES[@]} -gt 0 ]]; then
    for f in "${ALL_CHANGED_FILES[@]}"; do
        if is_test_or_doc_file "$f"; then
            continue
        fi
        PROD_FILES+=("$f")
    done
fi

if [[ ${#PROD_FILES[@]} -eq 0 ]]; then
    echo "  (No production source files changed)"
else
    for prod in "${PROD_FILES[@]}"; do
        BASE_NAME="${prod##*/}"
        STEM="${BASE_NAME%.*}"
        EXT="${BASE_NAME##*.}"

        MATCHING_TESTS=()

        # 1. Search tracked git files
        TEST_GLOBS=()
        case "$EXT" in
            java|kt)
                TEST_GLOBS=("*${STEM}Test.*" "*${STEM}Tests.*" "*${STEM}IT.*" "*Test${STEM}.*")
                ;;
            py)
                TEST_GLOBS=("*test_${STEM}.py" "*${STEM}_test.py" "*${STEM}Test.py")
                ;;
            ts|js|jsx|tsx)
                TEST_GLOBS=("*${STEM}.spec.*" "*${STEM}.test.*" "*${STEM}_test.*" "*${STEM}Test.*" "*test_${STEM}.*")
                ;;
            go)
                TEST_GLOBS=("*${STEM}_test.go")
                ;;
            rs)
                TEST_GLOBS=("*${STEM}*test*.rs" "tests/*${STEM}*.rs")
                ;;
            cs)
                TEST_GLOBS=("*${STEM}Tests.cs" "*${STEM}Test.cs")
                ;;
            cpp|cc|cxx|c|h|hpp|hxx)
                TEST_GLOBS=("*${STEM}_test.*" "*${STEM}Test.*" "*test_${STEM}.*")
                ;;
            rb)
                TEST_GLOBS=("*${STEM}_spec.rb" "*${STEM}_test.rb" "*test_${STEM}.rb")
                ;;
            *)
                TEST_GLOBS=("*test_${STEM}*" "*${STEM}_test*" "*${STEM}Test*" "*${STEM}Tests*" "*${STEM}.test.*" "*${STEM}.spec.*")
                ;;
        esac

        while IFS= read -r -d '' t; do
            [[ -n "$t" ]] && MATCHING_TESTS+=("$t")
        done < <(git ls-files -z "${TEST_GLOBS[@]}" 2>/dev/null || true)

        # 2. Also check untracked added files on disk
        if [[ ${#ADDED_FILES[@]} -gt 0 ]]; then
            shopt -s nocasematch
            local_test_pattern="(^|/)(test_${STEM}|Test${STEM}|${STEM}(Tests?|IT|_test|\.spec|\.test|_spec))\.[a-zA-Z0-9]+$"
            for added in "${ADDED_FILES[@]}"; do
                if [[ "$added" != "$prod" ]] && [[ "$added" =~ $local_test_pattern ]]; then
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
            shopt -u nocasematch
        fi

        if [[ ${#MATCHING_TESTS[@]} -eq 0 ]]; then
            echo "  [MISSING TEST] $prod"
            echo "                 -> No matching test file found (e.g. ${STEM}Test, test_${STEM}, or ${STEM}_test)!"
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

# --- 9. Potentially Affected Callers ---
echo "Potentially affected callers:"
if [[ ${#PROD_FILES[@]} -eq 0 ]]; then
    echo "  (No production source files changed)"
else
    CHECKED_SYMBOLS=0
    for prod in "${PROD_FILES[@]}"; do
        [[ $CHECKED_SYMBOLS -ge 6 ]] && break
        BASE_NAME="${prod##*/}"
        STEM="${BASE_NAME%.*}"

        # Skip empty or generic stems that cause massive false-positive caller noise
        if [[ -z "$STEM" ]] || [[ "$STEM" =~ ^(index|main|types|utils|common|base|config|helper|helpers|constants|styles)$ ]]; then
            continue
        fi

        CALLERS=()
        GREP_PATHSPEC=()
        if [[ -n "$SCOPE_DIR" && -d "$SCOPE_DIR" ]]; then
            GREP_PATHSPEC+=("$SCOPE_DIR")
        fi
        GREP_PATHSPEC+=("--" ":!${prod}" ":!*/${BASE_NAME}" ":!*test*" ":!*spec*" ":!*Test*" ":!*.md" ":!*.lock" ":!*.map" ":!*.min.*" ":!*.svg")
        while IFS= read -r caller; do
            [[ -n "$caller" ]] && CALLERS+=("$caller")
        done < <(git grep -l "\b${STEM}\b" "${GREP_PATHSPEC[@]}" 2>/dev/null | head -n 6 || true)

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

# --- 10. Full Diff Output ---
if [[ "$PRINT_DIFF" == "true" ]]; then
    echo "Full diff:"
    DIFF_LINE_COUNT=$(wc -l < "$INSPECT_TMP/diff" | tr -d ' ')
    if [[ "$DIFF_LINE_COUNT" -gt "$MAX_DIFF_LINES" ]]; then
        head -n "$MAX_DIFF_LINES" "$INSPECT_TMP/diff"
        echo ""
        echo "  [!] TRUNCATED: Diff output exceeded $MAX_DIFF_LINES lines (total: $DIFF_LINE_COUNT lines)."
        echo "      Use '--max-diff-lines $DIFF_LINE_COUNT' to view the entire diff, or '--no-diff' to omit."
    else
        cat "$INSPECT_TMP/diff"
    fi
    echo ""
fi

echo "================================================================================"
echo "                     END OF CHANGE INSPECTOR REPORT                             "
echo "================================================================================"
