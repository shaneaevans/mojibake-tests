"""`python -m mojibake_tests.verify_crawlee` — check all four Crawlee columns against real Crawlee.

Every Crawlee column in the bench reaches the framework's real decoding code past something
private: `parseContentTypeFromResponse` in JS is not exported, and the Python parser classes are
not re-exported from `crawlee.crawlers`. Under this lab's own rule that is an assertion until it is
measured, so: serve the corpus over real HTTP, run a real CheerioCrawler, JSDOMCrawler,
BeautifulSoupCrawler and ParselCrawler across it, and diff.

Exits non-zero on any disagreement — or on any crawler that swept fewer cases than the corpus,
because a crawler that answered nothing agrees with everything.
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time

SCRATCH = os.environ.get("TMPDIR", "/tmp")
# Before crawlee is imported anywhere: its storage must not land in the repo.
os.environ.setdefault("CRAWLEE_STORAGE_DIR", os.path.join(SCRATCH, "crawlee-verify-storage"))

from mojibake_tests.bridge import JS, ROOT           # noqa: E402
from mojibake_tests.cases import CASES               # noqa: E402
from mojibake_tests.readers import READERS, pick_bs4, pick_parsel, split_pseudo  # noqa: E402
from mojibake_tests.report import show               # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def serve(port):
    """The case server on its own port, so a sweep never collides with `make serve`."""
    env = dict(os.environ, MOJIBAKE_TESTS_PORT=str(port))
    proc = subprocess.Popen([sys.executable, "-m", "mojibake_tests.serve"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            return proc
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("case server did not come up on :%d" % port)


def sweep_js(base):
    """The JS half, out of process: `js/crawlee_sweep.js` writes to a file because Crawlee logs."""
    out_path = os.path.join(SCRATCH, "crawlee_sweep.json")
    payload = json.dumps([{"id": c["id"], "sel": c["sel"]} for c in CASES])
    subprocess.run(["node", "js/crawlee_sweep.js", base, out_path], cwd=ROOT,
                   input=payload.encode("utf-8"), check=True, stdout=subprocess.DEVNULL)
    with open(out_path) as f:
        return json.load(f)


async def sweep_py(base):
    """The Python half, in process: real BeautifulSoupCrawler and ParselCrawler over real HTTP."""
    from crawlee.crawlers import BeautifulSoupCrawler, ParselCrawler
    from crawlee.storages import RequestQueue

    by_url = {"%s/c/%s" % (base, c["id"]): c for c in CASES}
    out = {}

    async def one(label, queue_name, factory, pick):
        got = {}
        # A queue of its own per crawler: sharing the default one leaves the second crawler with
        # every URL already handled, so it sweeps NOTHING and mismatches nothing.
        queue = await RequestQueue.open(name=queue_name)
        crawler = factory(request_manager=queue, max_request_retries=0, configure_logging=False)

        @crawler.router.default_handler
        async def _(ctx):
            c = by_url[ctx.request.url]
            base_sel, kind, attr = split_pseudo(c["sel"])
            els = await crawler._parser.select(ctx.parsed_content, base_sel)
            got[c["id"]] = {"values": [v for el in els for v in pick(el, kind, attr)]}

        @crawler.failed_request_handler
        async def _(ctx, error):
            got[by_url[ctx.request.url]["id"]] = {"error": "%s: %s" % (type(error).__name__, error)}

        await crawler.run(list(by_url))
        await queue.drop()
        out[label] = got

    await one("crawlee.py(bs4)", "sweep-bs4", BeautifulSoupCrawler, pick_bs4)
    await one("crawlee.py(parsel)", "sweep-parsel", ParselCrawler, pick_parsel)
    return out


def main():
    port = free_port()
    server = serve(port)
    base = "http://127.0.0.1:%d" % port
    try:
        live = sweep_js(base)
        live.update(asyncio.run(sweep_py(base)))
    finally:
        server.kill()

    by_case = {c["id"]: c for c in CASES}
    bad = 0
    for name in ("crawlee(cheerio)", "crawlee(jsdom)", "crawlee.py(bs4)", "crawlee.py(parsel)"):
        fn = dict(READERS)[name]
        # Coverage first: a crawler that swept nothing agrees with everything.
        missing = [c["id"] for c in CASES if c["id"] not in live.get(name, {})]
        if missing:
            bad += len(missing)
            print("NOT SWEPT %-14s %d of %d cases: %s"
                  % (name, len(missing), len(CASES), ", ".join(missing[:6])))
        for cid, real in live[name].items():
            c = by_case[cid]
            bench = fn(c["ctype"], c["body"], c["sel"])
            # An error is an answer, but the MESSAGE carries a url that differs by port; the
            # exception type and the reason are what have to match.
            if "error" in real:
                kind = real["error"].split(":")[0]
                ok = bench and bench[0].startswith("ERR:" + kind)
            else:
                ok = bench == real["values"]
            if not ok:
                bad += 1
                print("MISMATCH %-14s %-20s\n    bench %s\n    real  %s"
                      % (name, cid, show(bench),
                         show(real.get("values", real.get("error")))))
    total = sum(len(live[n]) for n in live)
    print("%d cells checked against a live crawler, %d mismatched" % (total, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
