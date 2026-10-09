import test, { describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import {
  auditContent,
  auditFile,
  auditPath,
  main,
} from "../src/ship/tools/ux.ts";

const SCRIPT_PATH = path.resolve("src/ship/tools/ux.ts");

describe("TypeScript UX & Accessibility Audit Scanner (audit_ux.ts)", () => {
  it("detects interactive non-native elements lacking keyboard handlers (UX-001)", () => {
    // Bad div
    const badHtml = '<div onClick={() => submit()}>Click me</div>';
    const v1 = auditContent(badHtml, "test.tsx");
    assert.ok(v1.some((v) => v.rule_id === "UX-001" && v.severity === "ERROR"));

    // Good native button
    const goodHtml = '<button onClick={() => submit()}>Click me</button>';
    const v2 = auditContent(goodHtml, "test.tsx");
    assert.ok(!v2.some((v) => v.rule_id === "UX-001"));

    // Good div with keyboard handler
    const goodDiv = '<div role="button" tabIndex={0} onClick={() => submit()} onKeyDown={(e) => handle(e)}>Click me</div>';
    const v3 = auditContent(goodDiv, "test.tsx");
    assert.ok(!v3.some((v) => v.rule_id === "UX-001"));
  });

  it("detects suppressed focus outlines without replacement indicators (UX-002)", () => {
    const badOutline = '<button className="outline-none py-2 px-4">Submit</button>';
    const v1 = auditContent(badOutline, "test.tsx");
    assert.ok(v1.some((v) => v.rule_id === "UX-002" && v.severity === "ERROR"));

    const goodRing = '<button className="outline-none focus-visible:ring-2 focus-visible:ring-blue-500 py-2">Submit</button>';
    const v2 = auditContent(goodRing, "test.tsx");
    assert.ok(!v2.some((v) => v.rule_id === "UX-002"));
  });

  it("detects unlabelled icon buttons (UX-003 / UX-031)", () => {
    // Unlabelled icon button -> UX-003 ERROR
    const badIcon = '<button className="p-2"><svg className="w-5 h-5" /></button>';
    const v1 = auditContent(badIcon, "test.tsx");
    assert.ok(v1.some((v) => v.rule_id === "UX-003" && v.severity === "ERROR"));

    // Accessible aria-label -> clean
    const goodIcon = '<button aria-label="Close" className="p-2"><svg className="w-5 h-5" /></button>';
    const v2 = auditContent(goodIcon, "test.tsx");
    assert.ok(!v2.some((v) => v.rule_id === "UX-003"));

    // Title only -> UX-031 INFO
    const titleIcon = '<button title="Close" className="p-2"><svg className="w-5 h-5" /></button>';
    const v3 = auditContent(titleIcon, "test.tsx");
    assert.ok(v3.some((v) => v.rule_id === "UX-031" && v.severity === "INFO"));
  });

  it("detects form inputs lacking accessible names (UX-014)", () => {
    const unlabelledInput = '<input type="email" name="email" />';
    const v1 = auditContent(unlabelledInput, "test.tsx");
    assert.ok(v1.some((v) => v.rule_id === "UX-014" && v.severity === "ERROR"));

    const labelledInput = '<label htmlFor="email">Email</label><input id="email" type="email" />';
    const v2 = auditContent(labelledInput, "test.tsx");
    assert.ok(!v2.some((v) => v.rule_id === "UX-014"));
  });

  it("detects dead-end generic errors lacking actionable CTAs (UX-005)", () => {
    const deadEnd = '<p className="text-red-500">Something went wrong</p>';
    const v1 = auditContent(deadEnd, "test.tsx");
    assert.ok(v1.some((v) => v.rule_id === "UX-005" && v.severity === "WARNING"));

    const withCta = '<p className="text-red-500">Something went wrong <button onClick={retry}>Retry</button></p>';
    const v2 = auditContent(withCta, "test.tsx");
    assert.ok(!v2.some((v) => v.rule_id === "UX-005"));
  });

  it("detects arbitrary Tailwind dimension tokens (UX-021)", () => {
    const arbitrary = '<div className="p-[23px] w-[350px]">Content</div>';
    const v1 = auditContent(arbitrary, "test.tsx");
    assert.ok(v1.some((v) => v.rule_id === "UX-021" && v.severity === "WARNING"));

    const allowed = '<div className="p-4 w-full">Content</div>';
    const v2 = auditContent(allowed, "test.tsx");
    assert.ok(!v2.some((v) => v.rule_id === "UX-021"));
  });

  it("detects modal dialogs lacking accessible names (UX-041)", () => {
    const unlabelledDialog = '<dialog className="p-6">Dialog content</dialog>';
    const v1 = auditContent(unlabelledDialog, "test.tsx");
    assert.ok(v1.some((v) => v.rule_id === "UX-041" && v.severity === "ERROR"));

    const labelledDialog = '<dialog aria-labelledby="dialog-title" className="p-6"><h2 id="dialog-title">Title</h2></dialog>';
    const v2 = auditContent(labelledDialog, "test.tsx");
    assert.ok(!v2.some((v) => v.rule_id === "UX-041"));
  });

  it("detects dynamic collections lacking loading and empty states (UX-051)", () => {
    const incompleteMap = '<div>{items.map((item) => <Item key={item.id} />)}</div>';
    const v1 = auditContent(incompleteMap, "test.tsx");
    assert.ok(v1.some((v) => v.rule_id === "UX-051" && v.severity === "WARNING"));

    const completeMap = `
<div>
  {isLoading ? <Skeleton /> : items.length === 0 ? <p>No items found</p> : items.map((i) => <Item key={i.id} />)}
</div>
`;
    const v2 = auditContent(completeMap, "test.tsx");
    assert.ok(!v2.some((v) => v.rule_id === "UX-051"));
  });

  it("runs CLI on file path with JSON and template output", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ux-cli-"));
    try {
      const tsxFile = path.join(tmpDir, "component.tsx");
      fs.writeFileSync(tsxFile, '<button onClick={() => alert()}>Submit</button>');

      const stdoutJson = execFileSync(
        process.execPath,
        [SCRIPT_PATH, "--json", tsxFile],
        { encoding: "utf-8" }
      );
      const parsed = JSON.parse(stdoutJson);
      assert.equal(parsed.total_violations, 0);

      // Template flag
      const stdoutTpl = execFileSync(
        process.execPath,
        [SCRIPT_PATH, "--template"],
        { encoding: "utf-8" }
      );
      assert.ok(stdoutTpl.includes("Universal Accessible Component Blueprints"));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
