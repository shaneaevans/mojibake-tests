/**
 * The JavaScript browser stacks, over the live case server: each one navigates top-level to every
 * case in a real browser and answers the selector.
 *
 *   puppeteer                       page.evaluate(probe), Puppeteer's own Chrome for Testing
 *   crawlee(playwright)             PlaywrightCrawler, page.evaluate(probe) in the request handler
 *   crawlee(playwright+cheerio)     the same crawl, but `await parseWithCheerio()`: page.content()
 *                                   serialised and re-parsed by cheerio, as Crawlee's docs show
 *
 * The in-page probe is serve.PROBE, the one the Chrome reference column runs, so an in-page column
 * measures the engine and nothing else.
 *
 *   node js/browser_sweep.js <base-url> <out.json>    # {"probe": ..., "cases": [{id, sel}]} on stdin
 *
 * Output goes to a file because Crawlee logs to stdout.
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

const [baseUrl, outPath] = process.argv.slice(2);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const CASES = input.cases;
// A function expression the page evaluates with the selector as its argument.
const PROBE_FN = `(sel) => { ${input.probe}\n return probe(document, sel); }`;

function splitPseudo(sel) {
  const m = sel.match(/^(.*?)(?:::text|::attr\((.+)\))$/);
  if (!m) return { base: sel.trim() || '*', kind: 'text', attr: null };
  return { base: m[1].trim() || '*', kind: m[2] ? 'attr' : 'text', attr: m[2] || null };
}

function fromCheerio($, sel) {
  const { base, kind, attr } = splitPseudo(sel);
  const out = [];
  $(base).each((_, el) => {
    if (kind === 'attr') {
      const v = $(el).attr(attr);
      if (v !== undefined) out.push(v);
    } else {
      for (const c of el.children || []) if (c.type === 'text') out.push(c.data);
    }
  });
  return out;
}

const err = (e) => ['ERR:' + String((e && e.message) || e).split('\n')[0].slice(0, 90)];

async function puppeteerSweep() {
  const puppeteer = require('puppeteer');
  const browser = await puppeteer.launch({ headless: true });
  const cells = {};
  try {
    for (const c of CASES) {
      const page = await browser.newPage();
      try {
        await page.goto(`${baseUrl}/c/${c.id}`, { waitUntil: 'load', timeout: 30000 });
        cells[c.id] = await page.evaluate(`(${PROBE_FN})(${JSON.stringify(c.sel)})`);
      } catch (e) { cells[c.id] = err(e); }
      await page.close();
    }
    return {
      versions: `puppeteer ${require('puppeteer/package.json').version}`,
      engine: await browser.version(),
      cells,
    };
  } finally { await browser.close(); }
}

async function crawleePlaywrightSweep() {
  process.env.CRAWLEE_STORAGE_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'crawlee-browser-'));
  const { PlaywrightCrawler, RequestQueue, Configuration, log, LogLevel } = require('crawlee');
  log.setLevel(LogLevel.OFF);
  Configuration.getGlobalConfig().set('persistStorage', false);
  const inPage = {}, viaCheerio = {};
  let engine = null;
  const bySel = new Map(CASES.map((c) => [`${baseUrl}/c/${c.id}`, c]));
  // A queue of its own: a shared default queue is how a sweep ends up sweeping nothing.
  const requestQueue = await RequestQueue.open(`browser-sweep-${Date.now()}`);
  const crawler = new PlaywrightCrawler({
    requestQueue,
    maxConcurrency: 4,
    maxRequestRetries: 0,
    requestHandlerTimeoutSecs: 60,
    headless: true,
    async requestHandler({ request, page, parseWithCheerio }) {
      const c = bySel.get(request.url);
      engine = engine || page.context().browser().version();
      try { inPage[c.id] = await page.evaluate(`(${PROBE_FN})(${JSON.stringify(c.sel)})`); }
      catch (e) { inPage[c.id] = err(e); }
      try { viaCheerio[c.id] = fromCheerio(await parseWithCheerio(), c.sel); }
      catch (e) { viaCheerio[c.id] = err(e); }
    },
    failedRequestHandler({ request }, e) {
      const c = bySel.get(request.url);
      inPage[c.id] = err(e);
      viaCheerio[c.id] = err(e);
    },
  });
  await crawler.run([...bySel.keys()]);
  const v = `Crawlee ${require('crawlee/package.json').version} + playwright ${require('playwright/package.json').version}`;
  return {
    'crawlee(playwright)': { versions: v, engine, cells: inPage },
    'crawlee(playwright+cheerio)': { versions: v, engine, cells: viaCheerio },
  };
}

(async () => {
  const out = {};
  try { out.puppeteer = await puppeteerSweep(); } catch (e) { out.puppeteer = { error: String(e) }; }
  try { Object.assign(out, await crawleePlaywrightSweep()); }
  catch (e) { out['crawlee(playwright)'] = { error: String(e) }; }
  fs.writeFileSync(outPath, JSON.stringify(out));
  process.exit(0);
})();
