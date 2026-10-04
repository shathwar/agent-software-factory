#!/usr/bin/env python3
"""serve_review_app.py — Zero-dependency local annotation and trace review server.

Serves an interactive single-page app for human review of LLM traces,
inline annotation, and failure mode taxonomy building.
Zero external dependencies (Python 3.10+ standard library).
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import urllib.parse

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Eval Trace Review & Error Discovery</title>
<style>
  :root {
    --bg: #0f172a;
    --surface: #1e293b;
    --surface-hover: #334155;
    --text: #f8fafc;
    --text-muted: #94a3b8;
    --border: #334155;
    --primary: #38bdf8;
    --accent: #f59e0b;
    --danger: #ef4444;
    --success: #10b981;
    --system-role: #64748b;
    --user-role: #0284c7;
    --assistant-role: #059669;
    --tool-role: #d97706;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  body { background: var(--bg); color: var(--text); display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 12px 24px; display: flex; justify-content: space-between; align-items: center; }
  header h1 { font-size: 1.1rem; font-weight: 600; color: var(--primary); }
  .badge { background: #0369a1; color: #fff; font-size: 0.75rem; padding: 2px 8px; border-radius: 9999px; }
  main { display: flex; flex: 1; overflow: hidden; }
  #sidebar { width: 300px; background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow-y: auto; }
  .sidebar-header { padding: 14px 16px; border-bottom: 1px solid var(--border); font-size: 0.85rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; }
  .sample-item { padding: 12px 16px; border-bottom: 1px solid rgba(255,255,255,0.05); cursor: pointer; transition: background 0.15s; }
  .sample-item:hover { background: var(--surface-hover); }
  .sample-item.active { background: #1e3a8a; border-left: 3px solid var(--primary); }
  .sample-title { font-size: 0.9rem; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sample-meta { font-size: 0.75rem; color: var(--text-muted); margin-top: 4px; display: flex; justify-content: space-between; }
  #content-pane { flex: 1; display: flex; overflow: hidden; }
  #trace-viewer { flex: 1; padding: 24px; overflow-y: auto; max-width: 800px; margin: 0 auto; }
  .trace-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 20px; }
  .turn-bubble { border-radius: 6px; padding: 14px; margin-bottom: 14px; background: rgba(15,23,42,0.6); border-left: 4px solid var(--border); }
  .turn-bubble.user { border-left-color: var(--user-role); }
  .turn-bubble.assistant { border-left-color: var(--assistant-role); }
  .turn-bubble.system { border-left-color: var(--system-role); }
  .turn-bubble.tool { border-left-color: var(--tool-role); }
  .turn-header { font-size: 0.75rem; font-weight: 700; text-transform: uppercase; margin-bottom: 6px; color: var(--text-muted); }
  .turn-body { font-size: 0.95rem; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
  #margin-pane { width: 340px; background: var(--surface); border-left: 1px solid var(--border); padding: 16px; overflow-y: auto; }
  .pane-title { font-size: 0.85rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; margin-bottom: 12px; }
  .annotation-form { background: rgba(15,23,42,0.8); border: 1px solid var(--border); border-radius: 6px; padding: 12px; margin-bottom: 16px; }
  .annotation-form textarea { width: 100%; background: var(--bg); border: 1px solid var(--border); border-radius: 4px; color: var(--text); padding: 8px; font-size: 0.85rem; resize: vertical; min-height: 60px; margin-bottom: 8px; }
  .annotation-form input { width: 100%; background: var(--bg); border: 1px solid var(--border); border-radius: 4px; color: var(--text); padding: 6px; font-size: 0.85rem; margin-bottom: 8px; }
  .btn { background: var(--primary); color: #0f172a; border: none; border-radius: 4px; padding: 6px 12px; font-size: 0.85rem; font-weight: 600; cursor: pointer; }
  .btn-danger { background: var(--danger); color: #fff; }
  .annotation-card { background: rgba(15,23,42,0.8); border-left: 3px solid var(--accent); border-radius: 4px; padding: 10px; margin-bottom: 10px; font-size: 0.85rem; }
  .annotation-tag { display: inline-block; background: #854d0e; color: #fef08a; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; margin-bottom: 4px; }
</style>
</head>
<body>
<header>
  <div>
    <h1>AI Eval Trace Review <span class="badge" id="sample-count">0 traces</span></h1>
  </div>
  <div>
    <button class="btn" onclick="exportData()">Export Annotations</button>
  </div>
</header>
<main>
  <div id="sidebar">
    <div class="sidebar-header">Traces</div>
    <div id="sample-list"></div>
  </div>
  <div id="content-pane">
    <div id="trace-viewer">
      <div id="empty-state" style="text-align: center; margin-top: 100px; color: var(--text-muted);">
        Select a trace on the left to begin error analysis.
      </div>
      <div id="trace-content" style="display: none;"></div>
    </div>
    <div id="margin-pane">
      <div class="pane-title">Failure Notes & Observations</div>
      <div class="annotation-form">
        <input type="text" id="note-taxonomy" placeholder="Failure Mode (e.g. Tone Mismatch, Schema Drift)">
        <textarea id="note-text" placeholder="Observation: What specifically went wrong?"></textarea>
        <button class="btn" onclick="saveAnnotation()">Add Failure Note</button>
      </div>
      <div class="pane-title">Logged Notes For This Trace</div>
      <div id="annotations-list"></div>
    </div>
  </div>
</main>
<script>
let samples = [];
let annotations = [];
let currentSampleIndex = 0;

async function init() {
  const resSamples = await fetch('/api/samples');
  samples = await resSamples.json();
  const resAnn = await fetch('/api/annotations');
  annotations = await resAnn.json();

  document.getElementById('sample-count').textContent = `${samples.length} traces`;
  renderSampleList();
  if (samples.length > 0) {
    selectSample(0);
  }
}

function renderSampleList() {
  const container = document.getElementById('sample-list');
  container.innerHTML = '';
  samples.forEach((s, idx) => {
    const div = document.createElement('div');
    div.className = `sample-item ${idx === currentSampleIndex ? 'active' : ''}`;
    const title = s.title || s.input || s.trace_id || `Trace #${idx + 1}`;
    const annCount = annotations.filter(a => a.trace_id === (s.trace_id || s.id || idx)).length;
    div.innerHTML = `
      <div class="sample-title">${escapeHtml(String(title).slice(0, 40))}</div>
      <div class="sample-meta">
        <span>${s.trace_id || '#' + (idx + 1)}</span>
        <span>${annCount > 0 ? '📝 ' + annCount : ''}</span>
      </div>
    `;
    div.onclick = () => selectSample(idx);
    container.appendChild(div);
  });
}

function selectSample(idx) {
  currentSampleIndex = idx;
  renderSampleList();
  const s = samples[idx];
  if (!s) return;

  document.getElementById('empty-state').style.display = 'none';
  const container = document.getElementById('trace-content');
  container.style.display = 'block';
  container.innerHTML = '';

  const card = document.createElement('div');
  card.className = 'trace-card';

  // Render input/output or messages
  if (Array.isArray(s.messages)) {
    s.messages.forEach(m => {
      card.appendChild(createTurnBubble(m.role || 'message', m.content || JSON.stringify(m)));
    });
  } else {
    if (s.input || s.prompt || s.query) {
      card.appendChild(createTurnBubble('user', s.input || s.prompt || s.query));
    }
    if (s.output || s.response || s.answer || s.completion) {
      card.appendChild(createTurnBubble('assistant', s.output || s.response || s.answer || s.completion));
    }
  }

  // Display raw attributes if available
  const rawMeta = document.createElement('details');
  rawMeta.style.marginTop = '16px';
  rawMeta.style.fontSize = '0.8rem';
  rawMeta.innerHTML = `<summary style="cursor: pointer; color: var(--text-muted);">View Raw Trace JSON</summary><pre style="margin-top: 8px; white-space: pre-wrap; background: #0b1120; padding: 12px; border-radius: 4px;">${escapeHtml(JSON.stringify(s, null, 2))}</pre>`;
  card.appendChild(rawMeta);

  container.appendChild(card);
  renderAnnotations();
}

function createTurnBubble(role, content) {
  const bubble = document.createElement('div');
  bubble.className = `turn-bubble ${role}`;
  const roleName = document.createElement('div');
  roleName.className = 'turn-header';
  roleName.textContent = role;
  const body = document.createElement('div');
  body.className = 'turn-body';
  body.textContent = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
  bubble.appendChild(roleName);
  bubble.appendChild(body);
  return bubble;
}

function renderAnnotations() {
  const s = samples[currentSampleIndex];
  if (!s) return;
  const traceId = s.trace_id || s.id || currentSampleIndex;
  const currentAnn = annotations.filter(a => a.trace_id === traceId);
  const container = document.getElementById('annotations-list');
  container.innerHTML = '';

  if (currentAnn.length === 0) {
    container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem;">No notes logged for this trace yet.</div>';
    return;
  }

  currentAnn.forEach((a, idx) => {
    const card = document.createElement('div');
    card.className = 'annotation-card';
    card.innerHTML = `
      <div class="annotation-tag">${escapeHtml(a.failure_mode || 'Observation')}</div>
      <div style="margin-top: 4px; line-height: 1.4;">${escapeHtml(a.note)}</div>
    `;
    container.appendChild(card);
  });
}

async function saveAnnotation() {
  const s = samples[currentSampleIndex];
  if (!s) return;
  const taxonomyInput = document.getElementById('note-taxonomy');
  const textInput = document.getElementById('note-text');
  const failureMode = taxonomyInput.value.trim();
  const note = textInput.value.trim();
  if (!note) return;

  const traceId = s.trace_id || s.id || currentSampleIndex;
  const entry = {
    trace_id: traceId,
    failure_mode: failureMode || "General Failure",
    note: note,
    created_at: new Date().toISOString()
  };

  annotations.push(entry);
  await fetch('/api/annotations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(annotations)
  });

  textInput.value = '';
  renderAnnotations();
  renderSampleList();
}

function exportData() {
  const blob = new Blob([JSON.stringify(annotations, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'eval_annotations.json';
  a.click();
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

window.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>
"""


