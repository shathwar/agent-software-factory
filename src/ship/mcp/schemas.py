"""JSON Schemas for Ship MCP Server tools."""

from typing import List, Dict, Any

TOOLS_MANIFEST: List[Dict[str, Any]] = [
    {
        "name": "ship_next_turn",
        "description": "Derive the deterministic Turn Contract for the next required specialist activity (skill, role, phase, inputs, hard constraints, exit criteria, suggested CLI and MCP calls).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"},
                "change": {"type": "string", "description": "Target change ID (e.g. 'inventory')"},
                "format": {"type": "string", "enum": ["text", "json"], "description": "Output format ('text' for human/agent banner, 'json' for raw contract dict)"}
            },
            "required": []
        }
    },
    {
        "name": "ship_status",
        "description": "Evaluate active engineering lifecycle readiness and gate status (ready for delivery, blocked, or rollback required).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"},
                "change": {"type": "string", "description": "Target change ID"}
            },
            "required": []
        }
    },
    {
        "name": "ship_evaluate",
        "description": "Perform full lifecycle evaluation of repository state, including active gate, state key, blockers, next action, ADRs, and living specs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"},
                "change": {"type": "string", "description": "Target change ID"}
            },
            "required": []
        }
    },
    {
        "name": "ship_record_turn",
        "description": "Persist turn-level execution provenance into .agentflow/state.json (skill, harness, execution mode, inputs, evidence, state delta).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill": {"type": "string", "description": "Skill name that executed (e.g. 'design', 'tdd', 'review')"},
                "inputs": {"type": "object", "description": "Inputs provided to the specialist"},
                "evidence": {"type": "object", "description": "Evidence produced by the specialist (e.g. digests, test metrics)"},
                "state_delta": {"type": "object", "description": "Workflow state mutations resulting from this turn"},
                "harness": {"type": "string", "description": "Agent harness identifier (e.g. 'claude-code', 'cursor', 'antigravity', 'cicd')"},
                "execution_mode": {"type": "string", "enum": ["sequential", "parallel"], "description": "Execution mode (default: sequential)"},
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"},
                "change": {"type": "string", "description": "Target change ID"}
            },
            "required": ["skill"]
        }
    },
    {
        "name": "ship_checkpoint",
        "description": "Record an immutable git ref and receipt checkpoint for a gate (e.g. 'design' or 'implementation').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "gate": {"type": "string", "description": "Gate to checkpoint ('design' or 'implementation')"},
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"},
                "change": {"type": "string", "description": "Target change ID"}
            },
            "required": ["gate"]
        }
    },
    {
        "name": "ship_rollback",
        "description": "Restore a whole checkout checkpoint only after explicit operator authorization, backing up affected files. Refuses by default.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "gate": {"type": "string", "description": "Gate checkpoint to restore ('design' or 'implementation')"},
                "force": {"type": "boolean", "description": "True only after the operator authorizes whole-checkout restoration, including unrelated edits."},
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"},
                "change": {"type": "string", "description": "Target change ID"}
            },
            "required": ["gate"]
        }
    },
    {
        "name": "ship_approve_design",
        "description": "Record design specification approval in state ledger with verified design SHA-256 fingerprint.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "change": {"type": "string", "description": "Target change ID"},
                "fingerprint": {"type": "string", "description": "SHA-256 fingerprint of the approved design package"},
                "approved_by": {"type": "string", "description": "Identity of the approver (e.g. 'session-user' or 'lead-architect')"},
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"}
            },
            "required": ["change", "fingerprint"]
        }
    },
    {
        "name": "ship_record_tests",
        "description": "Record test execution receipt (passed/failed) in the lifecycle state ledger.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "passed": {"type": "boolean", "description": "True if test suite passed cleanly, False if failed"},
                "output": {"type": "string", "description": "Optional raw or trimmed test runner terminal output"},
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"},
                "change": {"type": "string", "description": "Target change ID"}
            },
            "required": ["passed"]
        }
    },
    {
        "name": "ship_record_review",
        "description": "Validate and record Evidence-Based Judge review report in the lifecycle state ledger.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_path": {"type": "string", "description": "Path to review_report.json"},
                "report_data": {"type": "object", "description": "Raw JSON report object (alternative to report_path)"},
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"},
                "change": {"type": "string", "description": "Target change ID"}
            },
            "required": []
        }
    },
    {
        "name": "ship_archive",
        "description": "Transactionally merge delta specs to openspec/specs/ and archive completed change package to openspec/archive/.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "change": {"type": "string", "description": "Change ID to archive (default: active change in .agentflow/state.json)"},
                "force": {"type": "boolean", "description": "Force archive even if review or task checks fail (default: false)"},
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"}
            },
            "required": []
        }
    },
    {
        "name": "ship_trailers",
        "description": "Generate RFC 5133 standard Git commit trailers based on current verified lifecycle evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "change": {"type": "string", "description": "Target change ID (default: active change in .agentflow/state.json)"},
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"}
            },
            "required": []
        }
    },
    {
        "name": "ship_doctor",
        "description": "Execute preflight diagnostics: Python version, git installation, skill directories, version parity, and ledger readability.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"}
            },
            "required": []
        }
    },
    {
        "name": "ship_tdd_verify",
        "description": "Verify test-driven development parity, classify changed files, audit test anti-patterns, and optionally trim test receipts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref_range": {"type": "string", "description": "Git revision range (e.g. 'main...HEAD')"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Specific files to audit instead of git diff"},
                "strict": {"type": "boolean", "description": "Fail if any ERROR-level findings are present (default: false)"},
                "trim_receipt": {"type": "string", "description": "Raw test runner output text to trim"},
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"}
            },
            "required": []
        }
    },
    {
        "name": "ship_simplify_scan",
        "description": "Scan codebase for simplify debt markers (TODO(simplify):), ceilings, and upgrade horizons.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Files or directories to scan (default: current directory)"},
                "strict": {"type": "boolean", "description": "Fail if any syntax errors or invalid markers are detected (default: false)"},
                "path": {"type": "string", "description": "Path to repository root (default: current working directory)"}
            },
            "required": []
        }
    },
    {
        "name": "ship_spike_run",
        "description": "Run statistical benchmark trials measuring command execution latency percentiles (p50, p90, p99), throughput, and failure rate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to benchmark"},
                "iterations": {"type": "integer", "description": "Number of iterations (default: 10)"},
                "concurrency": {"type": "integer", "description": "Concurrent workers (default: 1)"},
                "warmup": {"type": "integer", "description": "Warmup iterations before recording (default: 0)"},
                "timeout_sec": {"type": "number", "description": "Timeout per iteration in seconds (default: 60.0)"},
                "path": {"type": "string", "description": "Working directory for benchmark execution"},
                "agent_id": {"type": "string", "description": "Registered agent principal"},
                "operation": {"type": "string", "enum": ["EXECUTE"], "description": "Requires an EXECUTE capability"},
                "target": {"type": "string", "description": "Exact command string to authorize; must equal command"},
                "change": {"type": "string"}, "task_id": {"type": "string"},
                "session_id": {"type": "string"}, "lease_token": {"type": "string"}
            },
            "required": ["command", "agent_id", "operation", "target"]
        }
    },
    {
        "name": "ship_review_validate",
        "description": "Validate review report JSON against the 12-field finding schema contract and calculate PASS/FAIL verdict.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_path": {"type": "string", "description": "Path to review report JSON file"},
                "report_data": {"type": "object", "description": "Raw review report JSON dictionary"}
            },
            "required": []
        }
    }
]

