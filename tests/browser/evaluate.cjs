/* Real browser observations against a bounded fixture contract, with negative controls.
 * Screenshots are evidence; measured layout/contrast/interaction assertions are the gate.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const crypto = require('node:crypto');

const STATES = ['empty', 'loading', 'populated', 'partial', 'error', 'unavailable'];
const EXPECTED_FAILURE = { 'missing-error': 'state:error', keyboard: 'keyboard-recovery',
  contrast: 'contrast', overflow: 'mobile-layout', focus: 'visible-focus' };

function luminance(rgb) {
  return rgb.map(n => n / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
    .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
}
function contrast(foreground, background) {
  const a = luminance(foreground), b = luminance(background);
  return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
}

async function evaluate(browser, fixture, directory, mutation = '') {
  const context = await browser.newContext({ viewport: {width: 390, height: 844}, reducedMotion: 'reduce' });
  // Fixtures are fully local. Block any accidental network access.
  await context.route(/^https?:/, route => route.abort());
  await context.tracing.start({ screenshots: true, snapshots: true });
  const page = await context.newPage();
  const checks = [];
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = async (id, action) => {
    try { await action(); checks.push({id, passed: true}); }
    catch (error) { checks.push({id, passed: false, error: error.message}); }
  };
  const go = async state => {
    const url = pathToFileURL(fixture);
    url.searchParams.set('state', state);
    if (mutation) url.searchParams.set('mutation', mutation);
    await page.goto(url.href);
  };
  try {
    await fs.mkdir(directory, {recursive: true});
    for (const state of STATES) {
      await go(state);
      await check(`state:${state}`, async () => {
        assert.equal(await page.locator('body').getAttribute('data-state'), state);
        assert(await page.locator('#message').isVisible());
        assert((await page.locator('#message').innerText()).trim().length > 5);
        assert.equal(await page.locator('#action').isDisabled(), ['loading', 'unavailable'].includes(state));
        assert.equal(await page.locator('#action').getAttribute('aria-busy'), String(state === 'loading'));
        assert.equal(await page.locator('#items').isVisible(), ['populated', 'partial'].includes(state));
        if (state === 'partial') assert.match(await page.locator('#message').innerText(), /2 of 10.*stale/i);
        if (state === 'error') assert.equal(await page.locator('#message').getAttribute('role'), 'alert');
        if (state === 'unavailable') assert.match(await page.locator('#message').innerText(), /access.*administrator/i);
      });
      await page.screenshot({path: path.join(directory, `${state}.png`), fullPage: true, animations: 'disabled'});
    }
    await go('error');
    await check('keyboard-recovery', async () => {
      await page.keyboard.press('Tab');
      assert.equal(await page.locator('#filter').evaluate(el => el === document.activeElement), true);
      await page.keyboard.press('Tab');
      assert.equal(await page.locator('#action').evaluate(el => el === document.activeElement), true);
      await page.keyboard.press('Enter');
      await page.waitForFunction(() => document.body.dataset.state === 'populated', null, {timeout: 2000});
      assert.equal(await page.locator('#filter').inputValue(), 'Saved query');
    });
    await go('empty');
    await check('accessible-names', async () => {
      assert.equal(await page.getByRole('textbox', {name: 'Filter projects', exact: true}).count(), 1);
      assert.equal(await page.getByRole('button', {name: 'Create project', exact: true}).count(), 1);
    });
    await page.keyboard.press('Tab');
    await check('visible-focus', async () => {
      const outline = await page.locator('#filter').evaluate(el => ({
        width: parseFloat(getComputedStyle(el).outlineWidth), style: getComputedStyle(el).outlineStyle
      }));
      assert(outline.width >= 2 && outline.style !== 'none');
    });
    await check('contrast', async () => {
      const colors = await page.locator('#message').evaluate(el => ({
        foreground: getComputedStyle(el).color.match(/\d+(?:\.\d+)?/g).slice(0, 3).map(Number),
        background: getComputedStyle(document.body).backgroundColor.match(/\d+(?:\.\d+)?/g).slice(0, 3).map(Number)
      }));
      assert(contrast(colors.foreground, colors.background) >= 4.5);
    });
    await check('control-hover-and-pressed', async () => {
      const button = page.locator('#action');
      const normal = await button.evaluate(el => getComputedStyle(el).backgroundColor);
      await button.hover();
      assert.notEqual(await button.evaluate(el => getComputedStyle(el).backgroundColor), normal);
      await page.mouse.down();
      try { assert.notEqual(await button.evaluate(el => getComputedStyle(el).transform), 'none'); }
      finally { await page.mouse.up(); }
    });
    await check('mobile-layout', async () => {
      const layout = await page.evaluate(() => ({
        width: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth,
        panel: document.getElementById('panel').getBoundingClientRect().toJSON(),
        button: document.getElementById('action').getBoundingClientRect().toJSON()
      }));
      assert(layout.scrollWidth <= layout.width);
      assert(layout.panel.x >= 16 && layout.panel.right <= layout.width - 16);
      assert(layout.button.height >= 44 && layout.button.width >= 44);
    });
    await check('desktop-layout', async () => {
      await page.setViewportSize({width: 1280, height: 900});
      const box = await page.locator('main').boundingBox();
      assert(box.width <= 640 && box.x >= 0);
    });
    await check('runtime-errors', async () => assert.deepEqual(errors, []));
  } finally {
    await context.tracing.stop({path: path.join(directory, 'trace.zip')});
    await context.close();
  }
  return {mutation: mutation || 'reference', status: checks.every(c => c.passed) ? 'passed' : 'failed', checks};
}

async function main() {
  const argv = process.argv.slice(2);
  const arg = name => { const i = argv.indexOf(name); return i < 0 ? null : argv[i + 1]; };
  const fixture = path.resolve(arg('--fixture') || path.join(__dirname, 'fixture.html'));
  const output = path.resolve(arg('--output') || path.join(__dirname, 'artifacts'));
  const external = Boolean(arg('--fixture'));
  let browser;
  let report;
  try {
    browser = await chromium.launch({headless: true, ...(process.env.UX_BROWSER_CHANNEL ? {channel: process.env.UX_BROWSER_CHANNEL} : {})});
    const results = [];
    for (const mutation of external ? [''] : ['', ...Object.keys(EXPECTED_FAILURE)]) {
      results.push(await evaluate(browser, fixture, path.join(output, mutation || 'reference'), mutation));
    }
    const calibrated = external || results.slice(1).every(r => r.checks.some(c => c.id === EXPECTED_FAILURE[r.mutation] && !c.passed));
    report = {schema_version: 1, status: results[0].status === 'passed' && calibrated ? 'passed' : 'failed',
      measurement_kind: 'rendered_browser', fixture_sha256: crypto.createHash('sha256').update(await fs.readFile(fixture)).digest('hex'),
      browser: browser.version(), playwright: require('playwright/package.json').version,
      negative_controls: external ? 'unrun' : (calibrated ? 'passed' : 'failed'), results,
      limitations: ['Bounded fixture contract; not a general accessibility audit or agent evaluation.',
        'Screenshots are retained evidence; visual gates measure layout, focus and opaque text contrast, not pixel similarity.']};
  } catch (error) {
    report = {schema_version: 1, status: 'inconclusive', error: error.message, results: []};
  } finally {
    if (browser) await browser.close();
  }
  await fs.mkdir(output, {recursive: true});
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({status: report.status, report: path.join(output, 'report.json')}));
  process.exitCode = report.status === 'passed' ? 0 : 1;
}

if (require.main === module) main().catch(error => {console.error(error); process.exitCode = 1;});
module.exports = {evaluate, contrast};
