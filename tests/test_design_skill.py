"""Unit and regression tests for design skill validation engine (validate_design.py / design.py)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ship.tools import design
from tests.evaluation.evaluate_design_rubric import DesignRubricEvaluator

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "design"

VALID_CANONICAL_ADR = """# ADR-0001: Distributed Order Execution Engine

- **Status**: ACCEPTED
- **Date**: 2026-10-06
- **Architects**: User & Principal Systems Architect
- **Target Components**: OrderExecutionService, Postgres, RedisStreams
- **Related Issues / PRDs**: #101

---

## 1. Context & Problem Statement
Order processing currently experiences database lock contention under burst flash-sales.
We need an event-driven decoupled architecture with strict order execution invariants.

---

## 2. Decision Drivers
- Driver 1: Sub-15ms p99 execution latency
- Driver 2: 5,000 TPS concurrent write capability
- Driver 3: Zero double-spend or duplicate order execution

---

## 3. Considered Options

### Option A: Synchronous Two-Phase Commit across Postgres shards
- **Pros**: Strong immediate consistency
- **Cons**: High latency, brittle availability

### Option B: Transactional Outbox with Redis Streams Partitioning *(Chosen)*
- **Pros**: High throughput, isolated failure domains
- **Cons**: Requires consumer deduplication and eventual consistency

---

## 4. Decision Outcome & Architecture Specification

### 4.1. Chosen Architecture
We will use Postgres transactional outbox combined with Redis Streams consumer groups partitioned by customer_id.

### 4.2. Invariants & Guarantees
- **State & Consistency**: Postgres is the single source of truth; atomic writes within database transactions.
- **Concurrency & Locking**: Optimistic locking via row versioning; Redis-based idempotency key with 24h TTL.
- **Resilience & Timeouts**: Explicit 500ms connection timeout, 2000ms read timeout, exponential backoff with full jitter.
- **Data & Migration**: Phased zero-downtime migration: dual-read, backfill historical orders, cutover writes.
- **Blast Radius & Rollback**: Gated behind kill-switch feature flag `enable_order_v2`; instant fallback if error rate > 1%.

---

## 5. Consequences & Trade-offs
- **Positive Consequences**: High concurrency, horizontal scalability, decoupled downstream processing.
- **Negative Consequences / Accepted Technical Debt**: Eventual consistency requires UI optimistic updates.

---

