import { truth, size, contains, round, rx, re, checkGrounding, isType, valueType, str, int, float, dict, list, type RubricReport } from "./rubric_support.ts";
import { validateReport } from "../../src/ship/tools/review.ts";

export class ReviewRubricEvaluator {
  constructor(public passing_threshold = 0.80) {}
  MATERIAL_CATEGORIES = ["Correctness", "Concurrency", "Failure/Resilience", "Performance", "ProductionRisk", "SpecAlignment"];
  evaluate_report(report_dict: any, target_name: any = "ReviewReport", repo_root: any = null): RubricReport {
    let act_feedback: any, act_pts: any, actionable_count: any, adj_feedback: any, adj_pts: any, bikeshed_count: any, cal_feedback: any, cal_pts: any, cat: any, critical_count: any, dim: any, domain_scores: any, errors: any, f: any, findings: any, grounded_count: any, has_evidence: any, has_file: any, has_line: any, high_count: any, is_clean_review: any, mat_feedback: any, mat_pts: any, material_count: any, notes: any, overall: any, passed: any, rec: any, sev: any, src_feedback: any, src_pts: any, status: any, status_str: any, title: any, valid_schema: any;
    errors = validateReport(report_dict, false, undefined);
    if (truth(errors)) {
      return {domain_scores: {}, summary_notes: errors, target_name: target_name, overall_score: 0.0, passed: false, status: "FAIL"};
    }
    if (truth((truth(((report_dict["status"] !== "complete"))) || truth(!truth(report_dict["coverage"]))))) {
      return {domain_scores: {}, summary_notes: ["Incomplete or absent review coverage."], target_name: target_name, overall_score: 0.0, passed: false, status: "FAIL"};
    }
    errors = checkGrounding(report_dict, repo_root);
    if (truth(errors)) {
      return {domain_scores: {}, summary_notes: errors, target_name: target_name, overall_score: 0.0, passed: false, status: "FAIL"};
    }
    domain_scores = {};
    findings = (report_dict["findings"] ?? []);
    is_clean_review = ((size(findings) === 0));
    mat_feedback = [];
    mat_pts = 0.0;
    if (truth(is_clean_review)) {
      mat_pts = 1.0;
    } else {
      material_count = 0;
      bikeshed_count = 0;
      for (const f of findings) {
        cat = (f["category"] ?? "");
        sev = (f["severity"] ?? "");
        title = (((f["title"] ?? "") + " ") + (f["problem"] ?? "")).toLowerCase();
        if (truth(rx.search("\\b(naming|whitespace|prettier|formatting|camelcase|snake_case)\\b", title))) {
          bikeshed_count += 1;
          if (truth((contains(["CRITICAL", "HIGH"], sev)))) {
            mat_feedback.push(("Finding " + String((f["id"] ?? null)) + ": Cosmetic issue classified with elevated severity (" + String(sev) + ")."));
          }
        } else {
          if (truth((contains(this.MATERIAL_CATEGORIES, cat)))) {
            material_count += 1;
          }
        }
      }
      if (truth(((size(findings) > 0)))) {
        mat_pts = Math.max(0.0, ((material_count - (bikeshed_count * 0.5)) / size(findings)));
      } else {
        mat_pts = 1.0;
      }
      if (truth(((bikeshed_count > 0)))) {
        mat_feedback.push(("Detected " + String(bikeshed_count) + " cosmetic/bikeshedding finding(s). Focus on material correctness."));
      }
    }
    domain_scores["materiality"] = {name: "Materiality", weight: 0.25, score: Math.min(1.0, Math.max(0.0, mat_pts)), feedback: mat_feedback};
    src_feedback = [];
    src_pts = 0.0;
    if (truth(is_clean_review)) {
      src_pts = 1.0;
    } else {
      grounded_count = 0;
      for (const f of findings) {
        has_file = truth((truth((f["file"] ?? null)) && truth(!truth((f["file"] ?? "").startsWith("/")))));
        has_line = truth(rx.match("^L\\d+(-L\\d+)?$", (f["line"] ?? "")));
        has_evidence = truth((truth((f["evidence"] ?? null)) && truth(((size((f["evidence"] ?? "").trim()) >= 5)))));
        if (truth((truth(has_file) && truth(has_line) && truth(has_evidence)))) {
          grounded_count += 1;
        } else {
          src_feedback.push(("Finding " + String((f["id"] ?? null)) + ": Incomplete source grounding (file, line range, or verbatim code)."));
        }
      }
      src_pts = (truth(findings) ? (grounded_count / size(findings)) : 1.0);
    }
    domain_scores["source_grounding"] = {name: "Source Grounding", weight: 0.25, score: Math.min(1.0, src_pts), feedback: src_feedback};
    act_feedback = [];
    act_pts = 0.0;
    if (truth(is_clean_review)) {
      act_pts = 1.0;
    } else {
      actionable_count = 0;
      for (const f of findings) {
        rec = (f["recommendation"] ?? "");
        if (truth((truth(((size(rec.trim()) >= 15))) && truth(!truth(rec.toLowerCase().startsWith(["consider", "maybe", "look into"])))))) {
          actionable_count += 1;
        } else {
          act_feedback.push(("Finding " + String((f["id"] ?? null)) + ": Vague or speculative recommendation. Provide drop-in fix."));
        }
      }
      act_pts = (truth(findings) ? (actionable_count / size(findings)) : 1.0);
    }
    domain_scores["actionability"] = {name: "Actionability", weight: 0.2, score: Math.min(1.0, act_pts), feedback: act_feedback};
    cal_feedback = [];
    cal_pts = 0.0;
    critical_count = findings .filter((f: any) => truth((((f["severity"] ?? null) === "CRITICAL")))).map((f: any) => 1).reduce((a: number, b: number) => a + b, 0);
    high_count = findings .filter((f: any) => truth((((f["severity"] ?? null) === "HIGH")))).map((f: any) => 1).reduce((a: number, b: number) => a + b, 0);
    status = (report_dict["status"] ?? "");
    if (truth(is_clean_review)) {
      if (truth((contains(["complete", "READY TO DEPLOY", "APPROVE"], status)))) {
        cal_pts = 1.0;
      } else {
        cal_pts = 0.5;
        cal_feedback.push(("Clean review marked with status '" + String(status) + "'. Expected complete/clean pass."));
      }
    } else {
      if (truth(((critical_count > 0)))) {
        cal_pts = 1.0;
      } else {
        if (truth(((high_count > 0)))) {
          cal_pts = 1.0;
        } else {
          cal_pts = 0.85;
        }
      }
    }
    domain_scores["verdict_calibration"] = {name: "Verdict Calibration", weight: 0.15, score: Math.min(1.0, cal_pts), feedback: cal_feedback};
    adj_feedback = [];
    adj_pts = 0.0;
    valid_schema = true;
    for (const f of findings) {
      if (truth(!truth(((0.0 <= (f["confidence"] ?? -1.0)) && ((f["confidence"] ?? -1.0) <= 1.0))))) {
        valid_schema = false;
        adj_feedback.push(("Finding " + String((f["id"] ?? null)) + ": Invalid confidence score."));
      }
      if (truth((!contains(["autonomous", "requires-human"], (f["fixability"] ?? null))))) {
        valid_schema = false;
        adj_feedback.push(("Finding " + String((f["id"] ?? null)) + ": Invalid fixability enum."));
      }
    }
    if (truth(valid_schema)) {
      adj_pts = 1.0;
    } else {
      adj_pts = 0.4;
    }
    domain_scores["adjudication_integrity"] = {name: "Adjudication Integrity", weight: 0.15, score: Math.min(1.0, adj_pts), feedback: adj_feedback};
    overall = Object.values(domain_scores).map((dim: any) => (dim.score * dim.weight)).reduce((a: number, b: number) => a + b, 0);
    passed = (truth(((overall >= this.passing_threshold))) && truth(((adj_pts >= 0.8))) && truth(((repo_root !== null))));
    if (truth(passed)) {
      status_str = "PASS";
    } else {
      if (truth((truth(((repo_root === null))) && truth(((overall >= this.passing_threshold)))))) {
        status_str = "INCONCLUSIVE";
      } else {
        if (truth(((overall >= 0.6)))) {
          status_str = "CONDITIONAL";
        } else {
          status_str = "FAIL";
        }
      }
    }
    notes = [];
    if (truth(is_clean_review)) {
      notes.push("No findings reported; defect absence and coverage completeness are not verified.");
    } else {
      notes.push(("Reported " + String(size(findings)) + " finding(s): " + String(critical_count) + " CRITICAL, " + String(high_count) + " HIGH."));
    }
    notes.push("Artifact lint only; semantic correctness and defect recall require independent adjudication.");
    if (truth(((repo_root === null)))) {
      notes.push("Source files were not supplied; grounding is unverified.");
    }
    return {domain_scores: domain_scores, summary_notes: notes, target_name: target_name, overall_score: overall, passed: passed, status: status_str};
  }
}