class EvalReviewHandler(BaseHTTPRequestHandler):
    data_dir: Path = Path(".evals_review")
    samples_file: Path = Path(".evals_review/samples.json")
    annotations_file: Path = Path(".evals_review/annotations.json")

    def _send_json(self, data: Any, status: int = HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            body = HTML_TEMPLATE.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/api/samples":
            if self.samples_file.exists():
                try:
                    data = json.loads(self.samples_file.read_text(encoding="utf-8"))
                except Exception:
                    data = []
            else:
                data = []
            self._send_json(data)
        elif parsed.path == "/api/annotations":
            if self.annotations_file.exists():
                try:
                    data = json.loads(self.annotations_file.read_text(encoding="utf-8"))
                except Exception:
                    data = []
            else:
                data = []
            self._send_json(data)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8")

        if parsed.path == "/api/annotations":
            try:
                data = json.loads(body)
                self.data_dir.mkdir(parents=True, exist_ok=True)
                self.annotations_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                self._send_json({"status": "saved", "count": len(data)})
            except Exception as e:
                self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
        elif parsed.path == "/api/samples":
            try:
                data = json.loads(body)
                self.data_dir.mkdir(parents=True, exist_ok=True)
                self.samples_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                self._send_json({"status": "saved", "count": len(data)})
            except Exception as e:
                self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)


