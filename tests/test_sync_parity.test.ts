import { expect, test } from 'bun:test';
import { checkParity, getFileMappings } from '../scripts/verify/sync_parity';

test('sync parity maps and validates the repository distributions', async () => {
  const root = process.cwd();
  const mappings = await getFileMappings(root);
  expect(mappings.length).toBeGreaterThan(20);
  const [passed, errors] = await checkParity(root);
  expect(passed).toBe(true);
  expect(errors).toEqual([]);
});