## 6. Downstream Verification Criteria (For review)
- [ ] Concurrency stress test verifies zero double-orders under 50 concurrent requests.
- [ ] Outbox publisher retries with jitter on broker disconnection.
- [ ] Database migration runs without acquiring exclusive table lock.
"""


class TestDesignSkillValidators(unittest.TestCase):
    def test_adr_validation_happy_path(self):
        result = design.validate_adr_content(VALID_CANONICAL_ADR, "ADR-0001.md")
        self.assertTrue(result.passed, f"Expected clean pass, got errors: {[e.message for e in result.errors]}")
        self.assertEqual(len(result.errors), 0)

    def test_adr_validation_missing_status_or_title(self):
        bad_adr = "# Bad Title Without Number\n\nSome text"
        result = design.validate_adr_content(bad_adr, "ADR.md")
        self.assertFalse(result.passed)
        error_rules = [e.rule_id for e in result.errors]
        self.assertIn("DES-ADR-001", error_rules)  # Title
        self.assertIn("DES-ADR-002", error_rules)  # Status

    def test_adr_validation_missing_options_and_chosen(self):
        adr_one_option = VALID_CANONICAL_ADR.replace("### Option B: Transactional Outbox with Redis Streams Partitioning *(Chosen)*\n- **Pros**: High throughput, isolated failure domains\n- **Cons**: Requires consumer deduplication and eventual consistency", "")
        result = design.validate_adr_content(adr_one_option, "ADR-0001.md")
        self.assertFalse(result.passed)
        error_rules = [e.rule_id for e in result.errors]
        self.assertIn("DES-ADR-009", error_rules)  # Missing Option B

    def test_adr_validation_missing_verification_criteria(self):
        adr_no_criteria = VALID_CANONICAL_ADR.replace("## 6. Downstream Verification Criteria (For review)\n- [ ] Concurrency stress test verifies zero double-orders under 50 concurrent requests.\n- [ ] Outbox publisher retries with jitter on broker disconnection.\n- [ ] Database migration runs without acquiring exclusive table lock.", "")
        result = design.validate_adr_content(adr_no_criteria, "ADR-0001.md")
        self.assertFalse(result.passed)
        error_rules = [e.rule_id for e in result.errors]
        self.assertIn("DES-ADR-021", error_rules)

    def test_openspec_validation_happy_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            change_dir = Path(tmp) / "change-test"
            change_dir.mkdir()
            (change_dir / "proposal.md").write_text(
                "# Change Proposal: Auth\n\n## 1. Problem Statement\nNeed auth.\n\n## 2. Proposed Changes\nAdd auth tokens.\n\n## 3. Capabilities\nAdded auth.",
                encoding="utf-8",
            )
            specs_dir = change_dir / "specs"
            specs_dir.mkdir()
            (specs_dir / "auth.md").write_text(
                "# Specification: Auth\n\n## Requirements\nThe system SHALL authenticate JWT tokens.\n\n#### Scenario: Valid login\n- **GIVEN** active user\n- **WHEN** user submits password\n- **THEN** token is returned\n\n### Role Access Matrix\n| Role | Read | Write |\n| User | YES | NO |",
                encoding="utf-8",
            )
            (change_dir / "design.md").write_text(
                "# Technical Design\n\n## 1. Architecture Overview\nAuth service.\n\n## 2. Invariants & Critical Guarantees\nTokens expire in 1h.",
                encoding="utf-8",
            )
            (change_dir / "tasks.md").write_text(
                "# Implementation Tasks\n\n- [ ] 1.1 Implement JWT validator\n- [ ] 1.2 Add login endpoint",
                encoding="utf-8",
            )

            result = design.validate_openspec_dir(change_dir)
            self.assertTrue(result.passed, f"Expected pass, got errors: {[e.message for e in result.errors]}")
            self.assertEqual(len(result.errors), 0)

    def test_openspec_validation_missing_rfc2119_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            change_dir = Path(tmp) / "change-test"
            change_dir.mkdir()
            (change_dir / "proposal.md").write_text("# Change Proposal: Bad\n\n## 1. Problem Statement\nX\n\n## 2. Proposed Changes\nY", encoding="utf-8")
            specs_dir = change_dir / "specs"
            specs_dir.mkdir()
            (specs_dir / "spec.md").write_text("# Spec\n\nIt would be nice if the system accepts users.", encoding="utf-8")
            (change_dir / "tasks.md").write_text("- [ ] Task 1", encoding="utf-8")

            result = design.validate_openspec_dir(change_dir)
            self.assertFalse(result.passed)
            error_rules = [e.rule_id for e in result.errors]
            self.assertIn("DES-SPEC-012", error_rules)  # Missing SHALL/MUST


class TestDesignAntiCheatAndBypass(unittest.TestCase):
    def test_interview_round_valid_batch(self):
        valid_round = """### 🏛️ Round 1 — Design Frontier

❓ **Q1** - **Partition Key Strategy**: Should we partition by Tenant ID or User ID?
➡️ **Recommended Stance**: Tenant ID partitioning provides strict multi-tenant hardware isolation and zero cross-tenant tail latency noise.

❓ **Q2** - **Broker Failover SLA**: What failover window can downstream ingest tolerate?
➡️ **Recommended Stance**: 500ms failover with transactional producer buffering in local memory.
"""
        result = design.validate_interview_round(valid_round)
        self.assertTrue(result.passed)
        self.assertEqual(result.metrics["question_count"], 2)
        self.assertEqual(result.metrics["stance_count"], 2)

    def test_interview_round_vacuous_stance_rejection(self):
        evasive_round = """### 🏛️ Round 1 — Design Frontier

❓ **Q1** - **Database Selection**: Postgres or Cassandra?
➡️ **Recommended Stance**: Choose whatever you prefer based on team comfort.
"""
        result = design.validate_interview_round(evasive_round)
        self.assertFalse(result.passed)
        error_rules = [e.rule_id for e in result.errors]
        self.assertIn("DES-FNT-005", error_rules)

    def test_interview_round_missing_stance(self):
        missing_stance_round = """### 🏛️ Round 1 — Design Frontier