def run_server(host: str = "127.0.0.1", port: int = 8000, data_dir: Path = Path(".evals_review")):
    data_dir.mkdir(parents=True, exist_ok=True)
    EvalReviewHandler.data_dir = data_dir
    EvalReviewHandler.samples_file = data_dir / "samples.json"
    EvalReviewHandler.annotations_file = data_dir / "annotations.json"

    server = HTTPServer((host, port), EvalReviewHandler)
    print(f"✨ AI Eval Review App live at http://{host}:{port}/")
    print(f"📁 Persisting annotations to: {data_dir.resolve()}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down review server.")
        server.server_close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the local AI Eval Review interface.")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--data-dir", type=Path, default=Path(".evals_review"), help="Data directory (default: .evals_review)")
    parser.add_argument("--samples", type=Path, default=None, help="Initial samples file to load (.json or .jsonl)")

    args = parser.parse_args(argv)

    args.data_dir.mkdir(parents=True, exist_ok=True)
    if args.samples and args.samples.exists():
        # Copy or convert samples into data_dir/samples.json
        from sample_traces import load_traces
        traces = load_traces(args.samples)
        (args.data_dir / "samples.json").write_text(json.dumps(traces, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Loaded {len(traces)} samples from {args.samples}")

    run_server(host=args.host, port=args.port, data_dir=args.data_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
