#!/usr/bin/env python3
"""sample_traces.py — Diverse and stratified trace sampling for error discovery.

Avoids sampling bias by combining:
1. Heuristic diversity (stratified by input/output length, tool calls, error markers)
2. Random sampling (to discover unknown unknowns)

Zero external dependencies (Python 3.10+ standard library).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import random
import sys
from typing import Any, Dict, List, Optional


def load_traces(path: Path) -> List[Dict[str, Any]]:
    """Load traces from JSONL, JSON, or CSV."""
    if not path.exists():
        raise FileNotFoundError(f"Trace file not found: {path}")

    traces: List[Dict[str, Any]] = []
    suffix = path.suffix.lower()

    if suffix in (".jsonl", ".ndjson"):
        with open(path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if isinstance(record, dict):
                    if "id" not in record and "trace_id" not in record:
                        record["trace_id"] = f"trace_{idx}"
                    traces.append(record)

    elif suffix == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                for idx, record in enumerate(data, 1):
                    if isinstance(record, dict):
                        if "id" not in record and "trace_id" not in record:
                            record["trace_id"] = f"trace_{idx}"
                        traces.append(record)
            elif isinstance(data, dict):
                # Wrapped records
                for key in ("traces", "records", "data", "samples"):
                    if isinstance(data.get(key), list):
                        for idx, record in enumerate(data[key], 1):
                            if isinstance(record, dict):
                                if "id" not in record and "trace_id" not in record:
                                    record["trace_id"] = f"trace_{idx}"
                                traces.append(record)
                        break

    elif suffix == ".csv":
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader, 1):
                if "id" not in row and "trace_id" not in row:
                    row["trace_id"] = f"trace_{idx}"
                traces.append(dict(row))

    return traces


def extract_features(record: Dict[str, Any]) -> Dict[str, Any]:
    """Extract structural heuristics for stratified bucketing."""
    text = ""
    for k in ("output", "response", "content", "answer", "text", "completion"):
        if isinstance(record.get(k), str):
            text += record[k] + " "

    input_text = ""
    for k in ("input", "prompt", "query", "user", "messages"):
        val = record.get(k)
        if isinstance(val, str):
            input_text += val + " "
        elif isinstance(val, list):
            input_text += json.dumps(val) + " "

    tool_calls = 0
    if "tool_calls" in record and isinstance(record["tool_calls"], list):
        tool_calls = len(record["tool_calls"])
    elif "tools" in record and isinstance(record["tools"], list):
        tool_calls = len(record["tools"])

    has_error = bool(record.get("error") or record.get("status") in ("error", "failed", "500"))

    # Length buckets: short (<200 chars), medium (200-1000), long (>1000)
    out_len = len(text.strip())
    if out_len < 200:
        len_bucket = "short"
    elif out_len < 1000:
        len_bucket = "medium"
    else:
        len_bucket = "long"

    return {
        "len_bucket": len_bucket,
        "out_length": out_len,
        "in_length": len(input_text.strip()),
        "has_tools": tool_calls > 0,
        "has_error": has_error,
    }


def select_diverse_sample(
    traces: List[Dict[str, Any]],
    n_samples: int = 30,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """Select sample combining stratified feature diversity and random sampling."""
    if len(traces) <= n_samples:
        return list(traces)

    rng = random.Random(seed)

    # 1. Bucket traces by features
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for t in traces:
        feat = extract_features(t)
        key = f"{feat['len_bucket']}_tools={feat['has_tools']}_err={feat['has_error']}"
        buckets.setdefault(key, []).append(t)

    # 2. Allocate 65% to stratified diversity
    stratified_target = max(1, int(n_samples * 0.65))
    selected: List[Dict[str, Any]] = []
    seen_ids = set()

    # Round-robin pick from buckets
    bucket_keys = sorted(buckets.keys())
    while len(selected) < stratified_target and any(buckets[k] for k in bucket_keys):
        for k in bucket_keys:
            if buckets[k] and len(selected) < stratified_target:
                candidate = rng.choice(buckets[k])
                buckets[k].remove(candidate)
                c_id = candidate.get("trace_id") or candidate.get("id") or id(candidate)
                if c_id not in seen_ids:
                    seen_ids.add(c_id)
                    selected.append(candidate)

    # 3. Allocate remaining 35% to pure random selection across all remaining traces
    remaining = [t for t in traces if (t.get("trace_id") or t.get("id") or id(t)) not in seen_ids]
    random_target = n_samples - len(selected)
    if remaining and random_target > 0:
        random_picks = rng.sample(remaining, min(len(remaining), random_target))
        selected.extend(random_picks)

    return selected


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Stratified and diverse trace sampling for error discovery.")
    parser.add_argument("--input", "-i", type=Path, required=True, help="Input traces file (.jsonl, .json, .csv)")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output path (default: stdout as JSONL)")
    parser.add_argument("--count", "-n", type=int, default=25, help="Number of traces to sample (default: 25)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")

    args = parser.parse_args(argv)

    try:
        traces = load_traces(args.input)
    except Exception as e:
        print(f"Error reading traces: {e}", file=sys.stderr)
        return 1

    if not traces:
        print("Error: No traces found in input file.", file=sys.stderr)
        return 1

    sample = select_diverse_sample(traces, n_samples=args.count, seed=args.seed)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            for item in sample:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"Sampled {len(sample)} diverse traces to {args.output}")
    else:
        for item in sample:
            print(json.dumps(item, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