❓ **Q1** - **Cache Policy**: Redis vs Memcached?
"""
        result = design.validate_interview_round(missing_stance_round)
        self.assertFalse(result.passed)
        error_rules = [e.rule_id for e in result.errors]
        self.assertIn("DES-FNT-003", error_rules)

    def test_confirmation_gate_halt_enforcement(self):
        # When presenting the confirmation prompt, mutating spec files in that same turn is a violation
        turn_text = "Here is our synthesized design. Does this capture our shared architectural understanding?"
        illegal_mutations = ["docs/adr/ADR-0001-caching.md", "openspec/changes/auth/proposal.md"]
        result = design.validate_confirmation_gate(turn_text, illegal_mutations)
        self.assertFalse(result.passed)
        self.assertIn("DES-GATE-001", [e.rule_id for e in result.errors])

        # Legal: presenting prompt with zero mutations
        clean_result = design.validate_confirmation_gate(turn_text, [])
        self.assertTrue(clean_result.passed)

    def test_frontier_dag_resolution_order(self):
        dag = design.FrontierDAG()
        dag.add_decision("D1", "Message Broker")
        dag.add_decision("D2", "Partition Key", dependencies=["D1"])
        dag.add_decision("D3", "Consumer Dedup", dependencies=["D2"])

        # Initially, only D1 is unblocked
        frontier = dag.get_frontier()
        self.assertEqual(len(frontier), 1)
        self.assertEqual(frontier[0]["id"], "D1")

        # Resolve D1 -> D2 becomes unblocked
        dag.resolve("D1", "Kafka")
        frontier = dag.get_frontier()
        self.assertEqual(len(frontier), 1)
        self.assertEqual(frontier[0]["id"], "D2")

        # Resolve D2 -> D3 becomes unblocked
        dag.resolve("D2", "TenantID")
        frontier = dag.get_frontier()
        self.assertEqual(len(frontier), 1)
        self.assertEqual(frontier[0]["id"], "D3")

        # Resolve D3 -> Complete
        dag.resolve("D3", "RedisSETNX")
        self.assertTrue(dag.is_complete())
        self.assertEqual(len(dag.get_frontier()), 0)


class TestDesignFixturesAndRubric(unittest.TestCase):
    def test_fixture_01_existing_stack_presence(self):
        fixture_dir = FIXTURES_DIR / "01-existing-stack"
        self.assertTrue((fixture_dir / "package.json").is_file())
        self.assertTrue((fixture_dir / "config/redis.ts").is_file())

    def test_fixture_02_scenario_frontier_mapping(self):
        scenario_file = FIXTURES_DIR / "02-dependent-frontier-tree/scenario.json"
        self.assertTrue(scenario_file.is_file())
        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        dag = design.FrontierDAG()
        for d in data["decisions"]:
            dag.add_decision(d["id"], d["title"], d.get("dependencies", []))
        self.assertEqual([d["id"] for d in dag.get_frontier()], ["D1"])

    def test_fixture_03_empirical_claim_flags_spike_requirement(self):
        claim_file = FIXTURES_DIR / "03-empirical-boundary-claim/claim.json"
        self.assertTrue(claim_file.is_file())
        data = json.loads(claim_file.read_text(encoding="utf-8"))
        self.assertTrue(data.get("requires_spike"))

    def test_fixture_04_incomplete_capability_closure_caught_by_validator(self):
        fixture_change = FIXTURES_DIR / "04-incomplete-capability-closure/change"
        result = design.validate_openspec_dir(fixture_change)
        self.assertFalse(result.passed)
        error_rules = [e.rule_id for e in result.errors]
        self.assertIn("DES-SPEC-012", error_rules)  # Missing RFC 2119
        self.assertIn("DES-SPEC-030", error_rules)  # Missing tasks.md

    def test_l5_design_rubric_evaluation(self):
        evaluator = DesignRubricEvaluator(passing_threshold=0.80)
        report = evaluator.evaluate_text(VALID_CANONICAL_ADR, "", "TestADR")
        self.assertTrue(report.passed, f"Expected L5 pass, got score {report.overall_score:.2f} notes: {report.summary_notes}")
        self.assertGreaterEqual(report.overall_score, 0.80)
        self.assertEqual(report.status, "PASS")

        # Test shallow/poor ADR
        shallow_adr = "# ADR-0001: Just Use Mongo\n\nWe decided to use MongoDB because it is easy."
        poor_report = evaluator.evaluate_text(shallow_adr, "", "PoorADR")
        self.assertFalse(poor_report.passed)
        self.assertLess(poor_report.overall_score, 0.60)
        self.assertEqual(poor_report.status, "FAIL")

    def test_validator_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adr_dir = root / "docs" / "adr"
            adr_dir.mkdir(parents=True)
            (adr_dir / "ADR-0001-test.md").write_text(VALID_CANONICAL_ADR, encoding="utf-8")

            res1 = design.validate_repository(root)
            res2 = design.validate_repository(root)

            self.assertEqual(res1.to_dict(), res2.to_dict())
            self.assertEqual(res1.metrics, res2.metrics)
            self.assertTrue(res1.passed)


if __name__ == "__main__":
    unittest.main()
