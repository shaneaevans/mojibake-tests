"""How DEEP into a document will a browser still honour a `<meta charset>`?

This is the measurement that decides Frostwork's prescan bound. WHATWG's 1024 bytes is a streaming
budget for the prescan, but a browser does not stop caring after it: the tokenizer reaches the
`<meta>` later and runs "change the encoding", re-decoding what it already has. So the real question
is not "what does the spec suggest" but "where does Chrome give up", and that is measurable.

Each case is the same page with the declaration pushed further back behind a comment. The
declaration is ISO-8859-15 over the byte 0xA4: honoured -> `1.299,00 €`; ignored -> the fallback's
reading of 0xA4 (`¤` in windows-1252, U+FFFD in UTF-8). A windows-1252 declaration would read the
same as the windows-1252 fallback, so the case could not say which happened. `make discriminate`
checks that the two outcomes differ.
"""

NAME = "late meta"
CONTENT_TYPE = "text/html"
# An ignored declaration leaves the fallback to answer, which an iframe gets wrong.
NAV = "top-level"
NOTE = "the same declaration, pushed progressively deeper behind a comment"

DECLARED = "iso-8859-15"
META = b'<meta charset="iso-8859-15">'
_PAYLOAD = "1.299,00 €".encode(DECLARED)

OFFSETS = [
    ("1k", 900),
    ("4k", 4200),
    ("16k", 16 * 1024),
    ("64k", 64 * 1024),
    ("256k", 256 * 1024),
    ("1m", 1024 * 1024),
]


def _page(pad):
    return (b'<!DOCTYPE html><html><head><!--' + b'x' * pad + b'-->' + META + b'</head><body>'
            b'<p id="t">' + _PAYLOAD + b'</p></body></html>')


PAGES = {("late-meta-%s" % name): _page(pad) for name, pad in OFFSETS}
TITLES = {("late-meta-%s" % name): "<meta charset> in the head, after a %s-byte comment" % format(pad, ",")
          for name, pad in OFFSETS}
CASES = [(cid, "#t::text") for cid in PAGES]

# The registry hands one BODY per module; this module has several, so it exposes `PAGES` and
# `cases.register_demos` reads that when present.
BODY = _page(900)
