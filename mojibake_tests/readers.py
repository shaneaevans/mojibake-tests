"""The reader bench: one function per real-world way of turning an HTTP response into text.

Adding a stack is one decorated function. Each takes the response (headers + raw bytes) and a CSS
selector, and returns the list of extracted strings — or `ERR:...` if that stack refuses, because a
stack that raises is a real outcome and must not be silently dropped.

`E::text` means parsel's thing everywhere: the direct child TEXT NODES of E. The browser probe in
`serve.py` implements the same definition, so every column is answering one question.

Scraping is not a Python monoculture, and neither is this bench: the JavaScript and Java columns
run in real Node and JVM processes over `bridge.py`, driving cheerio, jsdom, Crawlee and jsoup
themselves rather than a Python guess at what they do.
"""
import codecs
import os
import re

from mojibake_tests.bridge import FROSTWORK_PY, JAVA, JS, FROSTWORK_WORKER_ENV

READERS = []

# Set in the process that answers the Frostwork-family readers (py_worker.py), and in any child that
# runs a single reader on its own (pinned_sweep.py). Everywhere else those readers are remote.
IN_FROSTWORK_WORKER = os.environ.get(FROSTWORK_WORKER_ENV) == "1"


def _check_codec_registry(name):
    """Fail the sweep if a reader has made `x-user-defined` decodable in this process.

    `import frostwork.encoding` (which w3lib 2.6, Scrapy 2.20 and web-poet 0.25 all do) registers
    Python codecs for `x-user-defined` and `replacement`, and the codec registry is process-wide.
    Once registered, `requests`' .text, Beautiful Soup and parsel decode those labels in every later
    reader, so a stack that never imports Scrapy gets measured as if it ran next to Scrapy. That is
    why the Frostwork family runs in its own worker."""
    if IN_FROSTWORK_WORKER:
        return
    try:
        codecs.lookup("x-user-defined")
    except LookupError:
        return
    raise RuntimeError("after %s, x-user-defined is a codec in the bench process: a reader that "
                       "imports frostwork.encoding ran here instead of in the worker" % name)


def reader(name, note=""):
    """Register a reader. Order here is the order in the matrix."""
    def deco(fn):
        def wrapped(ctype, body, sel):
            try:
                out = fn(ctype, body, sel)
            except Exception as e:
                out = ["ERR:%s: %s" % (type(e).__name__, str(e)[:70])]
            _check_codec_registry(name)
            return out
        wrapped.__name__ = fn.__name__
        wrapped.note = note
        READERS.append((name, wrapped))
        return wrapped
    return deco


def _remote(worker, stack, note):
    """One column answered by another process. The name in the matrix IS the stack name the worker
    reports, so a rename over there cannot quietly leave a stale column here."""
    @reader(stack, note)
    def fn(ctype, body, sel, _w=worker, _s=stack):
        return _w.call(_s, ctype, body, sel)
    return fn


FROSTWORK_FAMILY = []


def frostwork_family(name, note=""):
    """A reader that imports frostwork.encoding. It runs in its own Python process (see
    _check_codec_registry), and here it is a remote column at the same place in the matrix."""
    FROSTWORK_FAMILY.append(name)
    if IN_FROSTWORK_WORKER:
        return reader(name, note)

    def deco(fn):
        _remote(FROSTWORK_PY, name, note)
        return fn
    return deco


def charset_of(ctype):
    if not ctype:
        return None
    m = re.search(r"charset\s*=\s*([^;\s]+)", ctype, re.I)
    return m.group(1).strip("\"'") if m else None


def split_pseudo(sel):
    """`div.x::attr(href)` -> ('div.x', 'attr', 'href'); `p::text` -> ('p', 'text', None)."""
    m = re.match(r"^(.*?)(?:::text|::attr\((.+)\))$", sel)
    if not m:
        return sel.strip() or "*", "text", None
    base = m.group(1).strip() or "*"
    return base, ("attr" if m.group(2) else "text"), m.group(2)


