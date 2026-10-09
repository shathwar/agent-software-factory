#!/usr/bin/env bun
/** Zero-dependency local annotation and trace review server. */
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';

export const HTML = `<!doctype html><html><head><meta charset="utf-8"><title>AI Eval Trace Review</title><style>body{font:16px system-ui;margin:2rem;max-width:1000px}main{display:grid;grid-template-columns:240px 1fr;gap:2rem}button{margin:.25rem;padding:.5rem}textarea,input{display:block;width:100%;margin:.5rem 0;padding:.5rem}pre{white-space:pre-wrap}</style></head><body><h1>AI Eval Trace Review</h1><main><aside><h2>Traces</h2><div id="samples"></div></aside><section><pre id="trace">Select a trace.</pre><input id="mode" placeholder="Failure mode"><textarea id="note" placeholder="Observation"></textarea><button onclick="save()">Add failure note</button><h2>Notes</h2><pre id="notes"></pre></section></main><script>let s=[],a=[],i=0;async function init(){s=await fetch('/api/samples').then(r=>r.json());a=await fetch('/api/annotations').then(r=>r.json());render()}function render(){samples.innerHTML=s.map((x,n)=>'<button onclick="select('+n+')">'+(x.title||x.trace_id||'Trace '+(n+1))+'</button>').join('');select(i)}function select(n){i=n;trace.textContent=JSON.stringify(s[n]||{},null,2);notes.textContent=JSON.stringify(a.filter(x=>x.trace_id===(s[n]?.trace_id??s[n]?.id??n)),null,2)}async function save(){if(!s[i]||!note.value.trim())return;a.push({trace_id:s[i].trace_id??s[i].id??i,failure_mode:mode.value.trim()||'General Failure',note:note.value.trim(),created_at:new Date().toISOString()});await fetch('/api/annotations',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(a)});note.value='';render()}init()</script></body></html>`;

type ReviewState = { dataDir: string; samples: string; annotations: string };
const json = (value: unknown, init: ResponseInit = {}) => Response.json(value, { ...init, headers: { 'content-type': 'application/json; charset=utf-8', ...(init.headers || {}) } });
async function load(path: string): Promise<unknown[]> { try { const value = JSON.parse(await readFile(path, 'utf8')); return Array.isArray(value) ? value : []; } catch { return []; } }
export function createServer(state: ReviewState, port = 8000) {
  return Bun.serve({
    port,
    fetch: createHandler(state),
  });
}
export function createHandler(state: ReviewState) {
  return async (req: Request) => {
      const url = new URL(req.url);
      if (req.method === 'GET' && (url.pathname === '/' || url.pathname === '/index.html')) return new Response(HTML, { headers: { 'content-type': 'text/html; charset=utf-8' } });
      if (req.method === 'GET' && url.pathname === '/api/samples') return json(await load(state.samples));
      if (req.method === 'GET' && url.pathname === '/api/annotations') return json(await load(state.annotations));
      if (req.method === 'POST' && (url.pathname === '/api/samples' || url.pathname === '/api/annotations')) {
        try { const value = await req.json(); if (!Array.isArray(value)) return json({ error: 'Expected an array' }, { status: 400 }); await mkdir(state.dataDir, { recursive: true }); const path = url.pathname.endsWith('samples') ? state.samples : state.annotations; await writeFile(path, JSON.stringify(value, null, 2)); return json({ status: 'saved', count: value.length }); } catch (error) { return json({ error: String(error) }, { status: 400 }); }
      }
      return new Response('Not found', { status: 404 });
    };
}

if (import.meta.main) {
  const args = Bun.argv.slice(2); const value = (flag: string, fallback: string) => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] || fallback : fallback; };
  const dataDir = value('--data-dir', '.evals_review'); const samplesFile = join(dataDir, 'samples.json'); const annotationsFile = join(dataDir, 'annotations.json');
  const input = value('--samples', ''); if (input) { const parsed = input.endsWith('.jsonl') ? (await readFile(input, 'utf8')).split('\n').filter(Boolean).map((line) => JSON.parse(line)) : JSON.parse(await readFile(input, 'utf8')); await mkdir(dataDir, { recursive: true }); await writeFile(samplesFile, JSON.stringify(parsed, null, 2)); console.log(`Loaded ${parsed.length} samples from ${input}`); }
  const server = createServer({ dataDir, samples: samplesFile, annotations: annotationsFile }, Number(value('--port', '8000'))); console.log(`AI Eval Review App live at http://127.0.0.1:${server.port}/`); console.log(`Persisting annotations to: ${resolve(dataDir)}`);
}
