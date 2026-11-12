"""`python -m mojibake_tests.report [case-id ...]` — the full reader x case matrix.

With `results/browser.json` present (written by the browser harness in serve.py) the browser joins
as the first column, which is the only column that says what a PERSON saw.
"""
import json
import os
import sys

from mojibake_tests.bridge import ROOT
from mojibake_tests.cases import CASES, fingerprint
from mojibake_tests.readers import READERS

BROWSER_JSON = os.path.join(ROOT, "results", "browser.json")


def load_browser():
    if os.path.exists(BROWSER_JSON):
        with open(BROWSER_JSON) as f:
            return json.load(f)
    return {}


def show(v):
    """Render a value so the INVISIBLE differences are visible: C1 controls and private-use code
    points are exactly where a wrong price hides, and printing them raw shows nothing at all."""
    if isinstance(v, list):
        return "[" + ", ".join(show(x) for x in v) + "]"
    out = []
    for ch in str(v):
        o = ord(ch)
        if ch == "�":
            out.append("<?>")
        elif o < 0x20 or 0x7F <= o <= 0x9F:
            out.append("\\x%02x" % o)
        elif 0xE000 <= o <= 0xF8FF:
            out.append("<PUA:%04X>" % o)
        else:
            out.append(ch)
    return "'" + "".join(out) + "'"


def main(argv):
    only = set(argv) or None
    browser = load_browser()
    for c in CASES:
        if only and c["id"] not in only:
            continue
        print("=" * 100)
        print("[%s]  %s" % (c["id"], c["title"]))
        print("  mech=%s  selector=%s  Content-Type: %s"
              % (c["mech"], c["sel"], c["ctype"] or "(none)"))
        b = browser.get(c["id"])
        if b and b.get("sha", fingerprint(c)) != fingerprint(c):
            print("  %-22s STALE: measured on older bytes, recapture" % "BROWSER")
        elif b and "values" in b:
            print("  %-22s %s   [charset=%s, %d elements, %s%s]"
                  % ("BROWSER", show(b["values"]), b.get("charset"), b.get("nElems", -1),
                     b.get("nav", "iframe"), ", " + b["browser"] if "browser" in b else ""))
        elif b:
            print("  %-22s %s" % ("BROWSER", b.get("err", "?")))
        for name, fn in READERS:
            print("  %-22s %s" % (name, show(fn(c["ctype"], c["body"], c["sel"]))))
        print("  note: " + c["note"])


if __name__ == "__main__":
    main(sys.argv[1:])