def _lxml_xpath(root, sel):
    """Run parsel's own CSS->XPath so no reader hand-rolls the pseudo-element."""
    from parsel.csstranslator import HTMLTranslator
    return [str(n) for n in root.xpath(HTMLTranslator().css_to_xpath(sel))]


def _walk_soup(soup, sel):
    base, kind, attr = split_pseudo(sel)
    out = []
    for el in soup.select(base):
        if kind == "attr":
            if el.has_attr(attr):
                out.append(el[attr])
        else:
            out += [str(c) for c in el.children if isinstance(c, str)]
    return out


# ============================================================ the engine under test
# Every reader that takes a URL gets this one, so the top-level domain that Frostwork's autodetection
# weighs (and Scrapy's and web-poet's through it) is the same for all of them.
URL = "https://mojibake.wtf/"


@reader("frostwork", "Frostwork standalone: frostwork.extract() on the bytes, the HTTP charset and the URL")
def r_frostwork(ctype, body, sel):
    import frostwork
    return frostwork.extract(body, [sel], charset_of(ctype), url=URL)[0]


# ============================================================ the Scrapy family
def _scrapy_response(ctype, body):
    from scrapy.http import HtmlResponse
    headers = {"Content-Type": ctype} if ctype else {}
    return HtmlResponse(URL, headers=headers, body=body)


@frostwork_family("scrapy", "Scrapy on Parsel: an HtmlResponse and .css(), Scrapy's own encoding decision")
def r_scrapy_real(ctype, body, sel):
    # Since Scrapy 2.20 / w3lib 2.6 that encoding decision is Frostwork's (w3lib.encoding calls
    # frostwork.encoding); the parse and the selector are still parsel on lxml.
    return _scrapy_response(ctype, body).css(sel).getall()


@frostwork_family("scrapy+frostwork", "Scrapy on Frostwork: the HtmlResponse handed to Page.extract_response()")
def r_scrapy_frostwork(ctype, body, sel):
    # The ordinary-callback path in Frostwork's README: `PAGE.extract_response(response)`. The
    # released extract_response passes response.encoding, Scrapy's decision, as the encoding.
    import frostwork
    page = frostwork.Page().field_all("v", sel)
    return page.extract_response(_scrapy_response(ctype, body)).to_dict()["v"]


@frostwork_family("web-poet+frostwork", "web-poet's declared selectors, which web-poet 0.25 extracts with Frostwork")
def r_webpoet_frostwork(ctype, body, sel):
    # What scrapy-poet injects into a page object: a web_poet.HttpResponse. A css_getall()
    # declaration is read by Frostwork in one pass, given the body and response.encoding.
    from web_poet import HttpResponse, WebPage, css_getall
    headers = {"Content-Type": ctype} if ctype else {}
    page_cls = type("CasePage", (WebPage,), {"v": css_getall(sel)})
    return page_cls(response=HttpResponse(URL, body=body, headers=headers)).v


@frostwork_family("scrapy(w3lib+parsel)", "w3lib's html_to_unicode with a UTF-8 default, then parsel on .text")
def r_scrapy(ctype, body, sel):
    # Passing default_encoding= is deprecated since w3lib 2.6 and takes the old path: header, then
    # <meta>, else the default. It is what code that called w3lib directly still does.
    import warnings
    from parsel import Selector
    from w3lib.encoding import html_to_unicode
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        _, text = html_to_unicode(ctype, body, auto_detect_fun=None, default_encoding="utf-8")
    return Selector(text=text).css(sel).getall()


@reader("parsel(body=)", "raw parsel: the HTTP label handed straight to lxml, no w3lib")
def r_parsel_body(ctype, body, sel):
    from parsel import Selector
    return Selector(body=body, encoding=charset_of(ctype) or "utf-8").css(sel).getall()


# ============================================================ the requests family
def _requests_response(ctype, body):
    """A real requests.Response, so requests' OWN encoding rules apply — including its text/*
    default and its apparent_encoding fallback. Built without a socket."""
    import requests
    r = requests.Response()
    r.status_code = 200
    r._content = body
    r.headers["Content-Type"] = ctype or "text/html"
    r.encoding = requests.utils.get_encoding_from_headers(r.headers)
    return r


