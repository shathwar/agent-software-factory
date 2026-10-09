import { describe, expect, test } from 'bun:test';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHandler } from '../skills/evals/scripts/serve_review_app';

test('review app serves traces and persists annotations', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'review-app-'));
  const handler = createHandler({ dataDir: dir, samples: join(dir, 'samples.json'), annotations: join(dir, 'annotations.json') });
  expect((await handler(new Request('http://localhost/api/samples'))).status).toBe(200);
  const response = await handler(new Request('http://localhost/api/annotations', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify([{ trace_id: 'a', note: 'bad output' }]) }));
    expect(await response.json()).toEqual({ status: 'saved', count: 1 });
    expect(JSON.parse(await readFile(join(dir, 'annotations.json'), 'utf8'))[0].note).toBe('bad output');
  expect((await handler(new Request('http://localhost/missing'))).status).toBe(404);
});
