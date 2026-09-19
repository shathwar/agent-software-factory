#!/usr/bin/env bash
# ==============================================================================
# scripts/install.sh — Install skills into agent config directory
#
# Supported modes:
#   symlink (default): Creates relative/absolute symbolic links
#   copy: Copies skills directories
#
# Targets:
#   Default: ~/.gemini/config/skills/ (Antigravity global skill directory)
#   Custom: specified via --target <path>
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/skills"

DEFAULT_TARGET="$HOME/.gemini/config/skills"
TARGET_DIR="$DEFAULT_TARGET"
INSTALL_MODE="symlink"
MODE_EXPLICIT=0
DRY_RUN=0
OVERWRITE=0
BACKUP=0
INSTALL_PIP=0
INSTALL_MCP=0

IS_WINDOWS=0
case "$(uname -s 2>/dev/null || echo 'unknown')" in
    CYGWIN*|MINGW*|MSYS*)
        IS_WINDOWS=1
        ;;
esac

usage() {
    local code="${1:-0}"
    cat <<EOF
Usage: ./scripts/install.sh [options]

Options:
  --target <dir>     Target skills directory (default: $DEFAULT_TARGET)
  --target-claude    Install to Claude Code skills directory (~/.claude/skills)
  --target-cursor    Install to Cursor skills directory (~/.cursor/skills)
  --target-antigravity, --target-gemini
                     Install to Antigravity global directory (~/.gemini/config/skills)
  --pip, --editable  Install 'ship' CLI package locally into Python environment (pip install -e .)
  --mcp              Register 'ship' MCP server into target harness config (Antigravity/Claude/Cursor)
  --mode <symlink|copy>
                     Installation mode: 'symlink' or 'copy' (default: symlink on Unix, copy on Windows)
  --overwrite        Overwrite existing non-symlink directories (default: preserve & skip)
  --backup           Back up existing directories with timestamp suffix before replacing
  --dry-run          Print actions without modifying the filesystem
  --list             List available skills in this repository
  -h, --help         Show this help message
EOF
    exit "$code"
}