@reader("requests.text+lxml", "requests' own .text rules, then lxml/cssselect")
def r_requests_lxml(ctype, body, sel):
    import lxml.html
    text = _requests_response(ctype, body).text
    return _lxml_xpath(lxml.html.document_fromstring(text), sel)


@reader("requests.text+parsel", "requests' .text into Selector(text=): the test loop on mojibake.wtf")
def r_requests_parsel(ctype, body, sel):
    from parsel import Selector
    return Selector(text=_requests_response(ctype, body).text).css(sel).getall()


@reader("requests.text+bs4", "the single most common scraping stack there is")
def r_requests_bs4(ctype, body, sel):
    from bs4 import BeautifulSoup
    text = _requests_response(ctype, body).text
    return _walk_soup(BeautifulSoup(text, "html.parser"), sel)


@reader("requests+apparent", "requests with charset_normalizer detection forced on")
def r_requests_apparent(ctype, body, sel):
    from bs4 import BeautifulSoup
    r = _requests_response(ctype, body)
    r.encoding = r.apparent_encoding
    return _walk_soup(BeautifulSoup(r.text, "html.parser"), sel)


# ============================================================ Crawlee for Python
class _CrawleeResponse:
    """The `HttpResponse` protocol Crawlee's parsers consume, carrying one case.

    The decoding decision in Crawlee for Python lives in the PARSER (`parse()` receives the whole
    response and does what it likes with it), so driving the real parser object drives the real
    decision. `mojibake_tests.verify_crawlee` runs the actual crawlers over real HTTP to check that.
    """

    def __init__(self, ctype, body):
        from crawlee._types import HttpHeaders
        self._body = body
        self.http_version = "HTTP/1.1"
        self.status_code = 200
        self.headers = HttpHeaders({"content-type": ctype or "text/html"})

    async def read(self):
        return self._body

    async def read_stream(self):
        yield self._body


def pick_bs4(el, kind, attr):
    """`E::text` / `E::attr(a)` off one bs4 Tag. Shared with `verify_crawlee` so the live-crawler
    check diffs the DECODING, not two spellings of the extraction."""
    if kind == "attr":
        return [el[attr]] if el.has_attr(attr) else []
    return [str(c) for c in el.children if isinstance(c, str)]


def pick_parsel(el, kind, attr):
    """The same, off one parsel Selector."""
    if kind == "attr":
        v = el.attrib.get(attr)
        return [] if v is None else [v]
    return el.xpath("text()").getall()


def _crawlee_py(parser, ctype, body, sel, pick):
    import asyncio

    async def go():
        doc = await parser.parse(_CrawleeResponse(ctype, body))
        base, kind, attr = split_pseudo(sel)
        return [pick(el, kind, attr) for el in await parser.select(doc, base)]

    return [v for group in asyncio.run(go()) for v in group]


@reader("crawlee.py(bs4)", "Crawlee for Python: raw bytes to BeautifulSoup(features='lxml'), no hint")
def r_crawlee_py_bs4(ctype, body, sel):
    # Not re-exported from `crawlee.crawlers`; this is the parser BeautifulSoupCrawler builds, with
    # the same default (`parser='lxml'`). The live-crawler check is what proves that.
    from crawlee.crawlers._beautifulsoup._beautifulsoup_parser import BeautifulSoupParser

    return _crawlee_py(BeautifulSoupParser(), ctype, body, sel, pick_bs4)


@reader("crawlee.py(parsel)", "Crawlee for Python: Selector(body=...) with no encoding= at all")
def r_crawlee_py_parsel(ctype, body, sel):
    from crawlee.crawlers._parsel._parsel_parser import ParselParser

    return _crawlee_py(ParselParser(), ctype, body, sel, pick_parsel)


# ============================================================ parser-does-its-own-sniffing
@reader("lxml(bytes)", "libxml2 sniffing the raw bytes itself — no HTTP header in the path")
def r_lxml_bytes(ctype, body, sel):
    import lxml.html
    return _lxml_xpath(lxml.html.document_fromstring(body), sel)


