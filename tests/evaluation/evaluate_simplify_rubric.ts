import { truth, size, contains, round, rx, re, checkGrounding, isType, valueType, str, int, float, dict, list, type RubricReport } from "./rubric_support.ts";
import { validateReport } from "../../src/ship/tools/review.ts";

export class SimplifyRubricEvaluator {
  constructor(public passing_threshold = 0.80) {}
  FORBIDDEN_REDUNDANT_DEPS = ["uuid", "lodash.clonedeep", "lodash.get", "rimraf", "mkdirp", "node-fetch", "pytz", "left-pad", "is-odd"];
  evaluate_code(code_text: any, target_name: any = "SourceFile"): RubricReport {
    let comp_feedback: any, comp_pts: any, debt_feedback: any, debt_markers: any, debt_pts: any, deep_feedback: any, deep_pts: any, dep: any, dim: any, domain_scores: any, err_feedback: any, err_pts: any, factory_matches: any, has_ceiling: any, has_defensive_overkill: any, has_redundant_dep: any, has_upgrade: any, indent: any, line: any, loc: any, marker: any, max_indent: any, notes: any, overall: any, passed: any, shallow_forwarders: any, status: any, stdlib_feedback: any, stdlib_pts: any, valid_count: any;
    if (truth(!truth(code_text.trim()))) {
      return {domain_scores: {}, summary_notes: ["No source supplied; absence of detected smells is not evidence of a working solution."], target_name: target_name, overall_score: 0.0, passed: false, status: "INCONCLUSIVE"};
    }
    domain_scores = {};
    comp_feedback = [];
    comp_pts = 0.0;
    factory_matches = rx.findall("class\\s+\\w*Factory\\b", code_text);
    if (truth(factory_matches)) {
      comp_feedback.push(("Speculative factory classes detected: " + String(factory_matches.join(", ")) + "."));
      comp_pts += 0.2;
    } else {
      comp_pts += 0.5;
    }
    max_indent = 0;
    for (const line of code_text.split(/\r?\n/)) {
      indent = (size(line) - size(line.replace(/^ +/, "")));
      if (truth((truth(line.trim()) && truth(((indent > max_indent)))))) {
        max_indent = indent;
      }
    }
    if (truth(((max_indent > 16)))) {
      comp_feedback.push(("High nesting depth observed (max indent " + String(max_indent) + " spaces)."));
      comp_pts += 0.2;
    } else {
      comp_pts += 0.5;
    }
    domain_scores["complexity_reduction"] = {name: "Complexity Reduction", weight: 0.25, score: Math.min(1.0, comp_pts), feedback: comp_feedback};
    deep_feedback = [];
    deep_pts = 0.0;
    shallow_forwarders = rx.findall("def\\s+\\w+\\([^)]*\\):\\s*(?:return\\s+self\\._?\\w+\\.\\w+\\([^)]*\\))", code_text);
    if (truth(shallow_forwarders)) {
      deep_feedback.push(("Detected shallow forwarding method(s) that delegate without logic: " + String(size(shallow_forwarders)) + "."));
      deep_pts = 0.3;
    } else {
      deep_pts = 0.6;
    }
    loc = size(code_text.split(/\r?\n/) .filter((line: any) => truth((truth(line.trim()) && truth(!truth(line.trim().startsWith(["#", "//", "/*"])))))).map((line: any) => line));
    if (truth((truth(((loc >= 5))) && truth(!truth(shallow_forwarders))))) {
      deep_pts += 0.4;
    } else {
      deep_pts += 0.2;
    }
    domain_scores["deep_module_design"] = {name: "Deep Module Leverage", weight: 0.25, score: Math.min(1.0, deep_pts), feedback: deep_feedback};
    stdlib_feedback = [];
    stdlib_pts = 0.0;
    has_redundant_dep = false;
    for (const dep of this.FORBIDDEN_REDUNDANT_DEPS) {
      if (truth(rx.search(("['\\\"]" + String(rx.escape(dep)) + "['\\\"]|\\bimport\\s+" + String(rx.escape(dep)) + "\\b"), code_text))) {
        has_redundant_dep = true;
        stdlib_feedback.push(("Redundant 3rd-party dependency '" + String(dep) + "' imported when native standard library exists."));
      }
    }
    if (truth(has_redundant_dep)) {
      stdlib_pts = 0.2;
    } else {
      stdlib_pts = 0.7;
      if (truth(rx.search("crypto\\.randomUUID|structuredClone|pathlib|zoneinfo|dataclass", code_text))) {
        stdlib_pts += 0.3;
      }
    }
    domain_scores["stdlib_first"] = {name: "Stdlib & Platform First", weight: 0.2, score: Math.min(1.0, stdlib_pts), feedback: stdlib_feedback};
    err_feedback = [];
    err_pts = 0.0;
    has_defensive_overkill = ((size(rx.findall("if\\s+\\w+\\s*==\\s*null|if\\s+\\w+\\s*is\\s+None", code_text)) >= 6));
    if (truth(has_defensive_overkill)) {
      err_feedback.push("Repeated defensive null checks at multiple callsites; fix at root entrypoint.");
      err_pts += 0.4;
    } else {
      err_pts += 0.7;
    }
    if (truth(rx.search("\\.get\\(|\\?\\.|or\\s+\\[\\]|or\\s+\\{\\}|default=", code_text))) {
      err_pts += 0.3;
    }
    domain_scores["error_definition"] = {name: "Error Definition Quality", weight: 0.15, score: Math.min(1.0, err_pts), feedback: err_feedback};
    debt_feedback = [];
    debt_pts = 0.0;
    debt_markers = rx.findall("simplify:\\s*(.+)$", code_text, (re.MULTILINE | re.IGNORECASE));
    if (truth(!truth(debt_markers))) {
      debt_pts = 1.0;
    } else {
      valid_count = 0;
      for (const marker of debt_markers) {
        has_ceiling = truth(rx.search("Ceiling:\\s*(?!none|n/a|tbd|todo)[^.|;\\n]+", marker, re.IGNORECASE));
        has_upgrade = truth(rx.search("Upgrade:\\s*(?!none|n/a|tbd|todo)[^.|;\\n]+", marker, re.IGNORECASE));
        if (truth((truth(has_ceiling) && truth(has_upgrade)))) {
          valid_count += 1;
        } else {
          debt_feedback.push(("Incomplete/vague debt marker: '" + String(marker.slice(0, 60)) + "...'"));
        }
      }
      if (truth(((valid_count === size(debt_markers))))) {
        debt_pts = 1.0;
      } else {
        debt_pts = (valid_count / size(debt_markers));
      }
    }
    domain_scores["debt_marker_rigor"] = {name: "Debt Marker Rigor", weight: 0.15, score: Math.min(1.0, debt_pts), feedback: debt_feedback};
    overall = Object.values(domain_scores).map((dim: any) => (dim.score * dim.weight)).reduce((a: number, b: number) => a + b, 0);
    passed = (truth(((overall >= this.passing_threshold))) && truth(!truth(has_redundant_dep)));
    if (truth(passed)) {
      status = "PASS";
    } else {
      if (truth(((overall >= 0.6)))) {
        status = "CONDITIONAL";
      } else {
        status = "FAIL";
      }
    }
    notes = [];
    if (truth(has_redundant_dep)) {
      notes.push("REJECTED: Redundant external package detected where standard library suffices.");
    }
    if (truth(factory_matches)) {
      notes.push(("WARNING: Speculative factories detected: " + String(factory_matches.join(", ")) + "."));
    }
    if (truth(!truth(notes))) {
      notes.push(("Simplify Rubric Assessment completed with score " + String(round(overall, 3)) + " (" + String(status) + ")."));
    }
    return {domain_scores: domain_scores, summary_notes: notes, target_name: target_name, overall_score: overall, passed: passed, status: status};
  }
}
