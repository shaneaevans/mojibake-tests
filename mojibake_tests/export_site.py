"""`python -m mojibake_tests.export_site <site-dir>` writes the public corpus for mojibake.wtf to
`<site-dir>/data/cases.json`.

The site serves these bytes, and only these. Each entry carries the case's exact body (base64),
the exact Content-Type the lab serves it with, its fingerprint, and the browser cell, which is
included only when it was measured on these bytes. `make verify-live` then fetches every case from
the deployed site and checks it against `cases.py` itself, not against this file, so a bug here
shows up as a mismatch.
"""
import base64
import importlib.metadata as md
import json
import os
import re
import subprocess
import sys

from mojibake_tests.cases import CASES, fingerprint
from mojibake_tests.readers import READERS
from mojibake_tests.report import ROOT, load_browser

# Readers the site folds into another row because they return the same values on every public case.
# The export checks that, and fails rather than fold two stacks that disagree.
SAME_AS = {"scrapy+frostwork": "scrapy", "web-poet+frostwork": "scrapy"}

# Stacks measured by pinned_sweep.py that the site shows: older Scrapy, and the unreleased Frostwork.
EXPORT_PINNED = ["scrapy+w3lib-2.4.1", "scrapy-2.19.0", "frostwork-checkout"]

BROWSER_LANG = {"puppeteer": "JavaScript", "crawlee(playwright)": "JavaScript",
                "crawlee(playwright+cheerio)": "JavaScript"}
BROWSER_LABEL = {
    "playwright(chromium)": "Playwright {v}, Chromium",
    "playwright(firefox)": "Playwright {v}, Firefox",
    "playwright(webkit)": "Playwright {v}, WebKit",
    "crawlee.py(playwright)": "Crawlee for Python {v}, PlaywrightCrawler",
    "selenium(chrome)": "Selenium {v}, Chrome",
    "selenium(chrome)+bs4": "Selenium {v}, Chrome, page_source into Beautiful Soup",
    "scrapy-playwright": "{v}",
    "puppeteer": "Puppeteer {v}",
    "crawlee(playwright)": "Crawlee {v}, PlaywrightCrawler",
    "crawlee(playwright+cheerio)": "Crawlee {v}, PlaywrightCrawler + parseWithCheerio()",
}


def _py(pkg):
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return "?"


def _js(pkg):
    try:
        with open(os.path.join(ROOT, "js", "node_modules", pkg, "package.json")) as f:
            return json.load(f)["version"]
    except OSError:
        return "?"


def _jar(name):
    for f in os.listdir(os.path.join(ROOT, "java", "lib")):
        m = re.match(r"%s-([\d.]+)\.jar$" % name, f)
        if m:
            return m.group(1)
    return "?"


def _frostwork():
    """The build the bench imports, named by its git position when it is a checkout."""
    try:
        import frostwork
    except ImportError:
        return "?"
    here = os.path.dirname(frostwork.__file__)
    desc = _cmd_version(["git", "-C", here, "describe", "--tags"], r"(\S+)")
    m = re.match(r"([\d.]+)-(\d+)-g([0-9a-f]+)$", desc)
    if m:
        return "Frostwork main at %s (unreleased)" % m.group(3)
    return "Frostwork %s" % _py("frostwork")


