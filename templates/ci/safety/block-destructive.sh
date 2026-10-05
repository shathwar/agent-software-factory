#!/bin/bash
set -euo pipefail

# Microsoft AGT + Agent Guard Hardened PreToolUse Guardrail
INPUT="${1:-$(cat)}"

# Extract command from JSON if valid JSON, otherwise treat INPUT directly as command
COMMAND=""
if command -v jq >/dev/null 2>&1; then
  COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // .command // empty' 2>/dev/null || true)
fi

if [ -z "$COMMAND" ]; then
  COMMAND="$INPUT"
fi

# Run Policy Verification & Velocity Limiting via Python stdlib
RESULT=$(python3 -c '
import sys, os, re, json, time, shlex
from pathlib import Path

cmd = sys.argv[1]

def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(2)

# Parse JSON here as well so quoting protection does not depend on jq.
try:
    payload = json.loads(cmd)
except ValueError:
    payload = None
if isinstance(payload, dict):
    cmd = payload.get("tool_input", {}).get("command", payload.get("command", ""))
if not isinstance(cmd, str):
    block("Command must be a string.")

# Substitutions and heredocs require a full shell interpreter to classify.
if re.search(r"\$\(|`|\$\{|<<", cmd):
    block("Shell substitutions and heredocs cannot be safely classified by this hook.")
try:
    lexer = shlex.shlex(cmd, posix=True, punctuation_chars=";&|()<>\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    tokens = list(lexer)
except ValueError:
    block("Malformed shell quoting cannot be safely classified.")

commands = []
policy_commands = []
normalized = []
words = []
for token in tokens + [";"]:
    if token and all(c in ";&|\n" for c in token):
        if words:
            commands.append(words)
            # Literal output/message arguments are data. Executable operands in
            # every other command retain their complete unquoted values.
            if words[0] not in ("echo", "printf"):
                kept = []
                skip_next = False
                for word in words:
                    if skip_next:
                        skip_next = False
                        continue
                    if words[:2] == ["git", "commit"] and word in ("-m", "--message"):
                        skip_next = True
                        continue
                    if words[:2] == ["git", "commit"] and word.startswith("--message="):
                        continue
                    if words[:2] == ["git", "log"] and word.startswith("--grep="):
                        continue
                    kept.append(word)
                normalized.extend(kept)
                policy_commands.append(kept)
            words = []
        normalized.append(token)
    else:
        words.append(token)
cmd = " ".join(normalized)

# 0. Tool Velocity Limiter (agent-guard Anti-Runaway / Anti-Brute-Force Guardrail)
velocity_disabled = os.environ.get("AGT_VELOCITY_LIMITER_DISABLED", "").lower() in ("1", "true", "yes")
timestamps = []
history_file = None

if not velocity_disabled:
    max_calls = int(os.environ.get("AGT_MAX_TOOL_CALLS", "60"))
    window_secs = float(os.environ.get("AGT_TOOL_WINDOW_SECS", "60"))
    state_dir = os.environ.get("SKILLS_VELOCITY_DIR", ".agentflow/velocity")
    os.makedirs(state_dir, exist_ok=True)
    history_file = os.path.join(state_dir, "calls.json")

    now = time.time()
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                timestamps = json.load(f)
        except Exception:
            timestamps = []

    # Prune timestamps older than sliding window
    cutoff = now - window_secs
    timestamps = [t for t in timestamps if t > cutoff]

    if len(timestamps) >= max_calls:
        print(json.dumps({
            "decision": "block",
            "reason": f"Velocity limit exceeded: max {max_calls} calls per {window_secs:g}s reached to prevent runaway execution."
        }))
        sys.exit(2)

# 1. Cloud Metadata SSRF Defense (OWASP Agentic Top 10)
if re.search(r"https?://(169\.254\.169\.254|100\.100\.100\.200|metadata\.google\.internal)", cmd, re.I):
    print(json.dumps({"decision": "block", "reason": "Cloud instance metadata service access (169.254.169.254) is blocked by AGT SSRF policy."}))
    sys.exit(2)

# 2. Direct CLI Token Exfiltration
if re.search(r"\b(gh\s+auth\s+token|az\s+account\s+get-access-token|kubectl\s+config\s+view\s+--raw|security\s+find-generic-password)\b", cmd, re.I):
    print(json.dumps({"decision": "block", "reason": "Direct CLI token exfiltration command blocked by AGT policy."}))
    sys.exit(2)

# 3. Direct Secret & Credential Path Reads
if re.search(r"\b(cat|type|get-content|head|tail|more|less)\b[^\n\r]*(?:(?:\s|^|~|/)\.env(?!\.(example|sample|template))|~?/(?:\.ssh/id_|\.aws/credentials|\.azure|\.kube/config|\.netrc|\.git-credentials)|/proc/\d+/environ)", cmd, re.I):
    print(json.dumps({"decision": "block", "reason": "Direct credential/secret file read blocked by AGT policy."}))
    sys.exit(2)

# 4. Dangerous Shell Piping
if re.search(r"\b(curl|wget|fetch)\b[^|\n\r]*\|\s*(sh|bash|zsh|python|perl|pwsh)", cmd, re.I):
    print(json.dumps({"decision": "block", "reason": "Remote script download piped directly to shell execution is blocked by AGT policy."}))
    sys.exit(2)

# 5. Dangerous Git & Database Drops
if re.search(r"(git\s+push(\s+.*)?\s+(--force|-f\b)|git\s+reset\s+--hard|DROP\s+(TABLE|DATABASE)|TRUNCATE\s+TABLE|db\.dropDatabase|db\.[a-zA-Z0-9_]+\.drop\s*\(|mkfs\b|dd\s+if=.*of=/dev/)", cmd, re.I):
    print(json.dumps({"decision": "block", "reason": "Destructive command blocked by safety hook: risky operation detected."}))
    sys.exit(2)

# 6. Resolve recursive cleanup operands within the actual allowed roots.
for words in policy_commands:
    if os.path.basename(words[0]) != "rm":
        if re.search(r"(?:^|[ /])rm\s+-", " ".join(words)):
            block("Wrapped deletion cannot be safely classified; use a direct cleanup command.")
        continue
    targets = []
    recursive = False
    options = True
    for word in words[1:]:
        if options and word == "--":
            options = False
        elif options and word.startswith("-"):
            recursive |= word == "--recursive" or (not word.startswith("--") and any(c in word for c in "rR"))
        else:
            targets.append(word)
    if not recursive:
        continue
    SAFE_TARGETS = {
        "node_modules", "dist", "build", ".next", "target",
        "__pycache__", ".pytest_cache", ".venv", "venv",
        "coverage", ".turbo", "out", ".agentflow"
    }
    is_safe = bool(targets)
    if any(part[0] == "cd" for part in commands):
        is_safe = False
    for t in targets:
        path = Path(t)
        if path.is_absolute() or not path.parts or ".." in path.parts or any(c in t for c in "$*?[]{}~"):
            is_safe = False
            break
        root = Path.cwd() / path.parts[0]
        if path.parts[0] not in SAFE_TARGETS or root.is_symlink():
            is_safe = False
            break
        try:
            (Path.cwd() / path).resolve().relative_to(root.resolve())
        except (ValueError, OSError, RuntimeError):
            is_safe = False
            break
    if not is_safe:
        print(json.dumps({"decision": "block", "reason": "Recursive deletion outside approved safe targets (build/dist/__pycache__/.agentflow) is blocked by AGT policy."}))
        sys.exit(2)

# All checks passed: record velocity timestamp if limiter enabled
if history_file:
    timestamps.append(time.time())
    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(timestamps, f)
    except Exception:
        pass

sys.exit(0)
' "$COMMAND" 2>&1) || {
  EXIT_CODE=$?
  if [ -n "$RESULT" ]; then
    echo "$RESULT"
  fi
  exit "$EXIT_CODE"
}

exit 0
