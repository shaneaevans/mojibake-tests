"""Crafted pages where the SAME bytes read as different text depending on who reads them.

Each case is (id, title, content_type_header_or_None, body_bytes, css_selector, mechanism, note).
The selector semantics compared everywhere are parsel's `E::text` == direct child TEXT NODES of E,
so the browser probe is `childNodes.filter(nodeType==3).map(.data)`.

`nav` says how the browser column loads a case. An iframe that declares no encoding inherits its
parent's, so any case whose answer can depend on the FALLBACK is `top-level` and is captured by
`capture.py`, one top-level navigation per case; the rest go through the iframe harness in
`serve.py`. `make audit-nav` measures both ways and fails if a case differs and is not `top-level`.
"""
import hashlib

# ---------------------------------------------------------------- building blocks
U8 = "café — “Excellent”".encode("utf-8")          # real UTF-8, high bytes
W1252 = "1.299,00 €".encode("windows-1252")   # 0x80 = euro in cp1252
LATIN_DASH = b"99\x96149"                          # 0x96: en dash in cp1252, U+0096 control in latin-1


def doc(head=b"", body=b"", pre=b""):
    return (pre + b"<!DOCTYPE html><html><head>" + head + b"</head><body>"
            + body + b"</body></html>")


def p(payload):
    return b'<p id="t">' + payload + b"</p>"


CASES = []


def case(cid, title, ctype, body, sel="#t::text", mech="", note="", nav="iframe", capture="local"):
    """`capture="live"` marks a case whose browser answer depends on how the bytes arrive, so
    `make capture-top` loads it from the deployed site instead of the lab's server (capture.py)."""
    assert nav in ("iframe", "top-level"), nav
    assert capture in ("local", "live"), capture
    assert capture == "local" or nav == "top-level", "a live capture is a top-level load"
    CASES.append(dict(id=cid, title=title, ctype=ctype, body=body, sel=sel,
                      mech=mech, note=note, nav=nav, capture=capture))


def fingerprint(c):
    """What a browser answer was measured ON. A cell whose fingerprint no longer matches the case
    answers for bytes that no longer exist, and must not be graded."""
    return hashlib.sha256((c["ctype"] or "").encode() + b"\n" + c["body"]).hexdigest()[:16]


# ============================================================ A. ENCODING RESOLUTION
case("no-declaration", "no charset anywhere, UTF-8 bytes", None,
     doc(body=p(U8)),
     mech="sniffing", nav="top-level",
     note="the HTML spec's fallback is locale-dependent (windows-1252 in practice); every Python "
          "scraper stack defaults to UTF-8 instead")

case("comment-decoy", "a <meta charset> inside a comment, before the real one", None,
     doc(head=b"<!-- <meta charset=big5> --><meta charset=utf-8>", body=p(U8)),
     mech="sniffing",
     note="w3lib has no comment handling and takes the FIRST regex hit, which is the decoy; "
          "WHATWG's prescan skips comments and reaches the real declaration")

case("late-meta", "<meta charset> after <body> started", None,
     doc(body=b'<meta charset="windows-1252">' + p(W1252)),
     mech="sniffing",
     note="w3lib's regex has a `|body` alternative and gives up there")

case("invalid-then-valid", "unsupported label, then a valid one", None,
     doc(head=b'<meta charset="not-a-charset"><meta charset="windows-1252">', body=p(W1252)),
     mech="sniffing",
     note="WHATWG: an unsupported label is 'failure, continue'; w3lib stops at its first regex hit")

case("stray-quote", "stray quote inside an unquoted charset value", None,
     doc(head=b'<meta http-equiv="content-type" content="text/html" charset=windows-1252" />'
              b'<meta charset="big5">',
         body=p("中文".encode("big5"))),
     mech="sniffing",
     note="an unquoted attribute value ends at whitespace or `>`, so the label is `windows-1252\"` "
          "-> invalid -> continue to big5. w3lib stops at the quote and takes windows-1252")

case("meta-utf16", "<meta charset=utf-16> on ASCII-compatible bytes", None,
     doc(head=b'<meta charset="utf-16">', body=p(U8)),
     mech="sniffing",
     note="the prescan could only READ it by assuming ASCII-compat, so WHATWG rewrites it to UTF-8")

case("x-user-defined", "<meta charset=x-user-defined>", None,
     doc(head=b'<meta charset="x-user-defined">', body=p(W1252)),
     mech="sniffing",
     note="'get an encoding from a meta element' step 5 rewrites it to windows-1252")