def _cmd_version(cmd, pattern):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        m = re.search(pattern, out.stdout + out.stderr)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def stacks():
    """Each public reader as the site names it: a label with versions, its language, and what it
    does. Versions are read from what is installed, never typed in."""
    import lxml.etree
    libxml2 = ".".join(map(str, lxml.etree.LIBXML_VERSION))
    node = _cmd_version(["node", "--version"], r"v([\d.]+)")
    jdk = _cmd_version(["java", "-version"], r'version "([\d.]+)')
    v = {p: _py(p) for p in ("scrapy", "w3lib", "parsel", "lxml", "requests", "beautifulsoup4",
                             "charset-normalizer", "crawlee", "html5lib", "selectolax", "web-poet",
                             "frostwork")}
    js = {p: _js(p) for p in ("cheerio", "jsdom", "crawlee")}
    jsoup = _jar("jsoup")
    py = "Python"
    table = {
        "scrapy": (py, "Scrapy %s" % v["scrapy"],
                   "HtmlResponse(...).css() on parsel %s, the encoding from w3lib %s, which asks "
                   "Frostwork %s. Page.extract_response() on Frostwork %s and web-poet %s "
                   "declarations return the same values on every case"
                   % (v["parsel"], v["w3lib"], v["frostwork"], v["frostwork"], v["web-poet"])),
        "scrapy+frostwork": (py, "Scrapy %s on Frostwork %s" % (v["scrapy"], v["frostwork"]),
                             "Page.extract_response(HtmlResponse(...))"),
        "web-poet+frostwork": (py, "web-poet %s on Frostwork %s" % (v["web-poet"], v["frostwork"]),
                               "a css_getall() declaration on a WebPage"),
        "scrapy(w3lib+parsel)": (py, "w3lib %s + parsel %s" % (v["w3lib"], v["parsel"]),
                                 "html_to_unicode(default_encoding=\"utf-8\"), the deprecated path, then Selector(text=)"),
        "parsel(body=)": (py, "parsel %s" % v["parsel"], "Selector(body=, encoding=<HTTP charset>)"),
        "requests.text+lxml": (py, "requests %s + lxml %s" % (v["requests"], v["lxml"]),
                               "response.text into lxml.html"),
        "requests.text+parsel": (py, "requests %s + parsel %s" % (v["requests"], v["parsel"]),
                                 "response.text into Selector(text=)"),
        "requests.text+bs4": (py, "requests %s + Beautiful Soup %s" % (v["requests"], v["beautifulsoup4"]),
                              "response.text into BeautifulSoup(..., \"html.parser\")"),
        "requests+apparent": (py, "requests %s + charset-normalizer %s" % (v["requests"], v["charset-normalizer"]),
                              "response.apparent_encoding forced on"),
        "crawlee.py(bs4)": (py, "Crawlee for Python %s, BeautifulSoupCrawler" % v["crawlee"], "raw bytes to BeautifulSoup(features=\"lxml\")"),
        "crawlee.py(parsel)": (py, "Crawlee for Python %s, ParselCrawler" % v["crawlee"], "Selector(body=) with no encoding"),
        "lxml(bytes)": (py, "lxml %s (libxml2 %s)" % (v["lxml"], libxml2), "lxml.html on the raw bytes"),
        "html5lib": (py, "html5lib %s" % v["html5lib"], "the WHATWG prescan over the raw bytes"),
        "bs4+dammit": (py, "Beautiful Soup %s + UnicodeDammit" % v["beautifulsoup4"], "BeautifulSoup(bytes, \"html.parser\", from_encoding=<HTTP charset>), UnicodeDammit sniffing the rest"),
        "selectolax(lexbor)": (py, "selectolax %s (lexbor)" % v["selectolax"], "the lexbor HTML5 parser on the raw bytes"),
        "fetch.text+cheerio": ("JavaScript", "fetch + cheerio %s (Node %s)" % (js["cheerio"], node), "await res.text() into cheerio.load"),
        "crawlee(cheerio)": ("JavaScript", "Crawlee %s, CheerioCrawler" % js["crawlee"], "Crawlee's own header-only charset rule"),
        "crawlee(jsdom)": ("JavaScript", "Crawlee %s, JSDOMCrawler" % js["crawlee"], "Crawlee's charset rule, then jsdom"),
        "jsdom(bytes)": ("JavaScript", "jsdom %s" % js["jsdom"], "new JSDOM(bytes, {contentType})"),
        "jsoup(bytes)": ("Java", "jsoup %s" % jsoup, "Jsoup.parse(bytes) with no charset"),
        "jsoup(http-charset)": ("Java", "jsoup %s with the HTTP charset" % jsoup, "Jsoup.parse(bytes, <HTTP charset>)"),
        "jdk-http.ofString+jsoup": ("Java", "java.net.http + jsoup %s (JDK %s)" % (jsoup, jdk), "BodyHandlers.ofString() into Jsoup.parse"),
        "regex scraper": (py, "a regular expression", "the HTTP charset or UTF-8, then one regular expression per selector"),
        "frostwork": (py, _frostwork(), "frostwork.extract(), one streaming pass over the bytes"),
    }
    out = []
    for name, fn in READERS:
        if name in SAME_AS:
            continue
        lang, label, how = table.get(name, ("?", name, fn.note))
        out.append({"id": name, "language": lang, "label": label, "how": how, "kind": "http"})
    return out


