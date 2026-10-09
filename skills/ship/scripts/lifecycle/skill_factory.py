"""
skill_factory.py – /skill Skill Factory & Compatibility Engine.

Provides an authoritative end-to-end Skill Factory pipeline:
  requirements ➔ SKILL.md ➔ scripts/references ➔ evals ➔ package ➔ version

Features:
1. Native Claude Skills output: generates standard SKILL.md + scripts/ + references/ + assets/ + evals/
2. Skill × Model × Host compatibility matrix: assesses compatibility across Claude, Codex, Cursor,
   Antigravity, VS Code Copilot, and Gemini.
3. Run cost and usage metadata: computes token-level cost estimates and tracking across runs.

Zero external dependencies: 100% Python 3.10+ standard library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import re
import tarfile
from typing import Any, Dict, List, Optional, Union
import zipfile


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Pillar 3: Skill × Model × Host Compatibility Matrix
# ---------------------------------------------------------------------------

class CompatibilityLevel(str, Enum):
    FULL = "FULL"            # Fully supported with zero degradation
    PARTIAL = "PARTIAL"      # Supported with minor feature fallback
    DEGRADED = "DEGRADED"    # Strongly degraded, core capabilities missing
    UNSUPPORTED = "UNSUPPORTED"


class HostFeature(str, Enum):
    TERMINAL_EXECUTION = "terminal_execution"
    FILESYSTEM_MUTATIONS = "filesystem_mutations"
    MCP_SERVERS = "mcp_servers"
    SUBAGENTS = "subagents"
    DYNAMIC_CONTEXT_LOADING = "dynamic_context_loading"
    INTERACTIVE_PROMPTS = "interactive_prompts"
    PERSISTENT_MEMORY = "persistent_memory"


@dataclass
class HostProfile:
    name: str
    display_name: str
    features: List[HostFeature] = field(default_factory=list)
    notes: str = ""

    def has_feature(self, feat: Union[HostFeature, str]) -> bool:
        f_val = feat.value if hasattr(feat, "value") else str(feat)
        return any(f.value == f_val if hasattr(f, "value") else str(f) == f_val for f in self.features)


KNOWN_HOSTS: Dict[str, HostProfile] = {
    "claude_code": HostProfile(
        name="claude_code",
        display_name="Claude Code (CLI)",
        features=[
            HostFeature.TERMINAL_EXECUTION,
            HostFeature.FILESYSTEM_MUTATIONS,
            HostFeature.MCP_SERVERS,
            HostFeature.SUBAGENTS,
            HostFeature.DYNAMIC_CONTEXT_LOADING,
            HostFeature.INTERACTIVE_PROMPTS,
        ],
        notes="First-class native Claude agent environment",
    ),
    "antigravity": HostProfile(
        name="antigravity",
        display_name="Google Antigravity",
        features=[
            HostFeature.TERMINAL_EXECUTION,
            HostFeature.FILESYSTEM_MUTATIONS,
            HostFeature.MCP_SERVERS,
            HostFeature.SUBAGENTS,
            HostFeature.DYNAMIC_CONTEXT_LOADING,
            HostFeature.INTERACTIVE_PROMPTS,
        ],
        notes="High-autonomy dual-sandbox pair programmer",
    ),
    "claude_desktop": HostProfile(
        name="claude_desktop",
        display_name="Claude Desktop",
        features=[
            HostFeature.MCP_SERVERS,
            HostFeature.DYNAMIC_CONTEXT_LOADING,
            HostFeature.INTERACTIVE_PROMPTS,
        ],
        notes="Relies on MCP servers for filesystem and command side-effects",
    ),
    "cursor": HostProfile(
        name="cursor",
        display_name="Cursor IDE",
        features=[
            HostFeature.TERMINAL_EXECUTION,
            HostFeature.FILESYSTEM_MUTATIONS,
            HostFeature.DYNAMIC_CONTEXT_LOADING,
        ],
        notes="Editor-integrated agent without native child subagent spawning",
    ),
    "codex": HostProfile(
        name="codex",
        display_name="OpenAI Codex / Assistants",
        features=[
            HostFeature.FILESYSTEM_MUTATIONS,
            HostFeature.DYNAMIC_CONTEXT_LOADING,
        ],
        notes="Sandboxed code interpreter without native terminal shell access",
    ),
    "vscode_copilot": HostProfile(
        name="vscode_copilot",
        display_name="VS Code GitHub Copilot",
        features=[
            HostFeature.FILESYSTEM_MUTATIONS,
            HostFeature.DYNAMIC_CONTEXT_LOADING,
        ],
        notes="Limited shell and MCP execution primitives",
    ),
}


@dataclass
class ModelProfile:
    name: str
    display_name: str
    tier: str  # "advanced" | "reasoning" | "fast"
    reasoning_score: int  # 1-10
    native_tool_use: bool = True
    context_window_k: int = 200


KNOWN_MODELS: Dict[str, ModelProfile] = {
    "claude-3-7-sonnet": ModelProfile(
        name="claude-3-7-sonnet",
        display_name="Claude 3.7 Sonnet",
        tier="advanced",
        reasoning_score=10,
        context_window_k=200,
    ),
    "claude-3-5-sonnet": ModelProfile(
        name="claude-3-5-sonnet",
        display_name="Claude 3.5 Sonnet",
        tier="advanced",
        reasoning_score=9,
        context_window_k=200,
    ),
    "claude-3-5-haiku": ModelProfile(
        name="claude-3-5-haiku",
        display_name="Claude 3.5 Haiku",
        tier="fast",
        reasoning_score=6,
        context_window_k=200,
    ),
    "claude-3-opus": ModelProfile(
        name="claude-3-opus",
        display_name="Claude 3 Opus",
        tier="advanced",
        reasoning_score=9,
        context_window_k=200,
    ),
    "gpt-4o": ModelProfile(
        name="gpt-4o",
        display_name="OpenAI GPT-4o",
        tier="advanced",
        reasoning_score=9,
        context_window_k=128,
    ),
    "o3-mini": ModelProfile(
        name="o3-mini",
        display_name="OpenAI o3-mini",
        tier="reasoning",
        reasoning_score=9,
        context_window_k=200,
    ),
    "gemini-2-0-pro": ModelProfile(
        name="gemini-2-0-pro",
        display_name="Gemini 2.0 Pro",
        tier="advanced",
        reasoning_score=9,
        context_window_k=1000,
    ),
    "gemini-2-0-flash": ModelProfile(
        name="gemini-2-0-flash",
        display_name="Gemini 2.0 Flash",
        tier="fast",
        reasoning_score=7,
        context_window_k=1000,
    ),
}


@dataclass
class SkillCompatibility:
    """Declarative compatibility rules specified in a skill's manifest."""
    required_host_features: List[str] = field(default_factory=lambda: [
        "filesystem_mutations",
        "terminal_execution",
    ])
    recommended_model_tier: str = "advanced"  # "advanced" | "reasoning" | "fast"
    min_reasoning_score: int = 7
    host_overrides: Dict[str, str] = field(default_factory=dict)
    model_overrides: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "required_host_features": list(self.required_host_features),
            "recommended_model_tier": self.recommended_model_tier,
            "min_reasoning_score": self.min_reasoning_score,
            "host_overrides": dict(self.host_overrides),
            "model_overrides": dict(self.model_overrides),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillCompatibility":
        return cls(
            required_host_features=list(data.get("required_host_features") or [
                "filesystem_mutations", "terminal_execution"
            ]),
            recommended_model_tier=str(data.get("recommended_model_tier", "advanced")),
            min_reasoning_score=int(data.get("min_reasoning_score", 7)),
            host_overrides=dict(data.get("host_overrides") or {}),
            model_overrides=dict(data.get("model_overrides") or {}),
        )