TOOLS_MANIFEST.append({
    "name": "ship_verify",
    "description": "Execute configured project tests and record independent verification. Requires trusted MCP mutation opt-in.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"}, "change": {"type": "string"},
            "tiers": {"type": "array", "items": {"type": "string", "enum": ["execution", "grounding", "coverage", "mutation", "all"]}},
        },
    },
})

TOOLS_MANIFEST.extend([
    {
        "name": "ship_steps_begin",
        "description": "Begin a reported skill run with a snapshot of stable step IDs and skill versions. Returns run_id; does not verify agent behavior.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "skills": {"type": "array", "items": {"type": "string"}, "minItems": 1, "uniqueItems": True},
                "change": {"type": "string"},
                "task_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "session_id": {"type": "string"},
                "model": {"type": "string"}
            },
            "required": ["skills"]
        }
    },
    {
        "name": "ship_steps_record",
        "description": "Record a step start or result. Complete/fail require the active attempt_id. Completion requires evidence files; skip/fail require a reason. Returns the correlated event and attempt IDs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "run_id": {"type": "string"},
                "step_id": {"type": "string"},
                "status": {"type": "string", "enum": ["started", "completed", "failed", "skipped"]},
                "attempt_id": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}, "description": "Repository-relative receipt files, hashed at recording time"},
                "reason": {"type": "string"}
            },
            "required": ["run_id", "step_id", "status"]
        }
    },
    {
        "name": "ship_steps_report",
        "description": "Report every step in a run, including unobserved steps, unfinished attempts, skips, failures and changed/missing evidence. Not a quality verdict.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "run_id": {"type": "string"}},
            "required": ["run_id"]
        }
    }
])