def _load(name):
    path = os.path.join(ROOT, "results", name)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extra_stacks(cases):
    """The browser-driven stacks and the pinned old versions, as (stack, {case id: values}).

    A stack is exported only if every public case has a cell measured on its current bytes:
    a column with gaps would be graded over the cases that happened to survive."""
    fps = {c["id"]: fingerprint(c) for c in cases}
    out, dropped = [], []

    def cells_of(sid, s):
        cells = {cid: cell["values"] for cid, cell in s.get("cells", {}).items()
                 if fps.get(cid) == cell.get("sha")}
        missing = [cid for cid in fps if cid not in cells]
        if missing or "error" in s:
            dropped.append("%s (%d stale or missing)" % (sid, len(missing)))
            return None
        return cells

    for sid, s in _load("browser-stacks.json").items():
        cells = cells_of(sid, s)
        if cells is None:
            continue
        v = s["versions"].replace(" (Python)", "")
        v = re.sub(r"^(playwright|selenium|puppeteer) ", "", v)
        v = re.sub(r"^Crawlee for Python ", "", v)
        v = re.sub(r"^Crawlee ([\d.]+) \+ playwright [\d.]+$", r"\1", v)
        v = re.sub(r" \+ Beautiful Soup [\d.]+$", "", v)
        engine = (s.get("engine") or "?").replace("Chrome/", "Chrome for Testing ")
        if re.match(r"^[\d.]+$", engine):
            engine = "Chromium " + engine
        engine = re.sub(r"^(chromium|firefox|webkit|chrome) ",
                        lambda m: {"webkit": "WebKit"}.get(m.group(1), m.group(1).capitalize()) + " ", engine)
        out.append(({"id": sid, "language": BROWSER_LANG.get(sid, "Python"),
                     "label": BROWSER_LABEL.get(sid, "{v}").format(v=v),
                     "how": s["mode"], "engine": engine, "kind": "browser"}, cells))
    for sid, s in _load("pinned-stacks.json").items():
        if sid not in EXPORT_PINNED:
            continue
        cells = cells_of(sid, s)
        if cells is None:
            continue
        out.append(({"id": sid, "language": "Python", "label": s["label"], "how": s["how"],
                     "kind": "http", "outdated": not s.get("unreleased")}, cells))
    return out, dropped

# Off the public site until they can tell honoured from ignored. Deleting their declaration does
# not move the answer (see NOTEBOOK.md): the decoy points at the fallback encoding.
HELD_BACK = {
    "late-meta": "decoy target is the fallback encoding",
    "past-4096": "decoy target is the fallback encoding",
    "invalid-then-valid": "decoy target is the fallback encoding",
    "x-user-defined": "rewrite target is windows-1252 by definition; the note must say so",
}

# What the lab sends when a case declares no Content-Type. serve.py does the same.
DEFAULT_CTYPE = "text/html"


def served_ctype(c):
    return c["ctype"] or DEFAULT_CTYPE


def public_cases():
    return [c for c in CASES if c["id"] not in HELD_BACK]


def entry(c, browser, readers):
    b = browser.get(c["id"], {})
    fp = fingerprint(c)
    measured = "values" in b and b.get("sha", fp) == fp
    return {
        # Every public reader's answer, measured now on these exact bytes. An ERR: is an answer.
        "readers": {name: fn(c["ctype"], c["body"], c["sel"]) for name, fn in readers},
        "id": c["id"],
        "title": c["title"],
        "content_type": served_ctype(c),
        "declares_content_type": c["ctype"] is not None,
        "selector": c["sel"],
        "mechanism": c["mech"],
        "note": c["note"],
        "nav": c["nav"],
        "sha": fp,
        "size": len(c["body"]),
        "body_b64": base64.b64encode(c["body"]).decode("ascii"),
        "browser": {
            "values": b["values"],
            "charset": b.get("charset"),
            "nav": b.get("nav", "iframe"),
            "build": b.get("browser") or "Chrome/148",
            "locale": b.get("locale"),
        } if measured else None,
    }


def main(site_dir):
    browser = load_browser()
    readers = list(READERS)
    cases_ = public_cases()
    for name, into in SAME_AS.items():
        fns = dict(readers)
        differ = [c["id"] for c in cases_ if fns[name](c["ctype"], c["body"], c["sel"])
                  != fns[into](c["ctype"], c["body"], c["sel"])]
        if differ:
            raise SystemExit("FAIL %s differs from %s on %s; it can't share its row"
                             % (name, into, ", ".join(differ)))
    readers = [(n, fn) for n, fn in readers if n not in SAME_AS]
    cases = public_cases()
    extra, dropped = extra_stacks(cases)
    out = {
        "held_back": HELD_BACK,
        "stacks": stacks() + [s for s, _ in extra],
        "cases": [entry(c, browser, readers) for c in cases],
    }
    for e in out["cases"]:
        for s, cells in extra:
            e["readers"][s["id"]] = cells[e["id"]]
    path = os.path.join(site_dir, "data", "cases.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    unmeasured = [e["id"] for e in out["cases"] if e["browser"] is None]
    print("wrote %d cases to %s (%d held back)" % (len(out["cases"]), path, len(HELD_BACK)))
    if unmeasured:
        print("no current browser answer for: " + ", ".join(unmeasured))
    print("%d stacks, %d of them browser-driven" % (len(out["stacks"]),
                                                     sum(s["kind"] == "browser" for s in out["stacks"])))
    if dropped:
        print("NOT exported, cells don't match the current bytes: " + "; ".join(dropped))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m mojibake_tests.export_site <mojibake.wtf checkout>")
    main(sys.argv[1])