case("http-x-user-defined", "HTTP charset=x-user-defined (no meta rewrite)",
     "text/html; charset=x-user-defined",
     doc(body=p(W1252)),
     mech="sniffing",
     note="from HTTP the label is NOT rewritten: every high byte -> U+F780+b private use")

case("replacement-enc", "<meta charset=hz-gb-2312> (WHATWG 'replacement')", None,
     doc(head=b'<meta charset="hz-gb-2312">', body=p(b"Members only: 4 seats left")),
     mech="sniffing",
     note="WHATWG maps this label to the `replacement` decoder: the WHOLE document becomes one U+FFFD")

case("past-4096", "declaration past the 4096-byte prescan window", None,
     doc(head=b"<!--" + b"x" * 4200 + b'--><meta charset="windows-1252">', body=p(W1252)),
     mech="sniffing",
     note="a browser has no window: the tokenizer reaches the meta and re-decodes. w3lib and "
          "Frostwork both stop at 4096")

case("xmldecl-late", "<?xml encoding=...?> not at offset 0", None,
     doc(head=b'<?xml version="1.0" encoding="big5"?><meta charset=utf-8>', body=p(U8)),
     mech="sniffing",
     note="a `<?` after the start of the document is a bogus comment and declares nothing; "
          "w3lib's regex searches anywhere in its window")

case("utf32-bom", "UTF-32LE BOM (FF FE 00 00)", None,
     b"\xff\xfe\x00\x00" + ('<!DOCTYPE html><html><body><p id="t">' + "日本 \U0001f600"
                            + "</p></body></html>").encode("utf-32-le"),
     mech="sniffing",
     note="the WHATWG Encoding Standard has no UTF-32, so FF FE IS the UTF-16LE BOM. Agrees for BMP "
          "text after NUL deletion; an astral character is where the two readings split")

case("http-vs-meta", "HTTP charset wins over <meta> (control)",
     "text/html; charset=windows-1252",
     doc(head=b'<meta charset="utf-8">', body=p(W1252)),
     mech="sniffing", note="everyone should agree here — the control row")

case("bom-vs-http", "UTF-8 BOM outranks a conflicting HTTP charset (control)",
     "text/html; charset=windows-1252",
     b"\xef\xbb\xbf" + doc(body=p(U8)),
     mech="sniffing", note="control row: BOM first for everyone")

# ============================================================ B. DECODER INDEX
case("latin1-label", "charset=iso-8859-1 with byte 0x96", "text/html; charset=iso-8859-1",
     doc(body=p(LATIN_DASH)),
     mech="decoder",
     note="the WHATWG label iso-8859-1 MEANS windows-1252 (0x96 = en dash). Python's literal "
          "latin_1 codec gives the invisible control U+0096")

case("eucjp-wave", "euc-jp A1C1 (wave dash) + ADA1 (circled 1)",
     "text/html; charset=euc-jp",
     doc(body=p(b"\xa1\xc1 \xad\xa1")),
     mech="decoder",
     note="WHATWG/CP932: U+FF5E and U+2460. Python's strict euc_jp: U+301C and U+FFFD")

case("gb18030-pua", "gb18030 A3A0", "text/html; charset=gb18030",
     doc(body=p(b"a\xa3\xa0b")),
     mech="decoder",
     note="GB18030-2005 moved this out of the PUA: U+3000 here, U+E5E5 in Python's older index")

case("cp1252-c1", "windows-1252 bytes 81 8D 8F 90 9D", "text/html; charset=windows-1252",
     doc(body=p(b"x\x81y\x8dz")),
     mech="decoder",
     note="a WHATWG index is TOTAL; Python's cp1252 leaves these five undefined -> U+FFFD")

# ============================================================ C. INPUT NORMALIZATION
case("indented-bom", "a U+FEFF preceded by whitespace", None,
     b"  \xef\xbb\xbf" + b"<!DOCTYPE html><html xmlns=\"h\"><head><title>Real Title</title></head>"
     b"<body><p id=\"t\">body text</p></body></html>",
     sel="title::text",
     mech="normalization",
     note="parsel parses text.strip(), which PROMOTES the U+FEFF to offset 0 where libxml2 eats it "
          "as a BOM. On the raw bytes it is a character before the frame -> the head is lost")

case("vertical-tab", "a leading VERTICAL TAB (0x0B)", None,
     b"\x0b<!DOCTYPE html><html><head><title>Real Title</title></head>"
     b"<body><p id=\"t\">body text</p></body></html>",
     sel="title::text",
     mech="normalization",
     note="0x0B is whitespace to Python's str.strip() and NOT to libxml2 or HTML5")

