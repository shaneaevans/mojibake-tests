/**
 * The JavaScript half of the reader bench.
 *
 * Speaks the line protocol in `mojibake_tests/bridge.py`: one request JSON per stdin line, one
 * `@@ENC@@`-prefixed response line per request. The prefix exists because these libraries log:
 * Crawlee writes to stdout and jsdom writes parse errors to the virtual console, and a protocol
 * that shares a channel with library chatter reports the chatter as an answer.
 *
 * `E::text` means the same thing here as everywhere else in this lab: the direct child TEXT NODES
 * of E. cheerio/htmlparser2 call them `type === 'text'`, jsdom calls them `nodeType === 3`.
 */
'use strict';
const readline = require('readline');
const { Readable } = require('stream');

const cheerio = require('cheerio');
const { JSDOM, VirtualConsole } = require('jsdom');
const iconv = require('iconv-lite');
const contentTypeLib = require('content-type');
const mimeTypes = require('mime-types');
const { HttpCrawler } = require('@crawlee/http');
const { readStreamToString, concatStreamToBuffer } = require('@apify/utilities');

const CASE_URL = 'http://127.0.0.1:8765/c/case';   // shape of the real URL serve.py hands out

// Crawlee ships its own cheerio and jsdom (3.18.2: cheerio 1.0.0-rc.12, jsdom 26.1.0), which need
// not be the top-level ones the bare columns pin. A Crawlee column must parse with Crawlee's copy,
// or it measures a crawler nobody runs. `make verify-crawlee` is what caught this.
function crawleeRequire(crawleePkg, dep) {
  return require(require.resolve(dep, { paths: [require.resolve(crawleePkg)] }));
}
const crawleeCheerio = crawleeRequire('@crawlee/cheerio', 'cheerio');
const { JSDOM: CrawleeJSDOM, VirtualConsole: CrawleeVirtualConsole } = crawleeRequire('@crawlee/jsdom', 'jsdom');

// ---------------------------------------------------------------- selector plumbing
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
  // Character-for-character the browser probe in serve.py, so the columns are comparable.
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

// ---------------------------------------------------------------- Crawlee's own path
/**
 * A stand-in for the http.IncomingMessage Crawlee gets from got-scraping: a readable stream
 * carrying the case bytes, plus the `url`/`headers`/`statusCode` its code reads.
 */
function fakeResponse(ctype, buf) {
  const r = Readable.from([buf], { objectMode: false });   // an IncomingMessage is a byte stream
  r.url = CASE_URL;
  r.statusCode = 200;
  r.headers = { 'content-type': ctype || 'text/html' };
  return r;
}

/**
 * Transcribed from `parseContentTypeFromResponse` in @crawlee/http/internals/http-crawler.js,
 * which is module-private and so cannot be imported. `js/crawlee_sweep.js` runs the REAL crawler
 * over the whole corpus to check that this column and an end-to-end CheerioCrawler agree; that
 * run is what licenses the transcription.
 */
function parseContentTypeFromResponse(response) {
  const { url, headers } = response;
  let parsed;
  if (headers['content-type']) {
    try { parsed = contentTypeLib.parse(headers['content-type']); } catch { /* fall through */ }
  }
  if (!parsed) {
    const ext = new URL(url).pathname.split('.').slice(1).pop();
    parsed = contentTypeLib.parse(
      (ext && mimeTypes.contentType(ext)) || 'application/octet-stream; charset=utf-8');
  }
  return { type: parsed.type, charset: parsed.parameters.charset };
}

/** Crawlee's real `_encodeResponse`, called on a stub carrying the two options it consults. */
function crawleeDecode(ctype, buf) {
  const res = fakeResponse(ctype, buf);
  const { charset } = parseContentTypeFromResponse(res);
  const stub = { forceResponseEncoding: undefined, suggestResponseEncoding: undefined };
  return HttpCrawler.prototype._encodeResponse.call(stub, { url: CASE_URL }, res, charset);
}

// ---------------------------------------------------------------- the stacks
const STACKS = {
  /**
   * What `await fetch(url).then((r) => r.text())` gives you, then cheerio's default parser
   * (parse5, a conformant HTML5 parser). The most common shape of JS scraping there is.
   * `Response.text()` is UTF-8 always: the charset parameter is not consulted.
   */
  async 'fetch.text+cheerio'(ctype, buf, sel) {
    const res = new Response(buf, { headers: { 'content-type': ctype || 'text/html' } });
    return fromCheerio(cheerio.load(await res.text()), sel);
  },

  /**
   * CheerioCrawler: Crawlee resolves the encoding from the HTTP header alone (iconv-lite for
   * anything Node cannot decode natively, hard utf-8 fallback when the header is silent), then
   * cheerio with `_useHtmlParser2` forced on the way the crawler sets it.
   */
  async 'crawlee(cheerio)'(ctype, buf, sel) {
    const { response, encoding } = crawleeDecode(ctype, buf);
    const body = await readStreamToString(response, encoding);
    return fromCheerio(crawleeCheerio.load(body, { xmlMode: false, _useHtmlParser2: true }), sel);
  },

  /**
   * JSDOMCrawler: the same header-only resolution, but the (possibly already transcoded) BYTES
   * go to jsdom with `contentType: 'text/html'` — no charset — so jsdom sniffs them again.
   */
  async 'crawlee(jsdom)'(ctype, buf, sel) {
    const { response } = crawleeDecode(ctype, buf);
    const body = await concatStreamToBuffer(response);
    const dom = new CrawleeJSDOM(body, {
      url: CASE_URL, contentType: 'text/html', virtualConsole: new CrawleeVirtualConsole(),
    });
    return fromDom(dom.window.document, sel);
  },

  /**
   * jsdom handed the raw bytes plus the real Content-Type. jsdom runs html-encoding-sniffer,
   * which is the WHATWG prescan — BOM, then transport layer, then <meta> — so this is the JS
   * reader with the best claim to matching what the browser resolved.
   */
  async 'jsdom(bytes)'(ctype, buf, sel) {
    const dom = new JSDOM(buf, {
      url: CASE_URL, contentType: ctype || 'text/html', virtualConsole: new VirtualConsole(),
    });
    return fromDom(dom.window.document, sel);
  },
};

// ---------------------------------------------------------------- the line protocol
async function handle(req) {
  try {
    if (req.op === 'stacks') return { id: req.id, stacks: Object.keys(STACKS) };
    const fn = STACKS[req.stack];
    if (!fn) throw new Error('no such stack: ' + req.stack);
    return { id: req.id, values: await fn(req.ctype, Buffer.from(req.body, 'base64'), req.sel) };
  } catch (e) {
    const kind = (e && e.constructor && e.constructor.name) || 'Error';
    return { id: req.id, error: kind + ': ' + (e && e.message) };
  }
}

// One request at a time, and every reply carries the id back. The handlers are async, so a
// fire-and-forget listener answers in COMPLETION order — which silently permutes the columns of
// a sweep and is exactly the kind of bug this lab is built to catch in other people's code.
let chain = Promise.resolve();
const rl = readline.createInterface({ input: process.stdin });
rl.on('line', (line) => {
  line = line.trim();
  if (!line) return;
  chain = chain.then(async () => {
    let reply;
    try {
      reply = await handle(JSON.parse(line));
    } catch (e) {
      reply = { error: 'ProtocolError: ' + (e && e.message) };
    }
    process.stdout.write('@@ENC@@' + JSON.stringify(reply) + '\n');
  });
});
