import { truth, size, contains, round, rx, re, checkGrounding, isType, valueType, str, int, float, dict, list, type RubricReport } from "./rubric_support.ts";
import { validateReport } from "../../src/ship/tools/review.ts";

export class SpikeRubricEvaluator {
  constructor(public passing_threshold = 0.80) {}

  evaluate_report(report_text: any, target_name: any = "SpikeReport"): RubricReport {
    let bridge_feedback: any, bridge_pts: any, domain_scores: any, ds: any, fals_feedback: any, fals_pts: any, has_breached: any, iso_feedback: any, iso_pts: any, notes: any, overall_score: any, passed: any, stat_feedback: any, stat_pts: any, status: any, total_weight: any, verd_feedback: any, verd_pts: any, verdict_token: any, verdict_val: any;
    domain_scores = {};
    fals_feedback = [];
    fals_pts = 0.0;
    if (truth(rx.search("-\\s+\\*\\*Hypothesis\\*\\*:\\s*.+(?:<|>|<=|>=|\\b\\d+(?:\\.\\d+)?\\s*(?:ms|rps|tps|qps|%))", report_text, re.IGNORECASE))) {
      fals_pts += 0.5;
    } else {
      fals_feedback.push("Hypothesis lacks explicit numeric inequality or unit threshold.");
    }
    if (truth(rx.search("p99|p95|percentile|latency", report_text, re.IGNORECASE))) {
      fals_pts += 0.25;
    } else {
      fals_feedback.push("No latency percentile SLI specified.");
    }
    if (truth(rx.search("throughput|rps|tps|qps|error rate|concurren", report_text, re.IGNORECASE))) {
      fals_pts += 0.25;
    } else {
      fals_feedback.push("No throughput or error rate SLI specified.");
    }
    domain_scores["falsifiability"] = {name: "Falsifiability & SLIs", weight: 0.25, score: Math.min(1.0, fals_pts), feedback: fals_feedback};
    stat_feedback = [];
    stat_pts = 0.0;
    if (truth((truth(rx.search("p50|median", report_text, re.IGNORECASE)) && truth(rx.search("p99", report_text, re.IGNORECASE))))) {
      stat_pts += 0.4;
    } else {
      stat_feedback.push("Missing comprehensive percentile spectrum (p50 and p99).");
    }
    if (truth(rx.search("\\b(?:warmup|concurrency|iterations|runs)\\b", report_text, re.IGNORECASE))) {
      stat_pts += 0.35;
    } else {
      stat_feedback.push("Harness does not document warmup or iteration methodology.");
    }
    if (truth(rx.search("error rate|status", report_text, re.IGNORECASE))) {
      stat_pts += 0.25;
    } else {
      stat_feedback.push("Reliability or error rate metrics absent.");
    }
    domain_scores["statistical_rigor"] = {name: "Statistical Rigor", weight: 0.25, score: Math.min(1.0, stat_pts), feedback: stat_feedback};
    iso_feedback = [];
    iso_pts = 0.0;
    if (truth(rx.search("\\.scratch/|scratch/", report_text))) {
      iso_pts += 0.6;
    } else {
      iso_feedback.push("No scratch sandbox directory documented.");
    }
    if (truth(rx.search("docker|container|ephemeral|isolated|mock", report_text, re.IGNORECASE))) {
      iso_pts += 0.4;
    } else {
      iso_feedback.push("No isolation harness (ephemeral container, mock) described.");
    }
    domain_scores["isolation"] = {name: "Sandbox Isolation", weight: 0.15, score: Math.min(1.0, iso_pts), feedback: iso_feedback};
    verd_feedback = [];
    verd_pts = 0.0;
    verdict_token = rx.search("-\\s+\\*\\*Verdict\\*\\*:\\s*\\*{0,2}(CONFIRMED|REFUTED|QUALIFIED)\\*{0,2}", report_text, re.IGNORECASE);
    has_breached = truth(rx.search("❌\\s*Breached", report_text));
    if (truth(verdict_token)) {
      verdict_val = verdict_token[1].toUpperCase();
      if (truth((truth(((verdict_val === "CONFIRMED"))) && truth(has_breached)))) {
        verd_pts = 0.0;
        verd_feedback.push("CRITICAL: Verdict claimed CONFIRMED despite breached empirical metrics.");
      } else {
        if (truth((truth((contains(["REFUTED", "QUALIFIED"], verdict_val))) && truth(has_breached)))) {
          verd_pts = 1.0;
        } else {
          if (truth((truth(((verdict_val === "CONFIRMED"))) && truth(!truth(has_breached))))) {
            verd_pts = 1.0;
          } else {
            verd_pts = 0.7;
          }
        }
      }
    } else {
      verd_feedback.push("Missing explicit CONFIRMED / REFUTED / QUALIFIED verdict.");
    }
    domain_scores["verdict_coherence"] = {name: "Verdict Coherence", weight: 0.2, score: Math.min(1.0, verd_pts), feedback: verd_feedback};
    bridge_feedback = [];
    bridge_pts = 0.0;
    if (truth(rx.search("recommendation|adr|frontier|design", report_text, re.IGNORECASE))) {
      bridge_pts += 0.5;
    } else {
      bridge_feedback.push("No architectural recommendation or frontier impact stated.");
    }
    if (truth(rx.search("```", report_text))) {
      bridge_pts += 0.5;
    } else {
      bridge_feedback.push("No reusable verified configuration code snippet extracted.");
    }
    domain_scores["adr_bridge"] = {name: "ADR & Spec Bridge", weight: 0.15, score: Math.min(1.0, bridge_pts), feedback: bridge_feedback};
    total_weight = Object.values(domain_scores).map((ds: any) => ds.weight).reduce((a: number, b: number) => a + b, 0);
    overall_score = (Object.values(domain_scores).map((ds: any) => (ds.score * ds.weight)).reduce((a: number, b: number) => a + b, 0) / total_weight);
    passed = ((overall_score >= this.passing_threshold));
    status = (truth(passed) ? "PASS" : (truth(((overall_score >= 0.6))) ? "CONDITIONAL" : "FAIL"));
    notes = [];
    if (truth(passed)) {
      notes.push("Spike demonstrates empirical rigor, falsifiable SLIs, and actionable architectural guidance.");
    } else {
      notes.push(("Spike score (" + String(Number(overall_score).toFixed(2)) + ") falls below required threshold (" + String(Number(this.passing_threshold).toFixed(2)) + ")."));
      for (const ds of Object.values(domain_scores)) {
        if (truth(((ds.score < 0.7)))) {
          notes.push(("Deficiency in " + String(ds.name) + ": " + String(ds.feedback.join("; "))));
        }
      }
    }
    return {domain_scores: domain_scores, summary_notes: notes, target_name: target_name, overall_score: overall_score, passed: passed, status: status};
  }
}