@dataclass
class CompatibilityResult:
    skill_name: str
    host: str
    model: str
    level: CompatibilityLevel
    reasons: List[str] = field(default_factory=list)
    fallbacks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "host": self.host,
            "model": self.model,
            "level": self.level.value,
            "reasons": list(self.reasons),
            "fallbacks": list(self.fallbacks),
        }


def evaluate_compatibility(
    skill_compat: SkillCompatibility,
    skill_name: str,
    host_name: str,
    model_name: str,
) -> CompatibilityResult:
    """Evaluate compatibility for a single (skill, host, model) triplet."""
    # Check manual overrides first
    if host_name in skill_compat.host_overrides:
        override = skill_compat.host_overrides[host_name].upper()
        if override in CompatibilityLevel.__members__:
            return CompatibilityResult(
                skill_name=skill_name,
                host=host_name,
                model=model_name,
                level=CompatibilityLevel(override),
                reasons=[f"Explicit host override defined in skill manifest: {override}"],
            )

    host_prof = KNOWN_HOSTS.get(host_name) or HostProfile(
        name=host_name,
        display_name=host_name,
        features=[HostFeature.FILESYSTEM_MUTATIONS, HostFeature.TERMINAL_EXECUTION],
    )
    model_prof = KNOWN_MODELS.get(model_name) or ModelProfile(
        name=model_name,
        display_name=model_name,
        tier="advanced",
        reasoning_score=8,
    )

    reasons: List[str] = []
    fallbacks: List[str] = []
    missing_features: List[str] = []

    for req_feat in skill_compat.required_host_features:
        if not host_prof.has_feature(req_feat):
            missing_features.append(req_feat)

    if missing_features:
        # Check if terminal execution is missing but MCP exists
        if "terminal_execution" in missing_features and host_prof.has_feature(HostFeature.MCP_SERVERS):
            reasons.append("Host lacks direct terminal execution; requires MCP adapter fallback.")
            fallbacks.append("Execute scripts and validations via MCP tool dispatch.")
            level = CompatibilityLevel.PARTIAL
        elif "subagents" in missing_features:
            reasons.append("Host does not support multi-agent child subagent dispatch.")
            fallbacks.append("Sequential single-agent turn fallback mode.")
            level = CompatibilityLevel.PARTIAL
        else:
            reasons.append(f"Host lacks critical required features: {', '.join(missing_features)}")
            return CompatibilityResult(
                skill_name=skill_name,
                host=host_name,
                model=model_name,
                level=CompatibilityLevel.UNSUPPORTED,
                reasons=reasons,
                fallbacks=["Switch to a host environment with terminal and filesystem capabilities."],
            )
    else:
        level = CompatibilityLevel.FULL

    # Evaluate model reasoning score
    if model_prof.reasoning_score < skill_compat.min_reasoning_score:
        reasons.append(
            f"Model reasoning score ({model_prof.reasoning_score}) is below recommended "
            f"minimum ({skill_compat.min_reasoning_score}). Complex invariants may fail."
        )
        if level == CompatibilityLevel.FULL:
            level = CompatibilityLevel.DEGRADED

    return CompatibilityResult(
        skill_name=skill_name,
        host=host_name,
        model=model_name,
        level=level,
        reasons=reasons,
        fallbacks=fallbacks,
    )


