import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync, execFileSync } from "node:child_process";
import { runBenchmark, runSingleIteration } from "../src/ship/tools/spike.ts";
import { checkAntiPatterns, getChangedFiles } from "../src/ship/tools/tdd.ts";
import { scanPaths } from "../src/ship/tools/simplify.ts";
import { parseReport } from "../src/ship/tools/review.ts";

let root: string;
beforeEach(() => {root = fs.mkdtempSync(path.join(os.tmpdir(), "ship-runtime-"));});
afterEach(() => {fs.rmSync(root, {recursive: true, force: true});});
const command = (code: string) => [process.execPath, "-e", code];
const cli = (tool: string, args: string[], input?: string) => spawnSync(process.execPath, [path.resolve(`src/ship/tools/${tool}.ts`), ...args], {encoding: "utf8", input});

describe("migrated spike execution contracts", () => {
  it("runs concurrent workers, excludes warmup, and respects the iteration limit", async () => {
    const script = path.join(root, "worker.ts");
    fs.writeFileSync(script, `import fs from 'node:fs'; fs.appendFileSync('events', 'start\\n'); await Bun.sleep(80); fs.appendFileSync('events', 'end\\n');`);
    const result = await runBenchmark({cmd: [process.execPath, script], cwd: root, iterations: 6, warmup: 2, concurrency: 2});
    expect(result.total_runs).toBe(6); expect(result.failed_runs).toBe(0);
    const events = fs.readFileSync(path.join(root, "events"), "utf8").trim().split("\n");
    expect(events.filter(x => x === "start").length).toBe(8);
    let active = 0, peak = 0;
    for (const event of events) {active += event === "start" ? 1 : -1; peak = Math.max(peak, active);}
    expect(active).toBe(0); expect(peak).toBe(2);
    expect(result.min_ms).toBeLessThanOrEqual(result.p50_ms);
    expect(result.p99_ms).toBeLessThanOrEqual(result.max_ms);
  });
  it("duration mode finishes in-flight slow commands without dropping results", async () => {
    const result = await runBenchmark({cmd: command("await Bun.sleep(150)"), iterations: 0, durationSec: .25, concurrency: 2});
    expect(result.total_runs).toBeGreaterThanOrEqual(2);
    expect(result.failed_runs).toBe(0); expect(result.total_duration_sec).toBeLessThan(2);
  });
  it("clamps negative counts and zero workers", async () => {
    const result = await runBenchmark({cmd: command("process.exit(0)"), iterations: -5, warmup: -2, concurrency: 0});
    expect(result.total_runs).toBe(0); expect(result.error_rate_pct).toBe(100);
  });
  it("kills the entire process group on timeout", async () => {
    const marker = path.join(root, "orphan");
    const child = `await Bun.sleep(400); require('node:fs').writeFileSync(${JSON.stringify(marker)}, 'orphan')`;
    const parent = `require('node:child_process').spawn(process.execPath, ['-e', ${JSON.stringify(child)}], {stdio: 'ignore'}); await Bun.sleep(5000)`;
    const result = await runBenchmark({cmd: command(parent), iterations: 1, timeoutSec: .1});
    expect(result.failed_runs).toBe(1);
    await Bun.sleep(500); expect(fs.existsSync(marker)).toBe(false);
  });
  it("returns failed iterations for missing executables", async () => {
    const [, passed] = await runSingleIteration([path.join(root, "missing")]); expect(passed).toBe(false);
  });
  it("retains legacy JSON envelopes, timeout flags, and exit status", () => {
    const result = cli("spike", ["--cmd", `'${process.execPath}' -e 'await Bun.sleep(500)'`, "--iterations", "2", "--warmup", "0", "--timeout", "0.05", "--json"]);
    expect(result.status).toBe(1);
    const data = JSON.parse(result.stdout); expect(data.metrics.failed_runs).toBe(2); expect(data.passed).toBe(false);
    expect(data.metrics.measurement_scope).toBe("subprocess_wall_time"); expect(data.markdown_table).toContain("Command runs / second");
  });
  it("probe cleanup happens only on success", () => {
    const success = path.join(root, "success"), failure = path.join(root, "failure"); fs.mkdirSync(success); fs.mkdirSync(failure);
    const pass = cli("spike", ["--cmd", "echo probe", "--probe", "--cleanup", success, "--json"]);
    expect(pass.status).toBe(0); expect(JSON.parse(pass.stdout).probe).toBe(true); expect(fs.existsSync(success)).toBe(false);
    const fail = cli("spike", ["--cmd", "exit 2", "--probe", "--cleanup", failure, "--json"]);
    expect(fail.status).toBe(1); expect(fs.existsSync(failure)).toBe(true);
  });
  it("rejects malformed options and preserves equals signs inside commands", () => {
    expect(cli("spike", ["--unknown"]).status).toBe(1);
    expect(cli("spike", ["--cmd", "true", "--iterations", "NaN"]).status).toBe(1);
    expect(cli("spike", ["--cmd=VALUE=yes; test \"$VALUE\" = yes", "--probe", "--json"]).status).toBe(0);
  });
});

describe("migrated scanner and parser regressions", () => {
  it("does not borrow an assertion from a following helper or a docstring", () => {
    const file = path.join(root, "test_scope.py");
    fs.writeFileSync(file, 'async def test_missing():\n    """assert True\n    # simplify: fake marker\n    """\n    run()\ndef helper():\n    assert real()\n');
    expect(checkAntiPatterns(file).map(f => f.ruleId)).toEqual(["TDD-ASRT-001"]);
    expect(scanPaths([file])).toEqual([]);
  });
  it("discovers staged and untracked files before the first commit", () => {
    execFileSync("git", ["init", "-q"], {cwd: root});
    fs.writeFileSync(path.join(root, "app.py"), "answer = 42\n"); execFileSync("git", ["add", "app.py"], {cwd: root});
    fs.writeFileSync(path.join(root, "test_app.py"), "assert answer == 42\n");
    expect(getChangedFiles(undefined, root).sort()).toEqual(["app.py", "test_app.py"]);
    expect(() => getChangedFiles("missing..ref", root)).toThrow();
  });
  it("rejects duplicate keys including escaped spellings and nonfinite JSON", () => {
    for (const text of ['{"status":1,"status":2}', '{"status":1,"\\u0073tatus":2}', '{"x":NaN}', '{"x":1e999}']) expect(() => parseReport(text)).toThrow();
    expect(parseReport('{"outer":{"same":1},"same":2}')).toEqual({outer: {same: 1}, same: 2});
  });
});