case("nul-split", "a NUL inside a tag name", None,
     doc(body=b'<di\x00v id="t">deleted-nul text</di\x00v>'),
     sel="div::text",
     mech="normalization",
     note="parsel deletes NUL document-wide before parsing; HTML5 keeps it (U+FFFD in a tag name "
          "ends the name)")

# ============================================================ D. BYTE-SCANNING vs DECODE-FIRST
_JP = b"\x1b$B<R2q\x1b(B"   # ISO-2022-JP for 社会; in raw bytes that is the ASCII text `<R2q`
case("iso2022jp", "ISO-2022-JP: the word 社会 is the bytes `<R2q`",
     "text/html; charset=iso-2022-jp",
     doc(body=b'<p id="t">' + _JP + b"</p>"),
     mech="tokenizer",
     note="ISO-2022-JP is NOT ASCII-compatible: inside ESC $ B a JIS pair is two bytes below 0x80, "
          "so a byte-scanning tokenizer grows a start tag out of the middle of a Japanese word")

# ============================================================ E. STRUCTURE (pure ASCII)
case("noscript", "<noscript> is raw text only when scripting is ENABLED", None,
     doc(body=b'<p id="real">In stock</p><noscript><p id="t">Out of stock</p></noscript>'),
     sel="#t::text",
     mech="structure",
     note="with scripting on (a browser) <noscript> is RAWTEXT and contains no elements; every "
          "scraper parses with scripting off and sees real markup")

case("template", "<template> content is a separate fragment", None,
     doc(body=b'<p id="real">EUR 19.99</p><template><p id="t">EUR 99.99</p></template>'),
     sel="#t::text",
     mech="structure",
     note="a browser puts template children in a DocumentFragment, so querySelector/rendering "
          "never see them; lxml/parsel/bs4 treat them as ordinary descendants")

case("foster", "foster parenting out of a <table>", None,
     doc(body=b"<table><tr><td>1</td></tr><p id=\"t\">moved</p></table>"),
     sel="table #t::text",
     mech="structure",
     note="HTML5 moves the <p> to BEFORE the table; libxml2 does not foster-parent, so it stays "
          "inside and `table p` matches there and nowhere else")

case("bogus-comment", "</%> is a bogus comment and SPLITS a text node", None,
     doc(body=b'<p id="t">1,234</%>.56</p>'),
     mech="tokenizer",
     note="only an ASCII letter after `</` starts an end tag; `</%>` is a COMMENT node, so the "
          "text is two nodes. `</>` is ignored instead and splits nothing")

case("endtag-attr", "an end tag has a start tag's attribute states", None,
     doc(body=b'<p id="t">shown</p></img\nsrc="http:><p id="t">hidden from real parsers</p>'
              b'<span>x</span>">'),
     mech="tokenizer",
     note="the unterminated quoted value in an END tag runs to the next quote, swallowing every "
          "byte between. A `scan a name, skip to >` reader keeps markup no browser has")

case("truncated-tag", "a start tag the response ends inside", None,
     b'<!DOCTYPE html><html><body><p id="t">real text</p><a href="/x" data-junk="',
     sel="a::attr(data-junk)",
     mech="tokenizer",
     note="libxml2 and html5lib DROP the incomplete tag whole; keeping the attributes scanned so "
          "far reports an element holding the rest of the document")


# ============================================================ F. ASSEMBLED DEMOS
def register_demos():
    """Demos live in `demos/` and register themselves as cases so the browser harness and the
    matrix grade them exactly like an atomic case."""
    from demos import body_meta_depth, fake_price, late_meta_depth, product_price
    for mod in (product_price, fake_price, late_meta_depth, body_meta_depth):
        pages = getattr(mod, "PAGES", None)   # a module may carry one body or many
        for cid, sel in mod.CASES:
            # A module may describe each case; otherwise the title is the module name plus the id.
            title = getattr(mod, "TITLES", {}).get(cid) or "%s: %s" % (mod.NAME, cid if pages else sel)
            case(cid, title, mod.CONTENT_TYPE,
                 pages[cid] if pages else mod.BODY, sel=sel, mech="assembled",
                 note=getattr(mod, "NOTES", {}).get(cid, mod.NOTE),
                 nav=getattr(mod, "NAV", "iframe"),
                 capture="live" if cid in getattr(mod, "LIVE", ()) else "local")


register_demos()