def generate_compatibility_matrix(
    skill_compat: SkillCompatibility,
    skill_name: str,
    hosts: Optional[List[str]] = None,
    models: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Generate a comprehensive 2D matrix of host × model compatibility."""
    target_hosts = hosts or list(KNOWN_HOSTS.keys())
    target_models = models or list(KNOWN_MODELS.keys())

    matrix: Dict[str, Dict[str, str]] = {}
    details: List[Dict[str, Any]] = []

    for h in target_hosts:
        matrix[h] = {}
        for m in target_models:
            res = evaluate_compatibility(skill_compat, skill_name, h, m)
            matrix[h][m] = res.level.value
            details.append(res.to_dict())

    return {
        "skill": skill_name,
        "hosts": target_hosts,
        "models": target_models,
        "matrix": matrix,
        "details": details,
    }


def render_compatibility_markdown(matrix_data: Dict[str, Any]) -> str:
    """Format compatibility matrix as a GitHub-flavored markdown table."""
    skill = matrix_data["skill"]
    hosts = matrix_data["hosts"]
    models = matrix_data["models"]
    matrix = matrix_data["matrix"]

    lines = [
        f"### 🌐 Compatibility Matrix: `{skill}`",
        "",
        "| Host Profile | " + " | ".join(models) + " |",
        "| :--- | " + " | ".join([":---:"] * len(models)) + " |",
    ]

    icons = {
        "FULL": "🟢 Full",
        "PARTIAL": "🟡 Partial",
        "DEGRADED": "🟠 Degraded",
        "UNSUPPORTED": "🔴 Unsupported",
    }

    for h in hosts:
        h_display = KNOWN_HOSTS.get(h, HostProfile(name=h, display_name=h)).display_name
        row = [f"**{h_display}**"]
        for m in models:
            val = matrix.get(h, {}).get(m, "UNSUPPORTED")
            row.append(icons.get(val, val))
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pillar 4: Run Cost & Usage Metadata
# ---------------------------------------------------------------------------

@dataclass
class ModelPricing:
    input_per_m: float       # $ per 1,000,000 input tokens
    output_per_m: float      # $ per 1,000,000 output tokens
    cache_read_per_m: float  # $ per 1,000,000 cached input tokens


MODEL_PRICING_TABLE: Dict[str, ModelPricing] = {
    "claude-3-7-sonnet": ModelPricing(3.00, 15.00, 0.30),
    "claude-3-5-sonnet": ModelPricing(3.00, 15.00, 0.30),
    "claude-3-5-haiku": ModelPricing(0.80, 4.00, 0.08),
    "claude-3-opus": ModelPricing(15.00, 75.00, 1.50),
    "gpt-4o": ModelPricing(2.50, 10.00, 1.25),
    "gpt-4o-mini": ModelPricing(0.15, 0.60, 0.075),
    "o3-mini": ModelPricing(1.10, 4.40, 0.55),
    "gemini-2-0-pro": ModelPricing(3.50, 14.00, 0.875),
    "gemini-2-0-flash": ModelPricing(0.10, 0.40, 0.025),
    "default": ModelPricing(3.00, 15.00, 0.30),
}


def get_model_pricing(model_name: str) -> ModelPricing:
    clean = model_name.lower().strip()
    for key, pricing in MODEL_PRICING_TABLE.items():
        if key in clean or clean.startswith(key):
            return pricing
    return MODEL_PRICING_TABLE["default"]


def compute_cost_usd(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> float:
    """Calculate precise USD cost given model name and token breakdown."""
    pricing = get_model_pricing(model_name)
    uncached_inputs = max(0, input_tokens - cached_tokens)
    cost = (
        (uncached_inputs / 1_000_000.0) * pricing.input_per_m
        + (cached_tokens / 1_000_000.0) * pricing.cache_read_per_m
        + (output_tokens / 1_000_000.0) * pricing.output_per_m
    )
    return round(cost, 6)


@dataclass
class RunUsageMetadata:
    """Detailed telemetry and economic tracking for an agent run or turn."""
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    duration_ms: float = 0.0
    tool_calls_count: int = 0
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    estimated_cost_usd: float = 0.0
    timestamp: str = field(default_factory=_now_iso)

    def __post_init__(self):
        if not self.total_tokens:
            self.total_tokens = self.input_tokens + self.output_tokens
        if not self.estimated_cost_usd:
            self.estimated_cost_usd = compute_cost_usd(
                self.model, self.input_tokens, self.output_tokens, self.cached_tokens
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "total_tokens": self.total_tokens,
            "duration_ms": round(self.duration_ms, 2),
            "tool_calls_count": self.tool_calls_count,
            "tool_calls": list(self.tool_calls),
            "estimated_cost_usd": self.estimated_cost_usd,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunUsageMetadata":
        return cls(
            model=str(data.get("model", "claude-3-7-sonnet")),
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            cached_tokens=int(data.get("cached_tokens", 0)),
            total_tokens=int(data.get("total_tokens", 0)),
            duration_ms=float(data.get("duration_ms", 0.0)),
            tool_calls_count=int(data.get("tool_calls_count", 0)),
            tool_calls=list(data.get("tool_calls", [])),
            estimated_cost_usd=float(data.get("estimated_cost_usd", 0.0)),
            timestamp=str(data.get("timestamp", _now_iso())),
        )


# ---------------------------------------------------------------------------
# Pillar 1 & 2: Skill Requirements & Factory Engine
# ---------------------------------------------------------------------------

@dataclass
class SkillEvalScenario:
    name: str
    description: str
    input_prompt: str
    expected_behavior: str
    required_tool_calls: List[str] = field(default_factory=list)
    forbidden_patterns: List[str] = field(default_factory=list)
    evidence_assertions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_prompt": self.input_prompt,
            "expected_behavior": self.expected_behavior,
            "required_tool_calls": list(self.required_tool_calls),
            "forbidden_patterns": list(self.forbidden_patterns),
            "evidence_assertions": list(self.evidence_assertions),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillEvalScenario":
        return cls(
            name=str(data.get("name", "unnamed_scenario")),
            description=str(data.get("description", "")),
            input_prompt=str(data.get("input_prompt", "")),
            expected_behavior=str(data.get("expected_behavior", "")),
            required_tool_calls=list(data.get("required_tool_calls", [])),
            forbidden_patterns=list(data.get("forbidden_patterns", [])),
            evidence_assertions=list(data.get("evidence_assertions", [])),
        )


@dataclass
class SkillRequirements:
    """Formal specifications required to generate a complete native Claude skill."""
    name: str                                  # kebab-case skill identifier
    role: str                                  # Agent persona / title
    description: str                           # Description for YAML frontmatter & discovery
    domain: str = "engineering"                # Functional domain
    trigger_phrases: List[str] = field(default_factory=list)
    hard_constraints: List[str] = field(default_factory=list)
    turn_contract_items: List[str] = field(default_factory=list)
    workflow_steps: List[str] = field(default_factory=list)
    tools_required: List[str] = field(default_factory=list)
    compatibility: SkillCompatibility = field(default_factory=SkillCompatibility)
    version: str = "1.0.0"
    author: str = "AgentFlow"
    eval_scenarios: List[SkillEvalScenario] = field(default_factory=list)
    model: Optional[str] = None
    effort: Optional[str] = None
    allowed_tools: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "description": self.description,
            "domain": self.domain,
            "trigger_phrases": list(self.trigger_phrases),
            "hard_constraints": list(self.hard_constraints),
            "turn_contract_items": list(self.turn_contract_items),
            "workflow_steps": list(self.workflow_steps),
            "tools_required": list(self.tools_required),
            "compatibility": self.compatibility.to_dict(),
            "version": self.version,
            "author": self.author,
            "eval_scenarios": [s.to_dict() for s in self.eval_scenarios],
            "model": self.model,
            "effort": self.effort,
            "allowed_tools": list(self.allowed_tools),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillRequirements":
        compat_raw = data.get("compatibility", {})
        compat = SkillCompatibility.from_dict(compat_raw) if isinstance(compat_raw, dict) else SkillCompatibility()
        scenarios = [
            SkillEvalScenario.from_dict(s)
            for s in data.get("eval_scenarios", [])
            if isinstance(s, dict)
        ]
        return cls(
            name=re.sub(r"[^a-z0-9_-]", "-", str(data.get("name", "new-skill")).lower().strip()),
            role=str(data.get("role", "Specialist Engineer")),
            description=str(data.get("description", "")),
            domain=str(data.get("domain", "engineering")),
            trigger_phrases=list(data.get("trigger_phrases", [])),
            hard_constraints=list(data.get("hard_constraints", [])),
            turn_contract_items=list(data.get("turn_contract_items", [])),
            workflow_steps=list(data.get("workflow_steps", [])),
            tools_required=list(data.get("tools_required", [])),
            compatibility=compat,
            version=str(data.get("version", "1.0.0")),
            author=str(data.get("author", "AgentFlow")),
            eval_scenarios=scenarios,
            model=data.get("model"),
            effort=data.get("effort"),
            allowed_tools=list(data.get("allowed_tools", [])),
        )


@dataclass
class SkillPackageArtifact:
    """Result of skill factory synthesis and packaging."""
    name: str
    version: str
    output_dir: Path
    skill_md: Path
    version_file: Path
    scripts: List[Path] = field(default_factory=list)
    references: List[Path] = field(default_factory=list)
    assets: List[Path] = field(default_factory=list)
    evals: List[Path] = field(default_factory=list)
    archive_file: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "output_dir": str(self.output_dir),
            "skill_md": str(self.skill_md),
            "version_file": str(self.version_file),
            "scripts": [str(p) for p in self.scripts],
            "references": [str(p) for p in self.references],
            "assets": [str(p) for p in self.assets],
            "evals": [str(p) for p in self.evals],
            "archive_file": str(self.archive_file) if self.archive_file else None,
        }


class SkillFactory:
    """
    Authoritative factory engine for compiling, packaging, and versioning
    standard Native Claude Agent Skills:
      requirements ➔ SKILL.md ➔ scripts/references ➔ evals ➔ package ➔ version
    """

    def __init__(self, repo_root: Optional[Path] = None) -> None:
        self.repo_root = Path(repo_root or Path.cwd()).resolve()

    # ------------------------------------------------------------------ #
    # 1. SKILL.md Generation (Standard Native Claude Skills Output)      #
    # ------------------------------------------------------------------ #

    def generate_skill_md(self, req: SkillRequirements) -> str:
        """Synthesize authoritative SKILL.md compliant with native agent standards."""
        # Ensure default constraints if none provided
        constraints = list(req.hard_constraints)
        if not constraints:
            constraints = [
                "Verify invariants autonomously before concluding turn.",
                "Zero conversational preamble: execute deterministic inspection first.",
                "Never silently mask or suppress defects.",
            ]

        # Ensure default turn contract items
        contracts = list(req.turn_contract_items)
        if not contracts:
            contracts = [
                "1. Autonomously discovered facts and baseline context without prompting.",
                "2. Validated domain state using scripts/validate_" + req.name.replace("-", "_") + ".py.",
                "3. Verified output artifacts conform to schema.",
            ]

        # Ensure default workflow steps
        steps = list(req.workflow_steps)
        if not steps:
            steps = [
                "1. Autonomous Inspection: Discover current context and relevant code/configuration.",
                "2. Deterministic Verification: Execute verification script to detect regressions or baseline state.",
                "3. Targeted Execution: Perform required modifications or analysis strictly within domain boundaries.",
                "4. Validation & Contract Delivery: Re-run verification and report structured evidence.",
            ]

        # Trigger phrases description enhancement
        desc = req.description.strip()
        if req.trigger_phrases:
            triggers_str = ", ".join(f'"{t}"' for t in req.trigger_phrases)
            if "Use whenever" not in desc:
                desc += f" Use whenever the user asks for {triggers_str}."

        frontmatter_lines = [
            "---",
            f"name: {req.name}",
            f"description: {desc}",
        ]
        if req.model:
            frontmatter_lines.append(f"model: {req.model}")
        if req.effort:
            frontmatter_lines.append(f"effort: {req.effort}")
        if req.allowed_tools:
            frontmatter_lines.append("allowed-tools:")
            for tool in req.allowed_tools:
                frontmatter_lines.append(f"  - {tool}")
        frontmatter_lines.extend([
            f"version: {req.version}",
            "compatibility:",
            f"  recommended_tier: {req.compatibility.recommended_model_tier}",
            f"  min_reasoning: {req.compatibility.min_reasoning_score}",
            "---",
        ])

        body_lines = [
            f"# {req.name.replace('-', ' ').title()} Engine",
            "",
            f"**Role**: {req.role}.",
            "",
            "For script commands in the references, resolve `SKILLS_DIR` to the absolute parent directory",
            "of this installed skill folder. Run scripts from that location while keeping the working directory",
            "set to the consumer project.",
            "",
            "> [!IMPORTANT]",
            "> **Zero Conversational Filler**: Never say 'Certainly' or 'I would be happy to'.",
            "> Begin immediately with autonomous inspection, verification, or structured deliverables.",
            "",
            "<hard_constraints>",
        ]
        for c in constraints:
            body_lines.append(f"- {c}")
        body_lines.append("</hard_constraints>")
        body_lines.append("")

        body_lines.append("<turn_contract>")
        body_lines.append("Verify before ending the turn:")
        for idx, item in enumerate(contracts, start=1):
            prefix = "" if item.startswith(f"{idx}.") or item.startswith("✓") else f"✓ {idx}. "
            body_lines.append(f"{prefix}{item}")
        body_lines.append("</turn_contract>")
        body_lines.append("")

        body_lines.append("## Operating Workflow")
        body_lines.append("")
        for s in steps:
            body_lines.append(s)
        body_lines.append("")

        body_lines.append("## Deterministic Verification")
        body_lines.append("")
        script_name = f"validate_{req.name.replace('-', '_')}.py"
        body_lines.append(f"Execute the companion deterministic validator in `scripts/{script_name}`:")
        body_lines.append("```bash")
        body_lines.append(f"python3 scripts/{script_name} --strict")
        body_lines.append("```")
        body_lines.append("")

        return "\n".join(frontmatter_lines) + "\n\n" + "\n".join(body_lines) + "\n"

    # ------------------------------------------------------------------ #
    # 2. Companion Scripts Generation                                    #
    # ------------------------------------------------------------------ #

    def generate_validator_script(self, req: SkillRequirements) -> str:
        """Create zero-dependency companion python validation script."""
        script_module = req.name.replace("-", "_")
        code = f'''#!/usr/bin/env python3
"""
validate_{script_module}.py – Deterministic validator for {req.name} skill.

Validates that artifacts, configurations, and outputs conform to {req.name} invariants.
Zero external dependencies (Python 3.10+ standard library).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List


def validate_environment(repo_root: Path, strict: bool = False) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Invariant check: repository containment
    if not (repo_root / ".git").exists() and not (repo_root / ".agentflow.json").exists():
        warnings.append("Workspace does not appear to be an initialized git repository or AgentFlow project.")

    # 2. Add domain-specific checks here
    status = "PASSED" if not errors else "FAILED"
    if warnings and status == "PASSED" and strict:
        status = "FAILED"

    return {{
        "status": status,
        "skill": "{req.name}",
        "version": "{req.version}",
        "passed": status == "PASSED",
        "errors": errors,
        "warnings": warnings,
    }}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate {req.name} invariants.")
    parser.add_argument("--path", "-p", default=".", help="Root path of target project")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON")
    args = parser.parse_args()

    target = Path(args.path).resolve()
    result = validate_environment(target, strict=args.strict)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status_icon = "✅" if result["passed"] else "❌"
        print(f"{{status_icon}} {req.name} validation: {{result['status']}}")
        for err in result["errors"]:
            print(f"  • Error: {{err}}")
        for warn in result["warnings"]:
            print(f"  • Warning: {{warn}}")

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
'''
        return code

    # ------------------------------------------------------------------ #
    # 3. Companion References Generation                                 #
    # ------------------------------------------------------------------ #

    def generate_reference_guide(self, req: SkillRequirements) -> str:
        """Create on-demand documentation loaded by agents when relevant."""
        title = req.name.replace("-", " ").title()
        rule_items = "\n".join(f"- **{c}**" for c in req.hard_constraints) if req.hard_constraints else "- No violations of repository integrity."
        tool_items = "\n".join(f"- `{t}`" for t in req.tools_required) if req.tools_required else "- Standard read/write and execution tools."
        script_module = req.name.replace("-", "_")

        return f"""# {title} Reference Guide

## 1. Domain Overview
{req.description}

## 2. Invariants & Rules
The following hard rules MUST be obeyed during execution:
{rule_items}

## 3. Tool Interoperability
Required tools for this skill:
{tool_items}

## 4. Troubleshooting & Fallbacks
If execution encounters a degraded host or model:
- Re-run `python3 scripts/validate_{script_module}.py` to inspect baseline errors.
- Never silently omit evidence or bypass required validation gates.
"""

    # ------------------------------------------------------------------ #
    # 4. Companion Evals Generation                                      #
    # ------------------------------------------------------------------ #

    def generate_eval_cases(self, req: SkillRequirements) -> List[Dict[str, Any]]:
        """Generate structured behavioral evaluation scenarios."""
        scenarios: List[Dict[str, Any]] = []
        if req.eval_scenarios:
            for s in req.eval_scenarios:
                scenarios.append(s.to_dict())
        else:
            # Generate standard default scenarios (positive, negative, edge)
            scenarios.append({
                "name": f"{req.name}_clean_execution",
                "description": f"Standard invocation of {req.name} in clean repository",
                "input_prompt": f"Run {req.name} on the current project and verify all invariants.",
                "expected_behavior": "Executes verification autonomously and reports clean status.",
                "required_tool_calls": [f"scripts/validate_{req.name.replace('-', '_')}.py"],
                "forbidden_patterns": ["Certainly", "I would be happy to"],
                "evidence_assertions": ["status: PASSED"],
            })
            scenarios.append({
                "name": f"{req.name}_defect_detection",
                "description": f"Ensures {req.name} flags invalid invariants without silent pass",
                "input_prompt": f"Audit {req.name} when an invariant violation is present.",
                "expected_behavior": "Identifies violation and refuses to declare clean status.",
                "required_tool_calls": [],
                "forbidden_patterns": ["Everything looks good!"],
                "evidence_assertions": ["status: FAILED"],
            })
        return scenarios

    # ------------------------------------------------------------------ #
    # 5. Full Native Claude Skill Builder & Packaging                     #
    # ------------------------------------------------------------------ #

    def build_skill(
        self,
        req: SkillRequirements,
        output_dir: Optional[Path] = None,
        package_archive: bool = False,
        archive_format: str = "tar.gz",
    ) -> SkillPackageArtifact:
        """
        Execute full Skill Factory pipeline:
        requirements ➔ SKILL.md ➔ scripts/references ➔ evals ➔ package ➔ version
        """
        base_dir = output_dir or (self.repo_root / "skills" / req.name)
        base_dir.mkdir(parents=True, exist_ok=True)

        scripts_dir = base_dir / "scripts"
        refs_dir = base_dir / "references"
        assets_dir = base_dir / "assets"
        evals_dir = base_dir / "evals"

        scripts_dir.mkdir(exist_ok=True)
        refs_dir.mkdir(exist_ok=True)
        assets_dir.mkdir(exist_ok=True)
        evals_dir.mkdir(exist_ok=True)

        # 1. Generate SKILL.md
        skill_md_path = base_dir / "SKILL.md"
        skill_md_path.write_text(self.generate_skill_md(req), encoding="utf-8")

        # 2. Generate VERSION & CHANGELOG
        version_file = base_dir / "VERSION"
        version_file.write_text(f"{req.version}\n", encoding="utf-8")

        changelog_file = base_dir / "CHANGELOG.md"
        if not changelog_file.exists():
            changelog_file.write_text(
                f"# Changelog - {req.name}\n\n## [{req.version}] - {_now_iso()[:10]}\n- Initial release synthesized by /skill Skill Factory.\n",
                encoding="utf-8",
            )

        # 3. Generate scripts/
        script_path = scripts_dir / f"validate_{req.name.replace('-', '_')}.py"
        script_path.write_text(self.generate_validator_script(req), encoding="utf-8")
        try:
            os.chmod(script_path, 0o755)
        except Exception:
            pass

        # 4. Generate references/
        ref_path = refs_dir / f"{req.name.replace('-', '_')}_guide.md"
        ref_path.write_text(self.generate_reference_guide(req), encoding="utf-8")

        # 5. Generate assets/
        asset_meta = assets_dir / "manifest.json"
        asset_meta.write_text(
            json.dumps({
                "skill": req.name,
                "version": req.version,
                "domain": req.domain,
                "created_at": _now_iso(),
            }, indent=2),
            encoding="utf-8",
        )

        # 6. Generate evals/
        evals_file = evals_dir / "eval_cases.json"
        evals_file.write_text(json.dumps(self.generate_eval_cases(req), indent=2), encoding="utf-8")

        created_scripts = [script_path]
        created_refs = [ref_path]
        created_assets = [asset_meta]
        created_evals = [evals_file]

        archive_path: Optional[Path] = None
        if package_archive:
            archive_path = self.package_skill(base_dir, archive_format=archive_format)

        return SkillPackageArtifact(
            name=req.name,
            version=req.version,
            output_dir=base_dir,
            skill_md=skill_md_path,
            version_file=version_file,
            scripts=created_scripts,
            references=created_refs,
            assets=created_assets,
            evals=created_evals,
            archive_file=archive_path,
        )

    # ------------------------------------------------------------------ #
    # 6. Packaging & Distribution                                        #
    # ------------------------------------------------------------------ #

    def package_skill(self, skill_dir: Path, archive_format: str = "tar.gz") -> Path:
        """Create distributable compressed package for a skill directory."""
        skill_path = Path(skill_dir).resolve()
        skill_name = skill_path.name
        dist_dir = self.repo_root / "dist" / "skills"
        dist_dir.mkdir(parents=True, exist_ok=True)

        if archive_format in ("zip", ".zip"):
            archive_path = dist_dir / f"{skill_name}.zip"
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(skill_path):
                    for file in files:
                        full_p = Path(root) / file
                        rel_p = full_p.relative_to(skill_path.parent)
                        zf.write(full_p, arcname=str(rel_p))
            return archive_path
        else:
            archive_path = dist_dir / f"{skill_name}.tar.gz"
            with tarfile.open(archive_path, "w:gz") as tf:
                tf.add(skill_path, arcname=skill_name)
            return archive_path

    # ------------------------------------------------------------------ #
    # 7. Skill Verification & Linting                                    #
    # ------------------------------------------------------------------ #

    def validate_skill_structure(self, skill_dir: Path) -> Dict[str, Any]:
        """Verify that an existing skill directory satisfies native Claude agent standards."""
        sdir = Path(skill_dir).resolve()
        errors: List[str] = []
        warnings: List[str] = []

        skill_md = sdir / "SKILL.md"
        if not skill_md.exists():
            errors.append("Missing SKILL.md root instruction file")
        else:
            content = skill_md.read_text(encoding="utf-8")
            if not content.startswith("---"):
                errors.append("SKILL.md missing standard YAML frontmatter")
            if "name:" not in content or "description:" not in content:
                errors.append("SKILL.md YAML frontmatter missing 'name' or 'description'")
            if "<hard_constraints>" not in content:
                warnings.append("SKILL.md does not define explicit <hard_constraints>")
            if "<turn_contract>" not in content:
                warnings.append("SKILL.md does not define an explicit <turn_contract>")

        scripts_dir = sdir / "scripts"
        if not scripts_dir.exists() or not any(scripts_dir.glob("*.py")):
            warnings.append("Skill lacks deterministic helper scripts in scripts/")

        refs_dir = sdir / "references"
        if not refs_dir.exists():
            warnings.append("Skill lacks references/ directory for on-demand context")

        version_file = sdir / "VERSION"
        version_str = "unknown"
        if version_file.exists():
            version_str = version_file.read_text(encoding="utf-8").strip()
        else:
            warnings.append("Skill lacks a VERSION file")

        valid = len(errors) == 0
        return {
            "valid": valid,
            "skill": sdir.name,
            "version": version_str,
            "errors": errors,
            "warnings": warnings,
            "path": str(sdir),
        }
