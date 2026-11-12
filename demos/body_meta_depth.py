"""Does a browser honour a `<meta charset>` that appears deep in the BODY, after real content?

This decides whether an engine's prescan may be bounded at all. A `<meta>` inside `<head>` is
honoured at any depth (see `late_meta_depth`). But the HTML spec reaches "change the encoding" from
the "in body" insertion mode too, and a browser that has already painted has to decide whether
re-decoding is still worth it — so "in the body, after N bytes of content" is a different question
from "in the head, after N bytes of comment".

If Chrome stops honouring it past some amount of body content, a bound exists and can be matched.
If it never stops, the scan has to be unbounded and the cost is intrinsic.

The payload sits BEFORE the declaration in each page, which is the hard case: honouring the
declaration means re-decoding text the parser has already emitted.

The declaration is ISO-8859-15 over the byte 0xA4: honoured, it reads `1.299,00 €`; ignored, it
reads as the fallback decodes 0xA4 (`¤` in windows-1252, U+FFFD in UTF-8). A windows-1252
declaration would read the same as the windows-1252 fallback, so the case could not say which
happened. `make discriminate` checks that the two outcomes differ.
"""

NAME = "body meta"
CONTENT_TYPE = "text/html"
# An ignored declaration leaves the fallback to answer, which an iframe gets wrong.
NAV = "top-level"
NOTE = "a declaration in the BODY, behind increasing amounts of real content"

DECLARED = "iso-8859-15"
META = b'<meta charset="iso-8859-15">'
_PAYLOAD = "1.299,00 €".encode(DECLARED)

OFFSETS = [("0", 0), ("100", 100), ("512", 512), ("1k", 1024), ("2k", 2048),
           ("3k", 3072), ("4k", 4096), ("64k", 64 * 1024), ("512k", 512 * 1024)]


def _page(pad):
    filler = b"<p>lorem ipsum dolor sit amet consectetur</p>" * (pad // 44) if pad else b""
    return (b'<!DOCTYPE html><html><head><title>t</title></head><body>'
            b'<p id="t">' + _PAYLOAD + b'</p>' + filler + META
            + b'</body></html>')


PAGES = {("body-meta-%s" % name): _page(pad) for name, pad in OFFSETS}
TITLES = {cid: ("<meta charset> in the body, straight after the text it decodes" if pad == 0 else
                "<meta charset> in the body, after %s bytes of content" % format(
                    len(b"<p>lorem ipsum dolor sit amet consectetur</p>") * (pad // 44), ","))
          for (name, pad), cid in zip(OFFSETS, PAGES)}
CASES = [(cid, "#t::text") for cid in PAGES]

# Chrome runs its detector on each network chunk until one gives a verdict, and the 512k page has no
# declaration it honours, so its answer depends on delivery. From the lab's server, which writes the page in one call,
# Chrome 156 reads windows-874 (`1.299,00 ค`) once the page holds at least 262,944 bytes; from
# mojibake.wtf it read windows-1252 on 42 of 46 loads and windows-874 on 4 (2026-11-07). The recorded
# answer is the deployed site's most common one, with its tally.
LIVE = {"body-meta-512k"}
NOTES = {"body-meta-512k": NOTE + "; with nothing honoured, Chrome autodetects from the first network "
                           "chunk that gives a verdict, so the answer depends on delivery: windows-1252 on most loads from "
                           "mojibake.wtf, windows-874 on some, and windows-874 from the lab's own server"}
BODY = _page(0)
