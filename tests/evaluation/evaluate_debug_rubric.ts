import { truth, size, contains, round, rx, re, checkGrounding, isType, valueType, str, int, float, dict, list, type RubricReport } from "./rubric_support.ts";
import { validateReport } from "../../src/ship/tools/review.ts";

export class DebugRubricEvaluator {
  constructor(public passing_threshold = 0.80) {}

  evaluate_bugfix(audit_record: any, target_name: any = "BugfixAudit"): RubricReport {
    let a: any, assertions: any, causal_trace: any, cg_feedback: any, cg_pts: any, domain_scores: any, hypothesis: any, masking_violations: any, overall: any, passed: any, point_of_impact: any, prod_files: any, repro_found: any, repro_red_proven: any, repro_test: any, root_cause_origin: any, rr_feedback: any, rr_pts: any, s: any, sl_feedback: any, sl_pts: any, sm_feedback: any, sm_pts: any, status: any, summary_notes: any, tautological: any, total_prod_lines: any, tw_feedback: any, tw_pts: any, v: any, violations: any, weakening_violations: any;
    domain_scores = {};
    cg_feedback = [];
    cg_pts = 0.0;
    hypothesis = (audit_record["hypothesis"] ?? "");
    causal_trace = (audit_record["causal_trace"] ?? []);
    point_of_impact = (audit_record["point_of_impact"] ?? "");
    root_cause_origin = (audit_record["root_cause_origin"] ?? "");
    if (truth((truth(point_of_impact) && truth(root_cause_origin)))) {
      if (truth(((point_of_impact === root_cause_origin)))) {
        cg_feedback.push("Point of impact matches root cause origin. Ensure this is not a symptom patch.");
        cg_pts = 0.7;
      } else {
        cg_pts = 1.0;
      }
    } else {
      if (truth((truth(hypothesis) && truth(causal_trace)))) {
        cg_pts = 1.0;
      } else {
        if (truth((truth(hypothesis) || truth(causal_trace)))) {
          cg_pts = 0.6;
          cg_feedback.push("Causal trace or hypothesis partially documented.");
        } else {
          cg_feedback.push("No causal trace or hypothesis provided; root cause unverified.");
          cg_pts = 0.2;
        }
      }
    }
    domain_scores["causal_grounding"] = {name: "Causal Grounding", weight: 0.25, score: Math.min(1.0, cg_pts), feedback: cg_feedback};
    rr_feedback = [];
    rr_pts = 0.0;
    repro_test = (audit_record["reproduction_test"] ?? {});
    repro_found = (truth((audit_record["repro_test_found"] ?? false)) || truth(truth(repro_test)));
    repro_red_proven = (repro_test["red_proven"] ?? false);
    assertions = (repro_test["assertions"] ?? []);
    if (truth(!truth(repro_found))) {
      rr_feedback.push("Reproduction mandate violated: No reproduction test provided in diff.");
      rr_pts = 0.0;
    } else {
      if (truth(repro_red_proven)) {
        rr_pts += 0.5;
      } else {
        rr_feedback.push("Reproduction test was not explicitly proven failing (Red) before fix.");
        rr_pts += 0.2;
      }
      if (truth(assertions)) {
        tautological = assertions .filter((a: any) => truth((truth((contains(a, "True"))) || truth((contains(a, "true"))) || truth((contains(a, "1 == 1")))))).map((a: any) => a);
        if (truth(((size(tautological) === size(assertions))))) {
          rr_feedback.push("Hollow reproduction test: Only tautological assertions found.");
          rr_pts += 0.0;
        } else {
          rr_pts += 0.5;
        }
      } else {
        rr_pts += 0.3;
      }
    }
    domain_scores["reproduction_rigor"] = {name: "Reproduction Rigor", weight: 0.25, score: Math.min(1.0, rr_pts), feedback: rr_feedback};
    sl_feedback = [];
    sl_pts = 0.0;
    prod_files = (audit_record["prod_files_modified"] ?? []);
    total_prod_lines = (audit_record["total_prod_lines_added"] ?? 0);
    if (truth(((size(prod_files) === 0)))) {
      sl_feedback.push("No production files modified.");
      sl_pts = 0.5;
    } else {
      if (truth((truth(((size(prod_files) <= 2))) && truth(((total_prod_lines <= 30)))))) {
        sl_pts = 1.0;
      } else {
        if (truth((truth(((size(prod_files) <= 4))) && truth(((total_prod_lines <= 80)))))) {
          sl_pts = 0.8;
          sl_feedback.push("Diff is moderately sized. Ensure no extraneous refactoring.");
        } else {
          if (truth((truth(((size(prod_files) <= 5))) && truth(((total_prod_lines <= 150)))))) {
            sl_pts = 0.6;
            sl_feedback.push("Diff approaches non-surgical boundary.");
          } else {
            sl_feedback.push(("Excessive diff scope: " + String(size(prod_files)) + " files, " + String(total_prod_lines) + " lines added. Violates laziness ladder."));
            sl_pts = 0.2;
          }
        }
      }
    }
    domain_scores["surgical_laziness"] = {name: "Surgical Laziness", weight: 0.2, score: Math.min(1.0, sl_pts), feedback: sl_feedback};
    tw_feedback = [];
    tw_pts = 1.0;
    violations = (audit_record["violations"] ?? []);
    weakening_violations = violations .filter((v: any) => truth((truth((contains(v, "Test Weakening"))) || truth((contains(v, "Assertion Degradation")))))).map((v: any) => v);
    if (truth(weakening_violations)) {
      tw_pts = 0.0;
      tw_feedback.push(...weakening_violations);
    }
    domain_scores["zero_test_weakening"] = {name: "Zero Test Weakening", weight: 0.15, score: tw_pts, feedback: tw_feedback};
    sm_feedback = [];
    sm_pts = 1.0;
    masking_violations = violations .filter((v: any) => truth((truth((contains(v, "Symptom Masking"))) || truth((contains(v, "Hollow Repro")))))).map((v: any) => v);
    if (truth(masking_violations)) {
      sm_pts = 0.0;
      sm_feedback.push(...masking_violations);
    }
    domain_scores["zero_symptom_masking"] = {name: "Zero Symptom Masking", weight: 0.15, score: sm_pts, feedback: sm_feedback};
    overall = Object.values(domain_scores).map((s: any) => (s.score * s.weight)).reduce((a: number, b: number) => a + b, 0);
    passed = (truth(((overall >= this.passing_threshold))) && truth(Object.values(domain_scores).map((s: any) => ((s.score >= 0.5))).every(truth)));
    status = (truth(passed) ? "PASS" : (truth(((overall >= 0.65))) ? "CONDITIONAL" : "FAIL"));
    summary_notes = [];
    for (const s of Object.values(domain_scores)) {
      if (truth(((s.score < 0.7)))) {
        summary_notes.push(((String(s.name) + " scored low (" + String(Number(s.score).toFixed(2)) + "): ") + s.feedback.join("; ")));
      }
    }
    return {domain_scores: domain_scores, summary_notes: summary_notes, target_name: target_name, overall_score: overall, passed: passed, status: status};
  }
}
