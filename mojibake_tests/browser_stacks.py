"""`python -m mojibake_tests.browser_stacks` measures the stacks that render through a real browser.

Each one navigates top-level to every case over real HTTP and answers the selector, in one of two
ways, because people use these tools both ways:

  in the page     the browser's own DOM, read with serve.PROBE (the probe the Chrome reference
                  column runs), so the column measures the engine and nothing else
  re-parsed       the DOM serialised back to HTML (page.content(), driver.page_source) and parsed
                  again by a scraping parser, which brings that parser's tree rules back

Python stacks run here; the JavaScript ones run in `js/browser_sweep.js`; scrapy-playwright runs in
`scrapy_playwright_sweep.py`, a real Scrapy crawl in its own process. Results go to
`results/browser-stacks.json`, one cell per stack and case, each stamped with the case fingerprint.

Coverage is asserted before agreement: a stack that answered fewer cases than the corpus fails the
run, because a sweep that swept nothing agrees with everything.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile

SCRATCH = tempfile.mkdtemp(prefix="browser-stacks-")
os.environ.setdefault("CRAWLEE_STORAGE_DIR", os.path.join(SCRATCH, "crawlee-storage"))

from mojibake_tests.cases import CASES, fingerprint          # noqa: E402
from mojibake_tests.readers import _walk_soup                # noqa: E402
from mojibake_tests.report import ROOT                       # noqa: E402
from mojibake_tests.serve import PROBE                       # noqa: E402
from mojibake_tests.verify_crawlee import free_port, serve   # noqa: E402

OUT = os.path.join(ROOT, "results", "browser-stacks.json")
IN_PAGE = "(sel) => { %s\n return probe(document, sel); }" % PROBE
LANG = "() => navigator.language"


def _err(e):
    return ["ERR:%s: %s" % (type(e).__name__, str(e).splitlines()[0][:80] if str(e) else "")]


def _version(pkg):
    import importlib.metadata as md
    return md.version(pkg)


# ---------------------------------------------------------------- Playwright, three engines
def playwright_engines(base):
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        for name in ("chromium", "firefox", "webkit"):
            browser = getattr(p, name).launch(headless=True)
            cells, lang = {}, None
            for c in CASES:
                page = browser.new_page()
                try:
                    page.goto("%s/c/%s" % (base, c["id"]), wait_until="load", timeout=30000)
                    cells[c["id"]] = page.evaluate(IN_PAGE, c["sel"])
                    lang = lang or page.evaluate(LANG)
                except Exception as e:
                    cells[c["id"]] = _err(e)
                page.close()
            out["playwright(%s)" % name] = {
                "versions": "playwright %s (Python)" % _version("playwright"),
                "engine": "%s %s" % (name, browser.version), "lang": lang, "mode": "in the page",
                "cells": cells,
            }
            browser.close()
    return out


# ---------------------------------------------------------------- Crawlee for Python
async def crawlee_py_playwright(base):
    from crawlee.crawlers import PlaywrightCrawler
    from crawlee.storages import RequestQueue
    by_url = {"%s/c/%s" % (base, c["id"]): c for c in CASES}
    cells, meta = {}, {}
    queue = await RequestQueue.open(name="browser-stacks-%d" % os.getpid())
    crawler = PlaywrightCrawler(request_manager=queue, headless=True, max_request_retries=0)

    @crawler.router.default_handler
    async def handler(context):
        c = by_url[context.request.url]
        try:
            cells[c["id"]] = await context.page.evaluate(IN_PAGE, c["sel"])
            if "engine" not in meta:
                meta["engine"] = "chromium " + context.page.context.browser.version
                meta["lang"] = await context.page.evaluate(LANG)
        except Exception as e:
            cells[c["id"]] = _err(e)

    @crawler.failed_request_handler
    async def failed(context, error):
        cells[by_url[context.request.url]["id"]] = _err(error)

    await crawler.run(list(by_url))
    return {"crawlee.py(playwright)": {
        "versions": "Crawlee for Python %s" % _version("crawlee"), "engine": meta.get("engine"),
        "lang": meta.get("lang"), "mode": "in the page", "cells": cells}}


# ---------------------------------------------------------------- Selenium
def selenium_chrome(base):
    from bs4 import BeautifulSoup
    from selenium import webdriver
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    driver = webdriver.Chrome(options=opts)
    in_page, soup = {}, {}
    script = PROBE + "\nreturn probe(document, arguments[0]);"
    try:
        for c in CASES:
            try:
                driver.get("%s/c/%s" % (base, c["id"]))
                in_page[c["id"]] = driver.execute_script(script, c["sel"])
                soup[c["id"]] = _walk_soup(BeautifulSoup(driver.page_source, "html.parser"), c["sel"])
            except Exception as e:
                in_page[c["id"]] = soup[c["id"]] = _err(e)
        engine = "chrome " + driver.capabilities.get("browserVersion", "?")
        lang = driver.execute_script("return navigator.language")
    finally:
        driver.quit()
    v = "selenium %s" % _version("selenium")
    return {
        "selenium(chrome)": {"versions": v, "engine": engine, "lang": lang, "mode": "in the page", "cells": in_page},
        "selenium(chrome)+bs4": {"versions": v + " + Beautiful Soup %s" % _version("beautifulsoup4"),
                                 "engine": engine, "lang": lang,
                                 "mode": "re-parsed: driver.page_source into BeautifulSoup", "cells": soup},
    }


# ---------------------------------------------------------------- out of process
def scrapy_playwright(base, engine):
    out_path = os.path.join(SCRATCH, "scrapy_playwright.json")
    payload = json.dumps([{"id": c["id"], "sel": c["sel"]} for c in CASES])
    subprocess.run([sys.executable, "-m", "mojibake_tests.scrapy_playwright_sweep", base, out_path],
                   cwd=ROOT, input=payload.encode(), check=True)
    with open(out_path, encoding="utf-8") as f:
        cells = json.load(f)
    return {"scrapy-playwright": {
        "versions": "Scrapy %s + scrapy-playwright %s" % (_version("scrapy"), _version("scrapy-playwright")),
        # scrapy-playwright launches the same Playwright install measured above.
        "engine": engine, "lang": None,
        "mode": "re-parsed: page.content() into Scrapy's HtmlResponse", "cells": cells}}


def js_stacks(base):
    out_path = os.path.join(SCRATCH, "browser_sweep.json")
    payload = json.dumps({"probe": PROBE, "cases": [{"id": c["id"], "sel": c["sel"]} for c in CASES]})
    subprocess.run(["node", "js/browser_sweep.js", base, out_path], cwd=ROOT,
                   input=payload.encode(), check=True, stdout=subprocess.DEVNULL)
    with open(out_path, encoding="utf-8") as f:
        got = json.load(f)
    modes = {"puppeteer": "in the page", "crawlee(playwright)": "in the page",
             "crawlee(playwright+cheerio)": "re-parsed: parseWithCheerio()"}
    for name, s in got.items():
        s.setdefault("mode", modes.get(name, "?"))
        s.setdefault("lang", None)
    return got


def main():
    port = free_port()
    proc = serve(port)
    base = "http://127.0.0.1:%d" % port
    stacks = {}
    try:
        for label, run in [("playwright", lambda: playwright_engines(base)),
                           ("crawlee.py", lambda: asyncio.run(crawlee_py_playwright(base))),
                           ("selenium", lambda: selenium_chrome(base)),
                           ("scrapy-playwright", lambda: scrapy_playwright(base, stacks.get("playwright(chromium)", {}).get("engine"))),
                           ("js", lambda: js_stacks(base))]:
            try:
                stacks.update(run())
            except Exception as e:
                stacks[label] = {"error": "%s: %s" % (type(e).__name__, e)}
            print("swept %s" % label, file=sys.stderr)
    finally:
        proc.kill()

    by_id = {c["id"]: c for c in CASES}
    failed = False
    for name, s in stacks.items():
        if "error" in s:
            print("FAIL %-28s did not run: %s" % (name, s["error"][:120]))
            failed = True
            continue
        missing = [c["id"] for c in CASES if c["id"] not in s["cells"]]
        if missing:
            print("FAIL %-28s answered %d of %d cases" % (name, len(CASES) - len(missing), len(CASES)))
            failed = True
        s["cells"] = {cid: {"values": v, "sha": fingerprint(by_id[cid])} for cid, v in s["cells"].items()}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("{\n" + ",\n".join("%s: %s" % (json.dumps(k), json.dumps(v, ensure_ascii=False))
                                    for k, v in stacks.items()) + "\n}\n")
    print("wrote %d stacks to %s" % (len(stacks), OUT))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
