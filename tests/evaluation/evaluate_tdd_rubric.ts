import { truth, size, contains, round, rx, re, checkGrounding, isType, valueType, str, int, float, dict, list, type RubricReport } from "./rubric_support.ts";
import { validateReport } from "../../src/ship/tools/review.ts";

export class TDDRubricEvaluator {
  constructor(public passing_threshold = 0.80) {}
  FORBIDDEN_DB_MODULES = ["psycopg", "psycopg2", "sqlite3", "asyncpg", "pymysql", "mysql", "prisma", "sqlalchemy", "redis", "ioredis", "pg", "mongo", "pymongo"];
  evaluate_test_code(code_text: any, target_name: any = "TestSuite"): RubricReport {
    let aaa_feedback: any, aaa_pts: any, descriptive_names: any, dim: any, domain_scores: any, ds_feedback: any, ds_pts: any, fail_feedback: any, fail_pts: any, has_act: any, has_assert: any, has_boundary_probes: any, has_detailed_assertions: any, has_exception_test: any, has_setup: any, has_tautology: any, has_value_checks: any, micro_feedback: any, micro_pts: any, mocked_db: any, mod: any, name: any, notes: any, overall: any, passed: any, spec_feedback: any, spec_pts: any, status: any, test_defs: any;
    domain_scores = {};
    aaa_feedback = [];
    aaa_pts = 0.0;
    has_setup = truth(rx.search("(?:#\\s*arrange|def setUp|fixture|pytest\\.fixture|given\\b)", code_text, re.IGNORECASE));
    has_act = truth(rx.search("(?:#\\s*act|result\\s*=|actual\\s*=|when\\b|response\\s*=)", code_text, re.IGNORECASE));
    has_assert = truth(rx.search("(?:#\\s*assert|assert\\s+|self\\.assert|expect\\(|then\\b)", code_text, re.IGNORECASE));
    if (truth(has_assert)) {
      aaa_pts += 0.4;
    } else {
      aaa_feedback.push("No assertions found in test suite.");
    }
    if (truth(has_act)) {
      aaa_pts += 0.3;
    } else {
      aaa_feedback.push("No clear Act phase or action variable identified.");
    }
    if (truth(has_setup)) {
      aaa_pts += 0.3;
    } else {
      aaa_feedback.push("No explicit Arrange/fixture setup block observed.");
    }
    domain_scores["aaa_structure"] = {name: "AAA Structure", weight: 0.2, score: Math.min(1.0, aaa_pts), feedback: aaa_feedback};
    spec_feedback = [];
    spec_pts = 0.0;
    has_tautology = truth(rx.search("\\bassert\\s+True\\b|\\bassertTrue\\(\\s*True\\s*\\)|\\bassertEqual\\(\\s*([a-zA-Z0-9_]+)\\s*,\\s*\\1\\s*\\)", code_text));
    if (truth(has_tautology)) {
      spec_feedback.push("Critical failure: Tautological assertion detected (e.g. assert True or assertEqual(x, x)).");
      spec_pts = 0.0;
    } else {
      spec_pts += 0.4;
      has_value_checks = truth(rx.search("(?:==|assertEqual|toBe|toEqual|assertIn|\\.status_code\\s*==)", code_text));
      if (truth(has_value_checks)) {
        spec_pts += 0.4;
      } else {
        spec_feedback.push("Lacks concrete equality/value comparisons; assertions appear loose.");
      }
      has_detailed_assertions = ((size(rx.findall("(?:assert\\s+|self\\.assert|expect\\()", code_text)) >= 2));
      if (truth(has_detailed_assertions)) {
        spec_pts += 0.2;
      } else {
        spec_feedback.push("Sparse assertion coverage (fewer than 2 assertions).");
      }
    }
    domain_scores["assertion_specificity"] = {name: "Assertion Specificity", weight: 0.25, score: Math.min(1.0, spec_pts), feedback: spec_feedback};
    ds_feedback = [];
    ds_pts = 0.0;
    mocked_db = false;
    for (const mod of this.FORBIDDEN_DB_MODULES) {
      if (truth((truth(rx.search(("@patch(?:\\.object)?\\([^)]*['\\\"]\\S*" + String(mod) + "\\S*['\\\"]"), code_text)) || truth(rx.search(("mocker\\.patch\\([^)]*['\\\"]\\S*" + String(mod) + "\\S*['\\\"]"), code_text))))) {
        mocked_db = true;
        ds_feedback.push(("Forbidden database mock detected for engine/client '" + String(mod) + "'."));
        break;
      }
    }
    if (truth(mocked_db)) {
      ds_pts = 0.0;
    } else {
      ds_pts += 0.5;
      if (truth(rx.search("sqlite|:memory:|testcontainer|fake|mock_client|in_memory", code_text, re.IGNORECASE))) {
        ds_pts += 0.5;
      } else {
        ds_pts += 0.3;
      }
    }
    domain_scores["dual_speed_fidelity"] = {name: "Dual-Speed Fidelity", weight: 0.25, score: Math.min(1.0, ds_pts), feedback: ds_feedback};
    fail_feedback = [];
    fail_pts = 0.0;
    has_exception_test = truth(rx.search("assertRaises|pytest\\.raises|toThrow|expect\\(\\s*async\\s*\\(\\)\\s*=>", code_text));
    if (truth(has_exception_test)) {
      fail_pts += 0.6;
    } else {
      fail_feedback.push("No negative/exception assertion tests found (e.g. pytest.raises or assertRaises).");
    }
    has_boundary_probes = truth(rx.search("(-1|0|None|null|empty|\\\"\\\"|\\[\\]|\\{\\}|float\\('inf'\\)|404|400|500)", code_text));
    if (truth(has_boundary_probes)) {
      fail_pts += 0.4;
    } else {
      fail_feedback.push("No boundary or zero-value probe cases identified.");
    }
    domain_scores["failure_and_boundary"] = {name: "Failure & Boundary Coverage", weight: 0.15, score: Math.min(1.0, fail_pts), feedback: fail_feedback};
    micro_feedback = [];
    micro_pts = 0.0;
    test_defs = rx.findall("def\\s+(test_[a-zA-Z0-9_]+)\\s*\\(", code_text);
    if (truth(!truth(test_defs))) {
      test_defs = rx.findall("(?:it|test)\\s*\\(\\s*['\\\"]([^'\\\"]+)['\\\"]", code_text);
    }
    if (truth(((size(test_defs) >= 2)))) {
      micro_pts += 0.6;
    } else {
      if (truth(((size(test_defs) === 1)))) {
        micro_pts += 0.4;
        micro_feedback.push("Single test function detected; consider splitting into atomic behavior micro-cycles.");
      } else {
        micro_feedback.push("No test functions identified.");
      }
    }
    descriptive_names = test_defs .filter((name: any) => truth((truth(((size(name) > 10))) && truth((truth((contains(name, "should"))) || truth((contains(name, "when"))) || truth((contains(name, "fails"))) || truth((contains(name, "returns"))) || truth((contains(name, "raises"))) || truth((contains(name, "_")))))))).map((name: any) => name);
    if (truth(descriptive_names)) {
      micro_pts += 0.4;
    } else {
      micro_feedback.push("Test function names lack descriptive intent (e.g. test_when_empty_should_raise).");
    }
    domain_scores["micro_cycle_focus"] = {name: "Micro-Cycle Focus", weight: 0.15, score: Math.min(1.0, micro_pts), feedback: micro_feedback};
    overall = Object.values(domain_scores).map((dim: any) => (dim.score * dim.weight)).reduce((a: number, b: number) => a + b, 0);
    passed = (truth(((overall >= this.passing_threshold))) && truth(!truth(has_tautology)) && truth(!truth(mocked_db)));
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
    if (truth(has_tautology)) {
      notes.push("REJECTED: Tautological assertion detected.");
    }
    if (truth(mocked_db)) {
      notes.push("REJECTED: Database engine/driver mocked in violation of Tier 2 testing policy.");
    }
    if (truth(!truth(notes))) {
      notes.push(("TDD Rubric Assessment completed with score " + String(round(overall, 3)) + " (" + String(status) + ")."));
    }
    return {domain_scores: domain_scores, summary_notes: notes, target_name: target_name, overall_score: overall, passed: passed, status: status};
  }
}
