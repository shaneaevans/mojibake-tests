"""`python -m mojibake_tests.summary` — compact: how many DISTINCT answers each case produced, and
which readers disagreed with the browser.

Nothing here is asserted; it is read off the measured runs. A case with one distinct answer is a
NEGATIVE result and is reported as such — a mechanism that turns out not to split the field is worth
as much as one that does, and is the thing a lab like this most easily forgets to write down.
"""
import json

from mojibake_tests.cases import CASES, fingerprint
from mojibake_tests.readers import READERS
from mojibake_tests.report import load_browser

STALE = []    # cases whose stored browser answer was measured on bytes the case no longer has


def rows():
    browser = load_browser()
    out = []
    for c in CASES:
        b = browser.get(c["id"], {})
        if "values" not in b:
            continue
        if b.get("sha", fingerprint(c)) != fingerprint(c):
            STALE.append(c["id"])
            continue
        chrome = b["values"]
        answers = {json.dumps(chrome, ensure_ascii=False)}
        disagree = []
        for name, fn in READERS:
            v = fn(c["ctype"], c["body"], c["sel"])
            answers.add(json.dumps(v, ensure_ascii=False))
            if v != chrome:
                disagree.append(name)
        out.append(dict(id=c["id"], mech=c["mech"], answers=len(answers),
                        ndis=len(disagree), disagree=disagree, charset=b.get("charset")))
    return out


def main():
    rs = rows()
    if not rs:
        print("no results/browser.json — run `make browser` and load the harness page first")
        return
    print("%-20s %-13s %8s %9s  %s"
          % ("case", "mechanism", "answers", "!=browser", "readers disagreeing"))
    print("-" * 120)
    for r in rs:
        print("%-20s %-13s %8d %9d  %s"
              % (r["id"], r["mech"], r["answers"], r["ndis"], ", ".join(r["disagree"]) or "-"))
    print("-" * 120)
    split = sum(1 for r in rs if r["answers"] > 1)
    agree = sum(1 for r in rs if r["ndis"] == 0)
    worst = max(rs, key=lambda r: r["answers"])
    print("%d cases; %d produced more than one distinct answer; %d had every reader agreeing "
          "with the browser" % (len(rs), split, agree))
    print("most-split: %s (%d distinct answers across %d readers)"
          % (worst["id"], worst["answers"], len(READERS) + 1))
    if STALE:
        print("NOT GRADED, browser answer is for older bytes (recapture): " + ", ".join(STALE))


if __name__ == "__main__":
    main()
