/**
 * Run a REAL CheerioCrawler and a REAL JSDOMCrawler over the live case server.
 *
 * The `crawlee(...)` columns of the bench call Crawlee's own `_encodeResponse` but reach it through
 * a transcription of `parseContentTypeFromResponse`, which is module-private (see reader.js). A
 * transcription is an assertion until something measures it, so this is the measurement: the same
 * corpus, fetched over real HTTP by the real crawler class, with the real got-scraping response.
 * `mojibake_tests/verify_crawlee.py` diffs the two and fails loudly on any case that differs.
 *
 *   node js/crawlee_sweep.js <base-url> <out.json>     # case list as JSON on stdin
 *
 * Output goes to a file because Crawlee logs to stdout.
 */
'use strict';
const fs = require('fs');
const { CheerioCrawler, JSDOMCrawler, RequestQueue, Configuration, log, LogLevel } =
  require('crawlee');

const [baseUrl, outPath] = process.argv.slice(2);
log.setLevel(LogLevel.OFF);
Configuration.getGlobalConfig().set('persistStorage', false);

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

function fromDom(doc, sel) {
  const { base, kind, attr } = splitPseudo(sel);
  const out = [];
  for (const el of doc.querySelectorAll(base)) {
    if (kind === 'attr') {
      if (el.hasAttribute(attr)) out.push(el.getAttribute(attr));
    } else {
      for (const n of el.childNodes) if (n.nodeType === 3) out.push(n.data);
    }
  }
  return out;
}

async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

(async () => {
  const cases = await readStdin();          // [{id, sel}, ...]
  const bySel = Object.fromEntries(cases.map((c) => [`${baseUrl}/c/${c.id}`, c]));
  const results = {};

  // A crawler that gives up on the first failure and RECORDS it: Crawlee throwing on a charset it
  // cannot decode is an answer about Crawlee, not a hole in the sweep.
  const common = (extract) => ({
    maxRequestRetries: 0,
    maxConcurrency: 4,
    requestHandler: async (ctx) => {
      const c = bySel[ctx.request.url];
      try {
        results[c.id] = { values: extract(ctx, c.sel) };
      } catch (e) {
        results[c.id] = { error: `${e.constructor.name}: ${e.message}` };
      }
    },
    failedRequestHandler: ({ request }, e) => {
      results[bySel[request.url].id] = { error: `${e.constructor.name}: ${e.message}` };
    },
  });

  const urls = cases.map((c) => `${baseUrl}/c/${c.id}`);
  const out = {};

  // A queue of its own per crawler. Sharing the default one means the second crawler finds every
  // URL already handled and sweeps NOTHING — a zero-coverage run that looks like a clean pass.
  const sweep = async (label, Crawler, extract) => {
    for (const k of Object.keys(results)) delete results[k];
    const requestQueue = await RequestQueue.open(label);
    await new Crawler({ ...common(extract), requestQueue }).run(urls);
    await requestQueue.drop();
    out[label] = { ...results };
  };

  await sweep('crawlee(cheerio)', CheerioCrawler, ({ $ }, sel) => fromCheerio($, sel));
  await sweep('crawlee(jsdom)', JSDOMCrawler, ({ window }, sel) => fromDom(window.document, sel));

  fs.writeFileSync(outPath, JSON.stringify(out, null, 1));
})();
