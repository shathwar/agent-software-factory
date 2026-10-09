import { truth, size, contains, round, rx, re, checkGrounding, isType, valueType, str, int, float, dict, list, type RubricReport } from "./rubric_support.ts";
import { validateReport } from "../../src/ship/tools/review.ts";

export class DesignRubricEvaluator {
  constructor(public passing_threshold = 0.80) {}

  evaluate_text(adr_text: any, spec_text: any = "", target_name: any = "Design"): RubricReport {
    let blast_feedback: any, blast_pts: any, closure_feedback: any, closure_pts: any, combined: any, conc_feedback: any, conc_pts: any, data_feedback: any, data_pts: any, domain_scores: any, ds: any, fail_feedback: any, fail_pts: any, notes: any, overall_score: any, passed: any, state_feedback: any, state_pts: any, status: any, total_weight: any;
    combined = (String(adr_text) + "\n\n" + String(spec_text)).toLowerCase();
    domain_scores = {};
    state_feedback = [];
    state_pts = 0.0;
    if (truth(rx.search("single source of truth|source of truth", combined))) {
      state_pts += 0.35;
    } else {
      state_feedback.push("Missing explicit declaration of single source of truth.");
    }
    if (truth(rx.search("acid|transaction|atomic|eventual consist", combined))) {
      state_pts += 0.35;
    } else {
      state_feedback.push("Missing explicit consistency model (ACID vs eventual consistency).");
    }
    if (truth(rx.search("invariant|never break|guarantee", combined))) {
      state_pts += 0.3;
    } else {
      state_feedback.push("Missing explicit system invariant statements.");
    }
    domain_scores["state_invariants"] = {name: "State & Invariants", weight: 0.2, score: Math.min(1.0, state_pts), feedback: state_feedback};
    conc_feedback = [];
    conc_pts = 0.0;
    if (truth(rx.search("optimistic|pessimistic|lock|mutex|distributed lock", combined))) {
      conc_pts += 0.35;
    } else {
      conc_feedback.push("No locking strategy or concurrency control mechanism specified.");
    }
    if (truth(rx.search("idempotenc|dedup|deduplication|unique key|idempotent", combined))) {
      conc_pts += 0.35;
    } else {
      conc_feedback.push("No idempotency key or deduplication mechanism documented.");
    }
    if (truth(rx.search("race|toctou|re-entran|contention", combined))) {
      conc_pts += 0.3;
    } else {
      conc_feedback.push("No explicit analysis of race conditions or contention windows.");
    }
    domain_scores["concurrency"] = {name: "Concurrency & Contention", weight: 0.2, score: Math.min(1.0, conc_pts), feedback: conc_feedback};
    fail_feedback = [];
    fail_pts = 0.0;
    if (truth(rx.search("\\b\\d+ms\\b|\\btimeout\\b", combined))) {
      fail_pts += 0.35;
    } else {
      fail_feedback.push("Missing explicit numeric connection or read timeouts.");
    }
    if (truth(rx.search("backoff|jitter|retry", combined))) {
      fail_pts += 0.35;
    } else {
      fail_feedback.push("Missing exponential backoff with jitter retry strategy.");
    }
    if (truth(rx.search("circuit breaker|fallback|graceful degradation|dead letter", combined))) {
      fail_pts += 0.3;
    } else {
      fail_feedback.push("Missing circuit breaker, fallback, or dead-letter containment.");
    }
    domain_scores["failure_domains"] = {name: "Failure Domains & Chaos", weight: 0.2, score: Math.min(1.0, fail_pts), feedback: fail_feedback};
    data_feedback = [];
    data_pts = 0.0;
    if (truth(rx.search("migration|dual-write|dual-read|zero-downtime", combined))) {
      data_pts += 0.4;
    } else {
      data_feedback.push("Missing zero-downtime migration or phased rollout strategy.");
    }
    if (truth(rx.search("index|composite index|foreign key|query plan", combined))) {
      data_pts += 0.35;
    } else {
      data_feedback.push("Missing database index or query access pattern analysis.");
    }
    if (truth(rx.search("backward compat|backfill|schema evolv", combined))) {
      data_pts += 0.25;
    } else {
      data_feedback.push("Missing backward compatibility or historical backfill plan.");
    }
    domain_scores["data_evolution"] = {name: "Data Evolution & Schema", weight: 0.15, score: Math.min(1.0, data_pts), feedback: data_feedback};
    blast_feedback = [];
    blast_pts = 0.0;
    if (truth(rx.search("feature flag|kill-switch|kill switch|canary", combined))) {
      blast_pts += 0.4;
    } else {
      blast_feedback.push("Missing feature flag or immediate operational kill-switch.");
    }
    if (truth(rx.search("sli|slo|metric|alert|error rate|monitoring", combined))) {
      blast_pts += 0.35;
    } else {
      blast_feedback.push("Missing SLI metrics or monitoring alerts for silent failures.");
    }
    if (truth(rx.search("rollback|blast radius|containment", combined))) {
      blast_pts += 0.25;
    } else {
      blast_feedback.push("Missing rollback plan or blast radius containment.");
    }
    domain_scores["blast_radius"] = {name: "Operational Blast Radius", weight: 0.15, score: Math.min(1.0, blast_pts), feedback: blast_feedback};
    closure_feedback = [];
    closure_pts = 0.0;
    if (truth(rx.search("delete|destroy|archive|tombstone|retention", combined))) {
      closure_pts += 0.35;
    } else {
      closure_feedback.push("Capability Closure: Entity deletion, archival, or retention lifecycle unaddressed.");
    }
    if (truth(rx.search("role|rbac|permission|admin|guest|access control", combined))) {
      closure_pts += 0.35;
    } else {
      closure_feedback.push("Capability Closure: Role access matrix or permission boundaries unaddressed.");
    }
    if (truth(rx.search("non-goal|out of scope|excluded", combined))) {
      closure_pts += 0.3;
    } else {
      closure_feedback.push("Capability Closure: Non-goals and out-of-scope boundaries unaddressed.");
    }
    domain_scores["capability_closure"] = {name: "Capability Closure", weight: 0.1, score: Math.min(1.0, closure_pts), feedback: closure_feedback};
    total_weight = Object.values(domain_scores).map((ds: any) => ds.weight).reduce((a: number, b: number) => a + b, 0);
    overall_score = (Object.values(domain_scores).map((ds: any) => (ds.score * ds.weight)).reduce((a: number, b: number) => a + b, 0) / total_weight);
    passed = false;
    if (truth(((overall_score >= this.passing_threshold)))) {
      status = "INCONCLUSIVE";
    } else {
      if (truth(((overall_score >= 0.6)))) {
        status = "CONDITIONAL";
      } else {
        status = "FAIL";
      }
    }
    notes = [];
    if (truth(((status === "INCONCLUSIVE")))) {
      notes.push("Topic coverage meets the lint threshold; architectural correctness and capability closure are unverified.");
    } else {
      notes.push(("Design score (" + String(Number(overall_score).toFixed(2)) + ") falls below required threshold (" + String(Number(this.passing_threshold).toFixed(2)) + ")."));
      for (const ds of Object.values(domain_scores)) {
        if (truth(((ds.score < 0.7)))) {
          notes.push(("Deficiency in " + String(ds.name) + ": " + String(ds.feedback.join("; "))));
        }
      }
    }
    return {domain_scores: domain_scores, summary_notes: notes, target_name: target_name, overall_score: overall_score, passed: passed, status: status};
  }
}
