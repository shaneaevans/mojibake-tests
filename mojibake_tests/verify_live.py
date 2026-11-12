"""`python -m mojibake_tests.verify_live [base-url]` checks that a deployed mojibake.wtf serves every
public case exactly as the lab does.

Expected values come from `cases.py`, not from the exported site data, so a bug in the export fails
here too. Each case is fetched twice, once asking for no compression and once offering gzip, and
both must decode to the lab's bytes under the lab's exact Content-Type header. The report says
which encodings actually came back: with `Cache-Control: no-transform` Cloudflare sends the bytes
uncompressed whatever the client offers (measured 2026-11-04), so the gzip pass is a check that it
still does, not a test of gzip. Coverage is checked before agreement: a run that fetched nothing
would otherwise pass.

Exit status is non-zero on any mismatch.
"""
import gzip
import hashlib
import json
import sys
import urllib.error
import urllib.request

from mojibake_tests.cases import CASES
from mojibake_tests.export_site import HELD_BACK, public_cases, served_ctype

UA = "mojibake-verify-live/1 (+https://mojibake.wtf)"


def fetch(url, encoding):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": encoding})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


RECEIVED = {}   # (offered, Content-Encoding received) -> count


def check_case(base, c):
    problems = []
    want = c["body"]
    for enc in ("identity", "gzip"):
        status, headers, raw = fetch("%s/c/%s" % (base, c["id"]), enc)
        if status != 200:
            problems.append("%s: HTTP %d" % (enc, status))
            continue
        ctypes = headers.get_all("Content-Type") or []
        if ctypes != [served_ctype(c)]:
            problems.append("%s: Content-Type %r, lab sends %r" % (enc, ctypes, served_ctype(c)))
        ce = headers.get("Content-Encoding")
        RECEIVED[(enc, ce or "identity")] = RECEIVED.get((enc, ce or "identity"), 0) + 1
        if ce == "gzip":
            raw = gzip.decompress(raw)
        elif ce not in (None, "identity"):
            problems.append("%s: unexpected Content-Encoding %r" % (enc, ce))
            continue
        if raw != want:
            at = next((i for i, (a, b) in enumerate(zip(raw, want)) if a != b), min(len(raw), len(want)))
            problems.append("%s: body differs from byte %d (%d bytes served, lab has %d)"
                            % (enc, at, len(raw), len(want)))
    return problems


def main(base):
    base = base.rstrip("/")
    cases = public_cases()
    failed, checked = {}, 0
    for c in cases:
        probs = check_case(base, c)
        checked += 1
        if probs:
            failed[c["id"]] = probs

    # Held-back cases must not be served: they are off the site until their decoy can fail.
    for cid in HELD_BACK:
        status, _, _ = fetch("%s/c/%s" % (base, cid), "identity")
        if status != 404:
            failed[cid] = ["held back, but served with HTTP %d" % status]

    # The manifest must list exactly the public cases, at the lab's fingerprints.
    status, headers, raw = fetch(base + "/cases.json", "identity")
    if status != 200:
        failed["/cases.json"] = ["HTTP %d" % status]
    else:
        listed = {e["id"]: e["sha"] for e in json.loads(raw)["cases"]}
        from mojibake_tests.cases import fingerprint
        expect = {c["id"]: fingerprint(c) for c in cases}
        if listed != expect:
            missing = sorted(set(expect) - set(listed))
            extra = sorted(set(listed) - set(expect))
            stale = sorted(k for k in set(listed) & set(expect) if listed[k] != expect[k])
            failed["/cases.json"] = ["missing %s, extra %s, stale %s" % (missing, extra, stale)]

    print("%s: %d of %d public cases checked, %d held back, %d in the lab"
          % (base, checked, len(cases), len(HELD_BACK), len(CASES)))
    if checked != len(cases) or checked == 0:
        print("FAIL: coverage, checked %d of %d" % (checked, len(cases)))
        return 1
    for cid, probs in failed.items():
        for p in probs:
            print("FAIL %-20s %s" % (cid, p))
    if failed:
        return 1
    digest = hashlib.sha256(b"".join(c["body"] for c in cases)).hexdigest()[:16]
    got = ", ".join("offered %s, got %s x%d" % (o, r, n) for (o, r), n in sorted(RECEIVED.items()))
    print("received: " + got)
    print("OK: every case byte-identical to the lab (corpus %s)" % digest)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "https://mojibake.wtf"))
