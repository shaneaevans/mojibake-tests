"""`python -m mojibake_tests.discriminate [--browser]` checks each decoy case can tell its outcomes
apart.

A case that plants `<meta charset=X>` asks "was the declaration honoured?", and can only answer if
honouring it and ignoring it give different text. For every case of a demo that exports `DECLARED`
and `META`, this reads three pages:

    as served   the case itself
    ignored     the case with META deleted, i.e. what the reader shows if it never saw it
    honoured    the case with `Content-Type: text/html; charset=DECLARED`

and fails where honoured == ignored, or where the case as served is neither. Frostwork is checked
always; `--browser` measures the same three pages in headless Chrome, top-level.
"""
import sys

from demos import body_meta_depth, late_meta_depth
from mojibake_tests.cases import CASES
from mojibake_tests.report import show
from mojibake_tests.readers import r_frostwork

DECOYS = (late_meta_depth, body_meta_depth)


def variants():
    """(case, ignored page, honoured page) for every decoy case."""
    out = []
    for mod in DECOYS:
        for c in CASES:
            if c["id"] not in mod.PAGES:
                continue
            assert c["body"].count(mod.META) == 1, c["id"]
            ignored = dict(ctype=c["ctype"], body=c["body"].replace(mod.META, b""))
            honoured = dict(ctype="text/html; charset=" + mod.DECLARED, body=c["body"])
            out.append((c, ignored, honoured))
    return out


def grade(name, rows):
    """rows: (case id, as served, ignored, honoured). Returns the ids that cannot discriminate."""
    print("%s\n%-16s %-14s %-14s %-14s %s" % (name, "case", "honoured", "ignored", "as served",
                                              "outcome"))
    bad = []
    for cid, served, ignored, honoured in rows:
        if honoured == ignored:
            outcome = "CANNOT DISCRIMINATE"
        elif served == honoured:
            outcome = "honoured (deleting the meta changes the answer)"
        elif served == ignored:
            outcome = "ignored"
        else:
            outcome = "NEITHER"
        if outcome in ("CANNOT DISCRIMINATE", "NEITHER"):
            bad.append(cid)
        print("%-16s %-14s %-14s %-14s %s" % (cid, show(honoured), show(ignored), show(served),
                                              outcome))
    print()
    return bad


def main(argv):
    vs = variants()
    bad = grade("frostwork", [(c["id"], r_frostwork(c["ctype"], c["body"], c["sel"]),
                               r_frostwork(i["ctype"], i["body"], c["sel"]),
                               r_frostwork(h["ctype"], h["body"], c["sel"])) for c, i, h in vs])
    if "--browser" in argv:
        from mojibake_tests.capture import Chrome, Server
        extra = {}
        for c, i, h in vs:
            extra[c["id"] + "~ignored"], extra[c["id"] + "~honoured"] = i, h
        with Chrome() as chrome, Server(extra) as srv:
            def read(cid, sel):
                return chrome.top_level(srv.base + "/c/" + cid, sel)["values"]
            bad += grade(chrome.product + " (top-level)",
                         [(c["id"], read(c["id"], c["sel"]), read(c["id"] + "~ignored", c["sel"]),
                           read(c["id"] + "~honoured", c["sel"])) for c, i, h in vs])
    print("%d decoy cases; %d cannot say whether the declaration was honoured: %s"
          % (len(vs), len(set(bad)), ", ".join(sorted(set(bad))) or "-"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
