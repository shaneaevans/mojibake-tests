"""`python -m mojibake_tests.capture` captures the browser column for cases an iframe cannot answer.

An iframe whose document declares no encoding inherits its parent's, so the harness in serve.py is
wrong by construction for any case whose answer can depend on the fallback (AGENTS.md, the first
trap). This drives headless Chrome over the DevTools protocol instead: a fresh tab and ONE top-level
navigation per case, the harness's own probe, and the browser build and language in every cell.

    python -m mojibake_tests.capture            # every nav="top-level" case, merged into the column
    python -m mojibake_tests.capture ID ...     # just these cases, captured top-level
    python -m mojibake_tests.capture --audit    # every case both ways in one build; writes nothing

`--audit` checks the `nav` declarations: a case whose iframe and top-level values differ depends on
the fallback, and fails the audit unless it is declared top-level. It also names every stored cell
this build answers differently, which is how a browser upgrade shows up.

Chrome is `$CHROME`, else the stock macOS install. The fallback depends on the locale, so Chrome is
asked for `$CAPTURE_LANG` (default en-GB, the locale the column was first measured in) and every
cell records what the page actually got: `lang` (navigator.language) and `locale` (the UI locale,
as JavaScript's default `Intl` locale).

A case declared `capture="live"` is loaded from the deployed site (`$LIVE`, default
https://mojibake.wtf) instead, after `verify_live` confirms it serves the lab's exact bytes and header.
Those are the cases whose answer depends on how the bytes arrive. Chrome runs its detector on each
network chunk until one gives a verdict, and what the first chunks hold depends on the server and the
network: measured from the lab's server, which writes a page in one call, the detector saw about the
first 263 KB, and from the deployed site it saw less on most loads. Loads vary too, so a live case is
loaded `$LIVE_LOADS` times (default 11): the cell holds the most common answer, where it was loaded
from (`served`) and every answer's count (`tally`). A tie for the most common answer is refused rather
than recorded. `python -m mojibake_tests.capture --selftest` checks that rule on made-up loads.
"""
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

from mojibake_tests.cases import CASES, fingerprint
from mojibake_tests.report import load_browser, show
from mojibake_tests.serve import BY_ID, PROBE, H, merge_cells

CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
LIVE = os.environ.get("LIVE", "https://mojibake.wtf").rstrip("/")
LIVE_LOADS = int(os.environ.get("LIVE_LOADS", "11"))
LANG = os.environ.get("CAPTURE_LANG", "en-GB")