@reader("html5lib", "the HTML5 spec reference parser, doing the WHATWG prescan over the bytes")
def r_html5lib(ctype, body, sel):
    import html5lib
    tree = html5lib.parse(body, treebuilder="lxml", namespaceHTMLElements=False,
                          transport_encoding=charset_of(ctype))
    return _lxml_xpath(tree.getroot(), sel)


@reader("bs4+dammit", "BeautifulSoup sniffing bytes with UnicodeDammit")
def r_bs4(ctype, body, sel):
    from bs4 import BeautifulSoup
    return _walk_soup(BeautifulSoup(body, "html.parser", from_encoding=charset_of(ctype)), sel)


@reader("selectolax(lexbor)", "a production HTML5 engine over raw bytes")
def r_selectolax(ctype, body, sel):
    # Until selectolax 1.0 this column ran selectolax.parser.HTMLParser, which is the Modest
    # engine, not lexbor, whatever the column was called. 1.0 removed Modest. encoding=True asks
    # lexbor to sniff the bytes, as detect_encoding/use_meta_tags did.
    from selectolax.lexbor import LexborHTMLParser
    base, kind, attr = split_pseudo(sel)
    out = []
    for el in LexborHTMLParser(body, encoding=True).css(base):
        if kind == "attr":
            if attr in el.attributes:
                out.append(el.attributes[attr] or "")
        else:
            n = el.child
            while n is not None:
                if n.tag == "-text":
                    out.append(n.text_content)
                n = n.next
    return out


# ============================================================ JavaScript (real Node, via bridge)

_remote(JS, "fetch.text+cheerio",
        "node fetch().text() + cheerio: the most common JS scraper. .text() is UTF-8, always")
_remote(JS, "crawlee(cheerio)",
        "Crawlee's CheerioCrawler: HTTP charset via iconv-lite, no <meta> anywhere in the path")
_remote(JS, "crawlee(jsdom)",
        "Crawlee's JSDOMCrawler: same resolution, then jsdom re-sniffs the transcoded bytes")
_remote(JS, "jsdom(bytes)",
        "jsdom over raw bytes: html-encoding-sniffer IS the WHATWG prescan")

# ============================================================ Java (real JVM, via bridge)
_remote(JAVA, "jsoup(bytes)",
        "jsoup sniffing for itself: BOM, then its own <meta> prescan, then UTF-8")
_remote(JAVA, "jsoup(http-charset)",
        "what Jsoup.connect().get() does: the HTTP charset is handed in and <meta> is not read")
_remote(JAVA, "jdk-http.ofString+jsoup",
        "java.net.http BodyHandlers.ofString() decides the charset, then jsoup parses a String")


# ============================================================ the no-parser end of the field
@reader("regex scraper", "no tree, no tokenizer states — what a great many one-off scrapers are")
def r_regex(ctype, body, sel):
    text = body.decode(charset_of(ctype) or "utf-8", errors="replace")
    m = re.match(r"^(?:(\w+)?[#.]([\w-]+)|(\w+))\s*(?:::text|::attr\((.+)\))$", sel)
    if not m:
        return ["ERR:unsupported by the naive reader"]
    _, ident, tag, attr = m.groups()
    if ident:
        pat = (r"<(\w+)([^>]*\b(?:id|class)=[\"'][^\"']*%s[^\"']*[\"'][^>]*)>(.*?)</\1>"
               % re.escape(ident))
    else:
        pat = r"<(%s)(\b[^>]*)?>(.*?)</\1>" % re.escape(tag)
    out = []
    for mm in re.finditer(pat, text, re.S | re.I):
        if attr:
            am = re.search(r"\b%s=[\"']([^\"']*)[\"']" % re.escape(attr), mm.group(2) or "")
            if am:
                out.append(am.group(1))
        else:
            out.append(re.sub(r"<[^>]*>", "", mm.group(3)))
    return out
