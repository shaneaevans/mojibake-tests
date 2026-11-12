"""Serve each crafted case at /c/<id> with its EXACT bytes and EXACT Content-Type, plus a
harness page that loads every `nav="iframe"` case in a same-origin iframe and reports what Chrome
actually did. `/?all` loads every case, which only `make audit-nav` has a use for.

A save MERGES into results/browser.json: it never replaces a top-level cell (an iframe answer for a
fallback-dependent case is wrong by construction), and every cell it writes carries the fingerprint
of the bytes it was measured on.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mojibake_tests.cases import CASES, fingerprint  # noqa: E402

BY_ID = {c["id"]: c for c in CASES}
BROWSER_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "results", "browser.json")
# Overridable so a verification sweep can serve the corpus on its own port without colliding with
# whatever `make serve` is already holding.
PORT = int(os.environ.get("MOJIBAKE_TESTS_PORT", 8765))

# The one probe both capture paths run: the iframe harness below and the top-level capture in
# capture.py. parsel's `E::text` == direct child text nodes; `E::attr(a)` == that attribute.
PROBE = """function probe(doc, sel) {
  const m = sel.match(/^(.*?)(::text|::attr\\((.+)\\))$/);
  const base = (m ? m[1] : sel).trim() || '*';
  const attrName = m && m[3];
  let els;
  try { els = [...doc.querySelectorAll(base)]; } catch (e) { return ['ERR:' + e.message]; }
  const out = [];
  for (const el of els) {
    if (attrName) { if (el.hasAttribute(attrName)) out.push(el.getAttribute(attrName)); }
    else { for (const n of el.childNodes) if (n.nodeType === 3) out.push(n.data); }
  }
  return out;
}
function record(doc, sel) {
  return {
    charset: doc.characterSet,
    values: probe(doc, sel),
    bodyText: (doc.body ? doc.body.textContent : '').slice(0, 120),
    title: (doc.title || '').slice(0, 60),
    nElems: doc.getElementsByTagName('*').length,
    ua: navigator.userAgent,
    lang: navigator.language,
    locale: Intl.DateTimeFormat().resolvedOptions().locale
  };
}"""

HARNESS = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>encdiv</title></head>
<body><h1>encdiv harness</h1><div id="out">loading...</div>
<script>
const CASES = %s;
""" + PROBE + """
(async () => {
  const res = {};
  for (const c of CASES) {
    const f = document.createElement('iframe');
    f.style.cssText = 'width:200px;height:60px';
    f.src = '/c/' + c.id;
    document.body.appendChild(f);
    await new Promise(r => { f.onload = r; f.onerror = r; setTimeout(r, 3000); });
    let d = null;
    try { d = f.contentDocument; } catch (e) {}
    if (!d) { res[c.id] = {err: 'no contentDocument'}; continue; }
    res[c.id] = Object.assign(record(d, c.sel), {nav: 'iframe'});
  }
  window.__RESULT = res;
  await fetch('/save', {method: 'POST', body: JSON.stringify(res)});
  document.getElementById('out').textContent = 'DONE ' + Object.keys(res).length;
})();
</script></body></html>"""


def merge_cells(cells):
    """Write captured cells into results/browser.json, stamped with what they were measured on.
    An iframe answer never replaces a top-level one."""
    try:
        with open(BROWSER_JSON, encoding="utf-8") as f:
            stored = json.load(f)
    except FileNotFoundError:
        stored = {}
    kept = []
    for cid, cell in cells.items():
        if cid not in BY_ID:
            continue
        if cell.get("nav") != "top-level" and stored.get(cid, {}).get("nav") == "top-level":
            kept.append(cid)
            continue
        stored[cid] = dict(cell, sha=fingerprint(BY_ID[cid]))
    # One case per line, so a recapture diffs as the cells it changed.
    with open(BROWSER_JSON, "w", encoding="utf-8") as f:
        f.write("{\n" + ",\n".join("%s: %s" % (json.dumps(k), json.dumps(v, ensure_ascii=False))
                                    for k, v in stored.items()) + "\n}\n")
    return kept


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    cases = BY_ID     # what /c/<id> serves; capture.py adds pages of its own

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        kept = merge_cells(json.loads(self.rfile.read(n)))
        if kept:
            print("kept the top-level cells for: " + ", ".join(kept), file=sys.stderr)
        return self._send(b"saved", "text/plain")

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/":
            load = [c for c in CASES if query == "all" or c["nav"] == "iframe"]
            payload = json.dumps([{"id": c["id"], "sel": c["sel"]} for c in load])
            body = (HARNESS % payload).encode("utf-8")
            return self._send(body, "text/html; charset=utf-8")
        if path.startswith("/c/"):
            c = self.cases.get(path[3:])
            if not c:
                return self._send(b"no such case", "text/plain", 404)
            # No charset in the header unless the case declares one: that is the whole point.
            return self._send(c["body"], c["ctype"] or "text/html")
        return self._send(b"?", "text/plain", 404)

    def _send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
