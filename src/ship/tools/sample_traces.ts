#!/usr/bin/env node
/**
 * sample_traces.ts — Diverse and stratified trace sampling for error discovery.
 * Zero external dependencies (Node.js 22+ / 25+ standard library).
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

function parseCsv(content: string): Record<string, string>[] {
  const [head, ...rows] = content.trim().split(/\r?\n/).map((l) => l.split(",").map((c) => c.trim()));
  if (!head || !rows.length) return [];
  return rows.map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""])));
}

export function loadTraces(filePath: string): Record<string, any>[] {
  const resolved = path.resolve(filePath);
  if (!fs.existsSync(resolved)) throw new Error(`Trace file not found: ${resolved}`);

  const ext = path.extname(resolved).toLowerCase();
  const raw = fs.readFileSync(resolved, "utf-8");
  let items: any[] = [];

  if (ext === ".jsonl" || ext === ".ndjson") {
    items = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((l) => JSON.parse(l));
  } else if (ext === ".json") {
    const data = JSON.parse(raw);
    items = Array.isArray(data)
      ? data
      : ["traces", "records", "data", "samples"].map((k) => data?.[k]).find(Array.isArray) ?? [];
  } else if (ext === ".csv") {
    items = parseCsv(raw);
  }

  return items.filter((r) => typeof r === "object" && r !== null).map((r, i) => {
    if (!("id" in r) && !("trace_id" in r)) r.trace_id = `trace_${i + 1}`;
    return r;
  });
}

export interface TraceFeatures {
  len_bucket: "short" | "medium" | "long";
  out_length: number;
  in_length: number;
  has_tools: boolean;
  has_error: boolean;
}

export function extractFeatures(record: Record<string, any>): TraceFeatures {
  const text = ["output", "response", "content", "answer", "text", "completion"]
    .map((k) => record[k]).filter((v) => typeof v === "string").join(" ");

  const inputText = ["input", "prompt", "query", "user", "messages"]
    .map((k) => (typeof record[k] === "string" ? record[k] : Array.isArray(record[k]) ? JSON.stringify(record[k]) : ""))
    .filter(Boolean).join(" ");

  const tools = record.tool_calls ?? record.tools;
  const toolCalls = Array.isArray(tools) ? tools.length : 0;
  const hasError = Boolean(record.error || ["error", "failed", "500"].includes(String(record.status).toLowerCase()));
  const outLen = text.trim().length;

  return {
    len_bucket: outLen < 200 ? "short" : outLen < 1000 ? "medium" : "long",
    out_length: outLen,
    in_length: inputText.trim().length,
    has_tools: toolCalls > 0,
    has_error: hasError,
  };
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    let t = (a += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function selectDiverseSample(
  traces: Record<string, any>[],
  nSamples: number = 30,
  seed: number = 42
): Record<string, any>[] {
  if (traces.length <= nSamples) return [...traces];

  const rng = mulberry32(seed);
  const buckets = Map.groupBy(traces, (t) => {
    const f = extractFeatures(t);
    return `${f.len_bucket}_tools=${f.has_tools}_err=${f.has_error}`;
  });

  const stratifiedTarget = Math.max(1, Math.floor(nSamples * 0.65));
  const selected: Record<string, any>[] = [];
  const seenIds = new Set<string>();
  const idOf = (t: Record<string, any>) => String(t.trace_id ?? t.id ?? JSON.stringify(t));

  const bucketKeys = Array.from(buckets.keys()).sort();
  let hasMore = true;
  while (selected.length < stratifiedTarget && hasMore) {
    hasMore = false;
    for (const k of bucketKeys) {
      const list = buckets.get(k)!;
      if (list.length > 0) {
        hasMore = true;
        if (selected.length < stratifiedTarget) {
          const item = list.splice(Math.floor(rng() * list.length), 1)[0];
          const id = idOf(item);
          if (!seenIds.has(id)) {
            seenIds.add(id);
            selected.push(item);
          }
        }
      }
    }
  }

  const remaining = traces.filter((t) => !seenIds.has(idOf(t)));
  const randomTarget = nSamples - selected.length;
  if (remaining.length > 0 && randomTarget > 0) {
    const pool = [...remaining];
    const take = Math.min(pool.length, randomTarget);
    for (let i = 0; i < take; i++) {
      const j = i + Math.floor(rng() * (pool.length - i));
      [pool[i], pool[j]] = [pool[j], pool[i]];
      selected.push(pool[i]);
    }
  }

  return selected;
}

export function main(argv: string[] = process.argv.slice(2)): number {
  let inputPath: string | null = null;
  let outputPath: string | null = null;
  let count = 25;
  let seed = 42;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--input" || arg === "-i") inputPath = argv[++i];
    else if (arg === "--output" || arg === "-o") outputPath = argv[++i];
    else if (arg === "--count" || arg === "-n") count = parseInt(argv[++i], 10);
    else if (arg === "--seed") seed = parseInt(argv[++i], 10);
  }

  if (!inputPath) {
    console.error("Error: --input is required");
    return 1;
  }

  let traces: Record<string, any>[];
  try {
    traces = loadTraces(inputPath);
  } catch (e: any) {
    console.error(`Error reading traces: ${e.message}`);
    return 1;
  }

  if (traces.length === 0) {
    console.error("Error: No traces found in input file.");
    return 1;
  }

  const sample = selectDiverseSample(traces, count, seed);

  if (outputPath) {
    const resolvedOut = path.resolve(outputPath);
    fs.mkdirSync(path.dirname(resolvedOut), { recursive: true });
    fs.writeFileSync(resolvedOut, sample.map((s) => JSON.stringify(s)).join("\n") + "\n", "utf-8");
    console.log(`Sampled ${sample.length} diverse traces to ${outputPath}`);
  } else {
    for (const item of sample) console.log(JSON.stringify(item));
  }

  return 0;
}

if (process.argv[1] && import.meta.filename && process.argv[1] === import.meta.filename) {
  process.exit(main());
}