class Chrome:
    """Headless Chrome over `--remote-debugging-pipe`: CDP as NUL-terminated JSON, commands on the
    child's fd 3 and replies on its fd 4, so no websocket client is needed."""

    def __enter__(self):
        if not os.access(CHROME, os.X_OK):
            sys.exit("no Chrome at %r: set CHROME to a Chrome binary" % CHROME)
        self.profile = tempfile.mkdtemp(prefix="mojibake-tests-chrome-")
        cmd_r, self.cmd_w = os.pipe()
        self.out_r, out_w = os.pipe()

        def fds():
            a, b = os.dup(cmd_r), os.dup(out_w)
            os.dup2(a, 3)
            os.dup2(b, 4)

        # Start before any thread exists: preexec_fn is only safe in a single-threaded parent.
        self.proc = subprocess.Popen(
            [CHROME, "--headless", "--remote-debugging-pipe", "--user-data-dir=" + self.profile,
             "--no-first-run", "--no-default-browser-check", "--lang=" + LANG,
             "--accept-lang=" + LANG, "about:blank"],
            preexec_fn=fds, close_fds=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(cmd_r)
        os.close(out_w)
        self.buf, self.last_id = b"", 0
        self.product = self.send("Browser.getVersion")["product"]
        return self

    def __exit__(self, *exc):
        try:
            self.send("Browser.close")
        except Exception:
            self.proc.kill()
        self.proc.wait(10)
        os.close(self.cmd_w)
        os.close(self.out_r)
        shutil.rmtree(self.profile, ignore_errors=True)

    def send(self, method, session=None, timeout=60, **params):
        self.last_id += 1
        msg = {"id": self.last_id, "method": method, "params": params}
        if session:
            msg["sessionId"] = session
        os.write(self.cmd_w, json.dumps(msg).encode() + b"\0")
        deadline = time.monotonic() + timeout
        while True:
            reply = self._recv(deadline)
            if reply.get("id") != self.last_id:
                continue                       # an event: nothing here subscribes to any
            if "error" in reply:
                raise RuntimeError("%s: %s" % (method, reply["error"]))
            return reply.get("result", {})

    def _recv(self, deadline):
        while b"\0" not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self.out_r], [], [], left)[0]:
                raise TimeoutError("Chrome did not reply")
            chunk = os.read(self.out_r, 1 << 20)
            if not chunk:
                raise RuntimeError("Chrome closed the pipe")
            self.buf += chunk
        msg, self.buf = self.buf.split(b"\0", 1)
        return json.loads(msg)

    def _poll(self, url, expr, timeout):
        """Open `url` in a fresh tab (that IS the one top-level navigation) and evaluate `expr`
        once the document at `url` has finished loading and `expr` is non-null."""
        target = self.send("Target.createTarget", url=url)["targetId"]
        try:
            session = self.send("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
            ready = ("location.href === %s && document.readyState === 'complete' ? (%s) : null"
                     % (json.dumps(url), expr))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                r = self.send("Runtime.evaluate", session, expression=ready, returnByValue=True)
                if "exceptionDetails" in r:
                    raise RuntimeError(r["exceptionDetails"].get("text", "evaluate failed"))
                value = r["result"].get("value")
                if value is not None:
                    return value
                time.sleep(0.05)
            raise TimeoutError("%s did not finish loading" % url)
        finally:
            self.send("Target.closeTarget", targetId=target)

    def top_level(self, url, sel, timeout=60):
        cell = self._poll(url, "(() => { %s\nreturn record(document, %s); })()"
                          % (PROBE, json.dumps(sel)), timeout)
        return dict(cell, nav="top-level", browser=self.product)

    def harness(self, url, timeout=900):
        """The iframe harness itself, in this build, read back without letting it save."""
        cells = self._poll(url, "window.__RESULT || null", timeout)
        return {cid: dict(cell, browser=self.product) for cid, cell in cells.items()}


class Server:
    """The corpus on a free port, plus any extra pages (`{id: {"ctype", "body"}}`). A POST is
    discarded: what this module captures, it writes itself."""

    def __init__(self, extra=None):
        def discard(handler):
            handler.rfile.read(int(handler.headers.get("Content-Length", 0)))
            return handler._send(b"discarded", "text/plain")

        handler = type("CaptureHandler", (H,), {"cases": dict(BY_ID, **(extra or {})),
                                                "do_POST": discard})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def load_top(chrome, srv, c):
    """One top-level load of case `c`: from the lab's server, or from the deployed site for a
    `capture="live"` case, which must first serve the lab's exact bytes."""
    if c["capture"] != "live":
        return chrome.top_level(srv.base + "/c/" + c["id"], c["sel"])
    selftest()
    from mojibake_tests.verify_live import check_case
    problems = check_case(LIVE, c)
    if problems:
        sys.exit("%s is captured from %s, which does not serve the lab's bytes: %s"
                 % (c["id"], LIVE, "; ".join(problems)))
    loads = [chrome.top_level(LIVE + "/c/" + c["id"], c["sel"], timeout=120) for _ in range(LIVE_LOADS)]
    cell, tally = most_common(loads)
    if cell is None:
        sys.exit("%s: no single most common answer over %d loads from %s: %s"
                 % (c["id"], len(loads), LIVE, tally))
    return dict(cell, served=LIVE, tally=tally)


def most_common(loads):
    """`(cell, tally)` over repeated loads of one case: an answer is a charset and its values, the cell
    is the first load giving the most common one, and the tally counts each answer. The cell is `None`
    when there are no loads or the top two answers tie."""
    groups = {}
    for cell in loads:
        key = "%s %s" % (cell["charset"], json.dumps(cell["values"], ensure_ascii=False))
        groups.setdefault(key, []).append(cell)
    tally = {key: len(same) for key, same in groups.items()}
    counts = sorted(tally.values(), reverse=True)
    if not counts or (len(counts) > 1 and counts[0] == counts[1]):
        return None, tally
    return max(groups.values(), key=len)[0], tally


def selftest():
    """`most_common` on made-up loads: the cases that once recorded a wrong answer."""
    a = {"charset": "windows-1252", "values": ["x"]}
    b = {"charset": "windows-874", "values": ["y"]}
    same_text = {"charset": "ISO-8859-15", "values": ["x"]}
    assert most_common([a, b, a]) == (a, {'windows-1252 ["x"]': 2, 'windows-874 ["y"]': 1})
    assert most_common([b, a, a, b])[0] is None, "a tie must not be recorded"
    assert most_common([])[0] is None, "no loads, no answer"
    cell, tally = most_common([a, same_text, same_text])
    assert cell is same_text and tally == {'windows-1252 ["x"]': 1, 'ISO-8859-15 ["x"]': 2}, \
        "two charsets giving the same text are two answers"
    print("selftest: ok")


def capture(cases):
    with Chrome() as chrome, Server() as srv:
        print("%s, asked for %s" % (chrome.product, LANG))
        cells = {}
        for c in cases:
            cell = load_top(chrome, srv, c)
            cells[c["id"]] = cell
            print("  %-20s %-13s %s" % (c["id"], cell["charset"], show(cell["values"])))
    kept = merge_cells(cells)
    assert not kept, kept
    print("merged %d top-level cells into results/browser.json" % len(cells))


def audit():
    stored = load_browser()
    with Chrome() as chrome, Server() as srv:
        print("%s, asked for %s" % (chrome.product, LANG))
        framed = chrome.harness(srv.base + "/?all")
        print("%-20s %-9s %-26s %s"
              % ("case", "nav", "iframe vs top-level", "stored cell vs this build"))
        print("-" * 100)
        undeclared, drift = [], []
        for c in CASES:
            top = load_top(chrome, srv, c)
            fr = framed.get(c["id"], {})
            if top["values"] != fr.get("values"):
                split = "VALUES DIFFER"
                if c["nav"] != "top-level":
                    undeclared.append(c["id"])
            elif top["charset"] != fr.get("charset"):
                split = "charset only (%s/%s)" % (fr.get("charset"), top["charset"])
            else:
                split = "same"
            cell = stored.get(c["id"], {})
            mine = top if c["nav"] == "top-level" else fr
            if "values" not in cell:
                vs = "no stored cell"
            elif cell.get("sha", fingerprint(c)) != fingerprint(c):
                vs = "STALE (bytes changed since capture)"
            elif cell["values"] != mine.get("values"):
                vs = "DIFFERS: stored %s, now %s" % (show(cell["values"]), show(mine.get("values")))
                drift.append(c["id"])
            else:
                vs = "same"
            if "values" in cell and "sha" not in cell:
                vs += " (unfingerprinted: cannot say which bytes it measured)"
            print("%-20s %-9s %-26s %s" % (c["id"], c["nav"], split, vs))
    print("-" * 100)
    print("%d cases; %d depend on the fallback but are not declared top-level: %s"
          % (len(CASES), len(undeclared), ", ".join(undeclared) or "-"))
    print("%d stored cells answer differently in this build: %s"
          % (len(drift), ", ".join(drift) or "-"))
    return 1 if undeclared else 0


def main(argv):
    if "--selftest" in argv:
        selftest()
        return 0
    if "--audit" in argv:
        return audit()
    unknown = [a for a in argv if a not in BY_ID]
    if unknown:
        sys.exit("no such case: " + ", ".join(unknown))
    capture([BY_ID[a] for a in argv] if argv else [c for c in CASES if c["nav"] == "top-level"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
