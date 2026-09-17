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

# Strip quoted strings and heredocs to avoid false positives in commit messages or docs
STRIPPED=$(echo "$COMMAND" | sed -E \
  -e "/<<['\"]?EOF/,/^EOF/d" \
  -e "s/\"([^\"\\\\]|\\\\.)*\"//g" \
  -e "s/'[^']*'//g")

# Run Policy Verification & Velocity Limiting via Python stdlib
RESULT=$(python3 -c '
import sys, os, re, json, time

cmd = sys.argv[1]

# 0. Tool Velocity Limiter (agent-guard Anti-Runaway / Anti-Brute-Force Guardrail)
velocity_disabled = os.environ.get("AGT_VELOCITY_LIMITER_DISABLED", "").lower() in ("1", "true", "yes")
timestamps = []
history_file = None

if not velocity_disabled:
    max_calls = int(os.environ.get("AGT_MAX_TOOL_CALLS", "60"))
    window_secs = float(os.environ.get("AGT_TOOL_WINDOW_SECS", "60"))
    state_dir = os.environ.get("SKILLS_VELOCITY_DIR", ".scratch/velocity")
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
if re.search(r"(git\s+push(\s+.*)?\s+(--force|-f\b)|git\s+reset\s+--hard|DROP\s+(TABLE|DATABASE)|TRUNCATE\s+TABLE|db\.dropDatabase|db\.[a-zA-Z0-9_]+\.drop\(|mkfs\b|dd\s+if=.*of=/dev/)", cmd, re.I):
    print(json.dumps({"decision": "block", "reason": "Destructive command blocked by safety hook: risky operation detected."}))
    sys.exit(2)

# 6. Smart Safe-Target Cleanup Allowlisting for rm -rf
m = re.search(r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*|-r\s+-f|-f\s+-r|--recursive\s+-f|-f\s+--recursive)\s+(.+)$", cmd, re.I)
if m:
    SAFE_TARGETS = {
        "node_modules", "dist", "build", ".next", "target",
        "__pycache__", ".pytest_cache", ".venv", "venv",
        "coverage", ".turbo", "out", ".scratch"
    }
    targets_str = m.group(2).strip()
    targets = targets_str.split()
    is_safe = bool(targets)
    for t in targets:
        clean = re.sub(r"^\./+", "", t.strip("\"'\''")).rstrip("/")
        if not clean:
            is_safe = False
            break
        root_part = clean.split("/")[0]
        if root_part not in SAFE_TARGETS and clean not in SAFE_TARGETS:
            is_safe = False
            break
    if not is_safe:
        print(json.dumps({"decision": "block", "reason": "Recursive deletion outside approved safe targets (build/dist/__pycache__/.scratch) is blocked by AGT policy."}))
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
' "$STRIPPED" 2>&1) || {
  EXIT_CODE=$?
  if [ -n "$RESULT" ]; then
    echo "$RESULT"
  fi
  exit "$EXIT_CODE"
}

exit 0