list_skills() {
    echo "Available skills in $SKILLS_DIR:"
    for skill_path in "$SKILLS_DIR"/*; do
        if [[ -d "$skill_path" && -f "$skill_path/SKILL.md" ]]; then
            skill_name="$(basename "$skill_path")"
            echo "  • $skill_name"
        fi
    done
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            TARGET_DIR="$2"
            shift 2
            ;;
        --target-claude)
            TARGET_DIR="$HOME/.claude/skills"
            shift
            ;;
        --target-cursor)
            TARGET_DIR="$HOME/.cursor/skills"
            shift
            ;;
        --target-antigravity|--target-gemini)
            TARGET_DIR="$HOME/.gemini/config/skills"
            shift
            ;;
        --pip|--editable)
            INSTALL_PIP=1
            shift
            ;;
        --mcp)
            INSTALL_MCP=1
            shift
            ;;
        --mode)
            INSTALL_MODE="$2"
            MODE_EXPLICIT=1
            shift 2
            ;;
        --overwrite)
            OVERWRITE=1
            shift
            ;;
        --backup)
            BACKUP=1
            OVERWRITE=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --list)
            list_skills
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Error: Unknown option: $1" >&2
            usage 2
            ;;
    esac
done

if [[ $MODE_EXPLICIT -eq 0 && $IS_WINDOWS -eq 1 ]]; then
    INSTALL_MODE="copy"
    echo "ℹ️  Windows environment detected: defaulting to --mode copy for filesystem safety."
fi

if [[ "$INSTALL_MODE" != "symlink" && "$INSTALL_MODE" != "copy" ]]; then
    echo "Error: --mode must be either 'symlink' or 'copy'." >&2
    exit 1
fi

if [[ $INSTALL_MCP -eq 1 && $INSTALL_PIP -eq 0 && $DRY_RUN -eq 0 ]] && ! command -v ship >/dev/null 2>&1; then
    echo "Error: --mcp requires the ship CLI. Install it first or pass --pip --mcp." >&2
    exit 1
fi

echo "====================================================================="
echo " Installing Skills Suite"
echo "====================================================================="
echo " Source directory : $SKILLS_DIR"
echo " Target directory : $TARGET_DIR"
echo " Mode             : $INSTALL_MODE"
echo " Overwrite        : $((OVERWRITE))"
echo " Backup           : $((BACKUP))"
if [[ $DRY_RUN -eq 1 ]]; then
    echo " (DRY-RUN enabled: no changes will be made)"
fi
echo "---------------------------------------------------------------------"

if [[ $DRY_RUN -eq 0 ]]; then
    mkdir -p "$TARGET_DIR"
fi

installed_count=0
skipped_count=0

for skill_path in "$SKILLS_DIR"/*; do
    if [[ ! -d "$skill_path" || ! -f "$skill_path/SKILL.md" ]]; then
        continue
    fi

    skill_name="$(basename "$skill_path")"
    dest_path="$TARGET_DIR/$skill_name"

    # Destination already exists
    if [[ -L "$dest_path" ]]; then
        # Existing symlink: safe to re-link
        echo " 🔗 Updating existing symlink at $dest_path"
        if [[ $DRY_RUN -eq 0 ]]; then
            rm -f "$dest_path"
        fi
    elif [[ -e "$dest_path" ]]; then
        # Existing non-symlink file or directory
        if [[ $BACKUP -eq 1 ]]; then
            backup_path="${dest_path}.bak.$(date +%Y%m%d%H%M%S)"
            echo " 📦 Backing up existing directory: $dest_path -> $backup_path"
            if [[ $DRY_RUN -eq 0 ]]; then
                mv "$dest_path" "$backup_path"
            fi
        elif [[ $OVERWRITE -eq 1 ]]; then
            echo " ⚠️  Overwriting existing directory at $dest_path (--overwrite set)"
            if [[ $DRY_RUN -eq 0 ]]; then
                rm -rf "$dest_path"
            fi
        else
            echo " 🛡️  Preserving existing directory at $dest_path (use --overwrite or --backup to replace)"
            skipped_count=$((skipped_count + 1))
            continue
        fi
    fi

    if [[ "$INSTALL_MODE" == "symlink" ]]; then
        echo " 🔗 Linking $skill_name -> $dest_path"
        if [[ $DRY_RUN -eq 0 ]]; then
            if ! ln -s "$skill_path" "$dest_path" 2>/dev/null; then
                echo " ⚠️  Symlink creation failed. Falling back to copy."
                cp -R "$skill_path" "$dest_path"
            fi
        fi
    else
        echo " 📋 Copying $skill_name -> $dest_path"
        if [[ $DRY_RUN -eq 0 ]]; then
            cp -R "$skill_path" "$dest_path"
        fi
    fi
    installed_count=$((installed_count + 1))
done

echo "---------------------------------------------------------------------"
echo "✓ Successfully installed $installed_count skill(s) into $TARGET_DIR (skipped: $skipped_count)"

if [[ $INSTALL_PIP -eq 1 ]]; then
    echo "---------------------------------------------------------------------"
    echo "📦 Installing 'ship' CLI package locally (pip install -e .) ..."
    if [[ $DRY_RUN -eq 0 ]]; then
        python3 -m pip install -e "$REPO_ROOT"
    fi
fi

if [[ $INSTALL_MCP -eq 1 ]]; then
    echo "---------------------------------------------------------------------"
    echo "🔌 Registering 'ship' MCP server into target harness config ..."
    MCP_CONF=""
    if [[ "$TARGET_DIR" == *".gemini"* ]]; then
        MCP_CONF="$HOME/.gemini/config/mcp_config.json"
    elif [[ "$TARGET_DIR" == *".claude"* ]]; then
        MCP_CONF="$HOME/.claude/mcp_config.json"
    elif [[ "$TARGET_DIR" == *".cursor"* ]]; then
        MCP_CONF="$HOME/.cursor/mcp.json"
    else
        MCP_CONF="$TARGET_DIR/mcp_config.json"
    fi

    if [[ $DRY_RUN -eq 0 ]]; then
        mkdir -p "$(dirname "$MCP_CONF")"
        python3 -c "
import json, sys, shutil, os, tempfile
p = sys.argv[1]
executable = shutil.which('ship')
if not executable:
    raise SystemExit('ship executable unavailable on PATH; MCP config was not changed')
try:
    with open(p, 'r') as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
servers = data.setdefault('mcpServers', {})
servers['ship'] = {'command': executable, 'args': ['mcp']}
fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(p), prefix='.ship-mcp-')
try:
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, p)
finally:
    if os.path.exists(temp_path):
        os.unlink(temp_path)
print(f' ✓ Registered ship MCP server in {p}')
" "$MCP_CONF"
    else
        echo " (DRY-RUN: would update $MCP_CONF)"
    fi
fi

echo "====================================================================="
