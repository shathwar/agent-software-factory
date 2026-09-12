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
DRY_RUN=0

usage() {
    cat <<EOF
Usage: ./scripts/install.sh [options]

Options:
  --target <dir>     Target skills directory (default: $DEFAULT_TARGET)
  --mode <symlink|copy>
                     Installation mode: 'symlink' or 'copy' (default: symlink)
  --dry-run          Print actions without modifying the filesystem
  --list             List available skills in this repository
  -h, --help         Show this help message
EOF
    exit 0
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
        --mode)
            INSTALL_MODE="$2"
            shift 2
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
            echo "Unknown option: $1" >&2
            usage
            ;;
    esac
done

if [[ "$INSTALL_MODE" != "symlink" && "$INSTALL_MODE" != "copy" ]]; then
    echo "Error: --mode must be either 'symlink' or 'copy'." >&2
    exit 1
fi

echo "====================================================================="
echo " Installing Skills Suite"
echo "====================================================================="
echo " Source directory : $SKILLS_DIR"
echo " Target directory : $TARGET_DIR"
echo " Mode             : $INSTALL_MODE"
if [[ $DRY_RUN -eq 1 ]]; then
    echo " (DRY-RUN enabled: no changes will be made)"
fi
echo "---------------------------------------------------------------------"

if [[ $DRY_RUN -eq 0 ]]; then
    mkdir -p "$TARGET_DIR"
fi

installed_count=0

for skill_path in "$SKILLS_DIR"/*; do
    if [[ ! -d "$skill_path" || ! -f "$skill_path/SKILL.md" ]]; then
        continue
    fi

    skill_name="$(basename "$skill_path")"
    dest_path="$TARGET_DIR/$skill_name"

    if [[ -e "$dest_path" || -L "$dest_path" ]]; then
        echo " ⚠️  $skill_name: destination already exists at $dest_path (updating...)"
        if [[ $DRY_RUN -eq 0 ]]; then
            rm -rf "$dest_path"
        fi
    fi

    if [[ "$INSTALL_MODE" == "symlink" ]]; then
        echo " 🔗 Linking $skill_name -> $dest_path"
        if [[ $DRY_RUN -eq 0 ]]; then
            ln -s "$skill_path" "$dest_path"
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
echo "✓ Successfully installed $installed_count skill(s) into $TARGET_DIR"
echo "====================================================================="
