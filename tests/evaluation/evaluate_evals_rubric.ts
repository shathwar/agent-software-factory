import { truth, size, contains, round, rx, re, checkGrounding, isType, valueType, str, int, float, dict, list, type RubricReport } from "./rubric_support.ts";
import { validateReport } from "../../src/ship/tools/review.ts";

export class EvalsRubricEvaluator {
  constructor(public passing_threshold = 0.80) {}

  evaluate_eval_suite(eval_spec: any, target_name: any = "EvalsSuite"): RubricReport {
    let accuracy_only: any, bjp_feedback: any, bjp_pts: any, calib: any, cfp_feedback: any, cfp_pts: any, ci: any, claimed: any, code_evaluators: any, corrected: any, domain_scores: any, e: any, evaluators: any, expected: any, flawed_judges: any, ids: any, j: any, k: any, leakage: any, llm_evaluators: any, misrouted: any, model: any, obs: any, overall: any, partitions: any, passed: any, penalty: any, prod: any, prompt: any, prompt_lower: any, rate: any, ratio: any, rg_feedback: any, rg_pts: any, s: any, sir_feedback: any, sir_pts: any, split: any, stat_feedback: any, stat_pts: any, status: any, summary_notes: any, task: any, term: any, test_ids: any, tnr: any, tpr: any, train_ids: any, valid: any, valid_ids: any, x: any;
    if (truth(!truth(isType(eval_spec, dict)))) {
      return {domain_scores: {}, summary_notes: ["Expected an evaluation spec object."], target_name: target_name, overall_score: 0.0, passed: false, status: "FAIL"};
    }
    evaluators = (eval_spec["evaluators"] ?? []);
    if (truth((truth(!truth(isType(evaluators, list))) || truth(evaluators.map((e: any) => (truth(!truth(isType(e, dict))) || truth(["type", "name", "description", "prompt", "rubric", "model"].map((k: any) => !truth(isType((e[k] ?? ""), str))).some(truth)))).some(truth)) || truth(["splits", "calibration", "production_monitoring"].map((k: any) => !truth(isType((eval_spec[k] ?? {}), dict))).some(truth))))) {
      return {domain_scores: {}, summary_notes: ["Malformed evaluators or evidence sections."], target_name: target_name, overall_score: 0.0, passed: false, status: "FAIL"};
    }
    domain_scores = {};
    cfp_feedback = [];
    cfp_pts = 0.0;
    evaluators = (eval_spec["evaluators"] ?? []);
    code_evaluators = evaluators .filter((e: any) => truth((contains(["code", "deterministic", "assertion", "regex", "schema"], (e["type"] ?? null))))).map((e: any) => e);
    llm_evaluators = evaluators .filter((e: any) => truth((contains(["llm_judge", "model", "prompt"], (e["type"] ?? null))))).map((e: any) => e);
    misrouted = [];
    for (const e of llm_evaluators) {
      task = (((e["name"] ?? "") + " ") + (e["description"] ?? "")).toLowerCase();
      if (truth(["json valid", "schema valid", "status code", "regex", "exact match", "latency", "token count"].map((term: any) => (contains(task, term))).some(truth))) {
        misrouted.push((e["name"] ?? "unnamed"));
      }
    }
    if (truth(misrouted)) {
      cfp_feedback.push(("Objective assertion misrouted to LLM judge: " + String(misrouted) + ". Must use code assertions."));
      cfp_pts += 0.2;
    } else {
      if (truth((truth(code_evaluators) || truth(llm_evaluators)))) {
        ratio = (size(code_evaluators) / Math.max(1, size(evaluators)));
        if (truth(((ratio >= 0.3)))) {
          cfp_pts += 1.0;
        } else {
          cfp_pts += 0.7;
          cfp_feedback.push(("Code-first ratio (" + String((Number(ratio) * 100).toFixed(1) + "%") + ") is low; ensure objective checks are asserted in code."));
        }
      } else {
        cfp_feedback.push("No evaluators defined.");
      }
    }
    domain_scores["code_first_priority"] = {name: "Code-First Priority", weight: 0.2, score: Math.min(1.0, cfp_pts), feedback: cfp_feedback};
    bjp_feedback = [];
    bjp_pts = 0.0;
    if (truth(!truth(llm_evaluators))) {
      bjp_pts = 1.0;
    } else {
      flawed_judges = 0;
      for (const j of llm_evaluators) {
        prompt = (((j["prompt"] ?? "") + " ") + (j["rubric"] ?? ""));
        prompt_lower = prompt.toLowerCase();
        if (truth(rx.search("\\b(1\\s*[-–]\\s*5|1\\s*[-–]\\s*10|scale of 1|likert|rate 1-5)\\b", prompt_lower))) {
          bjp_feedback.push(("Judge '" + String((j["name"] ?? null)) + "' uses a Likert/multi-point scale. Must be binary Pass/Fail."));
          flawed_judges += 1;
        }
        if (truth(!truth(["critique", "reasoning", "thought", "chain of thought", "justification"].map((k: any) => (contains(prompt_lower, k))).some(truth)))) {
          bjp_feedback.push(("Judge '" + String((j["name"] ?? null)) + "' missing critique-before-result requirement."));
          flawed_judges += 1;
        }
        model = (j["model"] ?? "");
        if (truth(!truth(rx.search("(?:\\d{4}-\\d{2}-\\d{2}|\\d{8})$", model)))) {
          bjp_feedback.push(("Judge '" + String((j["name"] ?? null)) + "' uses unpinned model '" + String(model) + "'. Pin snapshot date."));
          flawed_judges += 1;
        }
        if (truth(!truth((truth(rx.search("\\bpass\\b", prompt_lower)) && truth(rx.search("\\bfail\\b", prompt_lower)))))) {
          bjp_feedback.push("Both binary output labels Pass and Fail must be specified.");
          flawed_judges += 1;
        }
      }
      if (truth(((flawed_judges === 0)))) {
        bjp_pts = 1.0;
      } else {
        penalty = ((flawed_judges / size(llm_evaluators)) * 0.8);
        bjp_pts = Math.max(0.1, (1.0 - penalty));
      }
    }
    domain_scores["binary_judge_design"] = {name: "Binary Judge Design", weight: 0.25, score: Math.min(1.0, bjp_pts), feedback: bjp_feedback};
    sir_feedback = [];
    sir_pts = 0.0;
    split = (eval_spec["splits"] ?? {});
    partitions = ["train", "few_shot", "dev", "test", "held_out"].map((k: any) => (split[k] ?? []));
    valid_ids = partitions.map((ids: any) => (truth(isType(ids, list)) && truth(ids.map((x: any) => (truth(isType(x, str)) && truth(x.trim()))).every(truth)) && truth(((size(ids) === size(new Set(ids))))))).every(truth);
    train_ids = (truth(valid_ids) ? new Set([new Set(), ...partitions.slice(0, 3)].flatMap(x => [...x])) : new Set());
    test_ids = (truth(valid_ids) ? new Set([new Set(), ...partitions.slice(3, undefined)].flatMap(x => [...x])) : new Set());
    if (truth((truth(!truth(valid_ids)) || truth(!truth(train_ids)) || truth(!truth(test_ids))))) {
      sir_feedback.push("Provide nonempty development and held-out sample IDs without duplicates; a boolean isolation claim is insufficient.");
      sir_pts = 0.0;
    } else {
      leakage = new Set([...train_ids].filter(x => test_ids.has(x)));
      if (truth(leakage)) {
        sir_feedback.push(("Data leakage detected! " + String(size(leakage)) + " samples shared between train and test: " + String(Array.from(leakage).slice(0, 3)) + "."));
        sir_pts = 0.0;
      } else {
        sir_pts = 1.0;
      }
    }
    domain_scores["split_isolation"] = {name: "Split Isolation Rigor", weight: 0.2, score: Math.min(1.0, sir_pts), feedback: sir_feedback};
    stat_feedback = [];
    stat_pts = 0.0;
    calib = (eval_spec["calibration"] ?? {});
    tpr = (calib["tpr"] ?? null);
    tnr = (calib["tnr"] ?? null);
    accuracy_only = (truth((calib["accuracy_only"] ?? false)) || truth((truth((((calib["accuracy"] ?? null) !== null))) && truth(((tpr === null))) && truth(((tnr === null))))));
    if (truth(accuracy_only)) {
      stat_feedback.push("Only raw accuracy reported without TPR/TNR. Vulnerable to imbalanced test set bias.");
      stat_pts = 0.2;
    } else {
      if (truth([tpr, tnr].map((x: any) => (truth((contains([int, float], valueType(x)))) && truth(Number.isFinite(x)) && truth(((0 <= x) && (x <= 1))))).every(truth))) {
        if (truth((truth(((tpr >= 0.8))) && truth(((tnr >= 0.8)))))) {
          stat_pts = 1.0;
          if (truth((truth(((tpr >= 0.9))) && truth(((tnr >= 0.9)))))) {

          } else {
            stat_feedback.push(("TPR (" + String((Number(tpr) * 100).toFixed(1) + "%") + ") or TNR (" + String((Number(tnr) * 100).toFixed(1) + "%") + ") meets minimum (80%) but below target (90%)."));
          }
        } else {
          if (truth((truth(((tpr >= 0.7))) && truth(((tnr >= 0.7)))))) {
            stat_pts = 0.6;
            stat_feedback.push(("Sub-threshold TPR (" + String((Number(tpr) * 100).toFixed(1) + "%") + ") or TNR (" + String((Number(tnr) * 100).toFixed(1) + "%") + "). Below 80% minimum."));
          } else {
            stat_pts = 0.3;
            stat_feedback.push(("Uncalibrated evaluator: TPR=" + String((Number(tpr) * 100).toFixed(1) + "%") + ", TNR=" + String((Number(tnr) * 100).toFixed(1) + "%") + "."));
          }
        }
      } else {
        stat_feedback.push("Calibration metrics must be finite numbers between zero and one; missing values and booleans are not measurements.");
        stat_pts = 0.0;
      }
    }
    domain_scores["statistical_rigor"] = {name: "Statistical Rigor (TPR/TNR)", weight: 0.2, score: Math.min(1.0, stat_pts), feedback: stat_feedback};
    rg_feedback = [];
    rg_pts = 0.0;
    prod = (eval_spec["production_monitoring"] ?? {});
    if (truth(!truth(prod))) {
      rg_pts = 0.8;
    } else {
      obs = (prod["observed_pass_rate"] ?? null);
      corrected = (prod["rogan_gladen_corrected"] ?? null);
      claimed = (prod["claimed_success_rate"] ?? null);
      if (truth((truth(((obs !== null))) && truth(((corrected === false))) && truth(((claimed === obs)))))) {
        rg_feedback.push("Naive prevalence claim: Raw observed pass rate reported as true success rate without Rogan-Gladen correction.");
        rg_pts = 0.1;
      } else {
        if (truth((truth(((corrected === true))) || truth((((prod["corrected_rate"] ?? null) !== null)))))) {
          rate = (prod["corrected_rate"] ?? null);
          ci = (prod["ci_95"] ?? null);
          const finite_rate = (x: any) => {
            return (truth((contains([int, float], valueType(x)))) && truth(Number.isFinite(x)) && truth(((0 <= x) && (x <= 1))));
          };
          valid = [obs, rate, tpr, tnr].map((x: any) => finite_rate(x)).every(truth);
          valid = (truth(valid) && truth((((tpr + tnr) > 1))));
          if (truth(valid)) {
            expected = (((obs + tnr) - 1) / ((tpr + tnr) - 1));
            valid = (truth(((0 <= expected) && (expected <= 1))) && truth(Math.abs(rate - expected) <= 1e-06));
          }
          valid = (truth(valid) && truth(isType(ci, list)) && truth(((size(ci) === 2))) && truth(ci.map((x: any) => finite_rate(x)).every(truth)) && truth(((ci[0] <= rate) && (rate <= ci[1]))));
          if (truth(((claimed !== null)))) {
            valid = (truth(valid) && truth(finite_rate(claimed)) && truth(Math.abs(claimed - rate) <= 1e-06));
          }
          rg_pts = (truth(valid) ? 1.0 : 0.0);
          if (truth(!truth(valid))) {
            rg_feedback.push("Correction needs a consistent numeric rate and interval; correction flags alone are not evidence.");
          }
        } else {
          rg_pts = 0.5;
          rg_feedback.push("Production prevalence estimation lacks bias correction details.");
        }
      }
    }
    domain_scores["rogan_gladen_correction"] = {name: "Rogan-Gladen Prevalence", weight: 0.15, score: Math.min(1.0, rg_pts), feedback: rg_feedback};
    overall = Object.values(domain_scores).map((s: any) => (s.score * s.weight)).reduce((a: number, b: number) => a + b, 0);
    passed = (truth(((overall >= this.passing_threshold))) && truth(Object.values(domain_scores).map((s: any) => ((s.score >= 0.5))).every(truth)));
    status = (truth(passed) ? "PASS" : (truth(((overall >= 0.65))) ? "CONDITIONAL" : "FAIL"));
    summary_notes = ["Spec lint only; supplied calibration metrics and labels are not independently verified."];
    for (const s of Object.values(domain_scores)) {
      if (truth(((s.score < 0.7)))) {
        summary_notes.push(((String(s.name) + " scored low (" + String(Number(s.score).toFixed(2)) + "): ") + s.feedback.join("; ")));
      }
    }
    return {domain_scores: domain_scores, summary_notes: summary_notes, target_name: target_name, overall_score: overall, passed: passed, status: status};
  }
}
