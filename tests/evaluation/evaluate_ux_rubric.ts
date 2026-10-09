import { truth, size, contains, round, rx, re, checkGrounding, isType, valueType, str, int, float, dict, list, type RubricReport } from "./rubric_support.ts";
import { validateReport } from "../../src/ship/tools/review.ts";

export class UXRubricEvaluator {
  constructor(public passing_threshold = 0.80) {}

  evaluate_component(component_spec: any, target_name: any = "UXComponent"): RubricReport {
    let a11y: any, arbitrary_count: any, as_feedback: any, as_pts: any, defined_states: any, destructive: any, domain_scores: any, err_state: any, error_violations: any, escape_paths: any, ev: any, fg_feedback: any, fg_pts: any, flow: any, jtbd: any, k: any, missing_states: any, overall: any, passed: any, penalty: any, required_states: any, s: any, slop: any, sm_feedback: any, sm_pts: any, states: any, status: any, summary_notes: any, token_reuse: any, tokens: any, undo_or_cancel: any, v: any, violations: any, vr_feedback: any, vr_pts: any, w: any, wcag_feedback: any, wcag_pts: any;
    domain_scores = {};
    fg_feedback = [];
    fg_pts = 0.0;
    flow = (component_spec["flow"] ?? {});
    jtbd = (truth((flow["jtbd"] ?? "")) || truth((component_spec["jtbd"] ?? "")));
    escape_paths = (truth((flow["escape_paths"] ?? [])) || truth((component_spec["escape_paths"] ?? [])));
    undo_or_cancel = (truth((flow["cancellation_or_undo"] ?? false)) || truth(truth(escape_paths)));
    if (truth(jtbd)) {
      fg_pts += 0.5;
    } else {
      fg_feedback.push("Missing primary Job-to-be-Done (JTBD) definition.");
    }
    if (truth(undo_or_cancel)) {
      fg_pts += 0.5;
    } else {
      fg_feedback.push("Missing secondary escape paths, cancellation, or undo mechanics.");
    }
    domain_scores["flow_architecture"] = {name: "Flow Grilling & Architecture", weight: 0.15, score: Math.min(1.0, fg_pts), feedback: fg_feedback};
    sm_feedback = [];
    sm_pts = 0.0;
    states = (component_spec["states"] ?? {});
    required_states = ["empty", "loading", "populated", "error"];
    defined_states = new Set(Object.entries(states) .filter(([k, v]: any) => truth(v)).map(([k, v]: any) => k.toLowerCase()));
    missing_states = required_states.filter((state: string) => !defined_states.has(state));
    if (truth(!truth(missing_states))) {
      sm_pts += 0.7;
      err_state = (states["error"] ?? {});
      if (truth((truth(isType(err_state, dict)) && truth((truth((err_state["recovery_action"] ?? null)) || truth((err_state["actionable"] ?? null))))))) {
        sm_pts += 0.3;
      } else {
        if (truth((truth(isType(err_state, str)) && truth(["retry", "reload", "help", "contact"].map((w: any) => (contains(err_state.toLowerCase(), w))).some(truth))))) {
          sm_pts += 0.3;
        } else {
          sm_feedback.push("Error state lacks actionable recovery CTA (Retry, Reload, Contact).");
        }
      }
    } else {
      sm_pts += Math.max(0.2, (size(defined_states) / 6.0));
      sm_feedback.push(("Missing core states from 6-State Matrix: " + String(Array.from(missing_states).sort()) + "."));
    }
    domain_scores["state_matrix"] = {name: "State Matrix Completeness", weight: 0.25, score: Math.min(1.0, sm_pts), feedback: sm_feedback};
    wcag_feedback = [];
    wcag_pts = 1.0;
    a11y = (component_spec["accessibility"] ?? {});
    violations = (component_spec["audit_violations"] ?? []);
    error_violations = violations .filter((v: any) => truth((contains(["CRITICAL", "ERROR"], (v["severity"] ?? null))))).map((v: any) => v);
    if (truth(error_violations)) {
      penalty = (size(error_violations) * 0.25);
      wcag_pts = Math.max(0.1, (1.0 - penalty));
      for (const ev of error_violations.slice(0, 3)) {
        wcag_feedback.push(("[" + String((ev["rule_id"] ?? "A11Y")) + "] " + String((ev["message"] ?? ""))));
      }
    } else {
      if (truth((truth(!truth((a11y["keyboard_navigable"] ?? true))) || truth(!truth((a11y["focus_indicators_visible"] ?? true)))))) {
        wcag_pts = 0.5;
        wcag_feedback.push("Keyboard navigation or focus indicators not verified.");
      }
    }
    domain_scores["wcag_accessibility"] = {name: "WCAG Accessibility Compliance", weight: 0.25, score: wcag_pts, feedback: wcag_feedback};
    vr_feedback = [];
    vr_pts = 0.0;
    tokens = (component_spec["design_system"] ?? {});
    token_reuse = (tokens["tokens_reused"] ?? true);
    arbitrary_count = (tokens["arbitrary_values_count"] ?? 0);
    if (truth((truth(token_reuse) && truth(((arbitrary_count === 0)))))) {
      vr_pts = 1.0;
    } else {
      if (truth((truth(token_reuse) && truth(((arbitrary_count <= 2)))))) {
        vr_pts = 0.8;
        vr_feedback.push((String(arbitrary_count) + " arbitrary values detected; justify or replace with semantic tokens."));
      } else {
        vr_pts = 0.4;
        vr_feedback.push(("Design token hierarchy ignored; " + String(arbitrary_count) + " arbitrary values found."));
      }
    }
    domain_scores["visual_refinement"] = {name: "Visual Refinement (Impeccable)", weight: 0.15, score: vr_pts, feedback: vr_feedback};
    as_feedback = [];
    as_pts = 1.0;
    slop = (component_spec["slop_patterns"] ?? []);
    destructive = (component_spec["destructive_actions"] ?? {});
    if (truth(slop)) {
      penalty = (size(slop) * 0.25);
      as_pts = Math.max(0.2, (1.0 - penalty));
      as_feedback.push(("Generic AI-slop layout patterns detected: " + String(slop.join(", ")) + "."));
    }
    if (truth((truth((destructive["present"] ?? false)) && truth(!truth((destructive["confirmed"] ?? false)))))) {
      as_pts = Math.min(as_pts, 0.5);
      as_feedback.push("Destructive action lacks confirmation dialog or undo mechanic.");
    }
    domain_scores["anti_slop_structural"] = {name: "Anti-Slop Structural Integrity", weight: 0.2, score: as_pts, feedback: as_feedback};
    overall = Object.values(domain_scores).map((s: any) => (s.score * s.weight)).reduce((a: number, b: number) => a + b, 0);
    overall = round(overall, 12);
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
