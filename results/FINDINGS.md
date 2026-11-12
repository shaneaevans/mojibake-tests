# Findings

Measured on 2026-11-12 with the versions pinned in `requirements.txt`, `js/package.json` and the
`Makefile`. Every value below came out of `make matrix`, and invisible characters are written the
way `report.show()` prints them: `<?>` is U+FFFD, `\x96` a C1 control, `<PUA:F780>` a private-use
code point. The reference is Chrome: 32 cases from Chrome 148 through the iframe harness, 16 from
Chrome 156 loaded top-level, UI locale en-GB.

## The scrapers that come closest

Out of 48 cases, `jsdom(bytes)` disagrees with Chrome on 7, and Frostwork 0.2.2 and Scrapy 2.20.0
(which decides encodings with Frostwork) on 8. The README has the full table. The unreleased
Frostwork main matches Chrome on all 44 public cases.

Scrapy 2.20's eight are `no-declaration`, `utf32-bom`, and six cases where the tree differs because
lxml builds it: `nul-split`, `noscript`, `template`, `foster`, `demo-price` and `demo-stock`.

Three cases are matched by almost nobody:

| case | Chrome | readers that match it |
|---|---|---|
| `no-declaration`: UTF-8 bytes, no declaration anywhere | windows-1252 mojibake | `jsdom(bytes)` only |
| `noscript`: a `<noscript>` holding a stock message | nothing | `fetch.text+cheerio` only |
| `demo-price`: a product page with a `<template>` decoy price | `2.499,00 €` | `jsdom(bytes)`, `crawlee.py(bs4)`, `requests+apparent` |

The `no-declaration` row is Chrome being "wrong" by any spec-reading scraper's standard: it shows
the user mojibake. The rule here is that the scraper should see what the user sees, so every reader
that returns the clean UTF-8 text is graded as disagreeing.

## Where a `<meta charset>` stops counting

Chrome honours a `<meta charset>` anywhere in `<head>` (tested to 1 MB). In `<body>` it honours one
at byte 512 and ignores one at byte 1,024. Of the readers bisected, only w3lib comes close. Bisected with an ISO-8859-15 declaration
over the byte `0xA4`, which reads `€` only if the declaration is honoured:

| reader | in `<head>` | in `<body>` |
|---|---|---|
| Chrome | any depth | honoured at 512, ignored at 1,024 |
| `jsoup(bytes)` | tag ends within the first 5,120 bytes | the same |
| `jsdom(bytes)` | tag ends within the first 1,024 bytes | the same |
| `selectolax(lexbor)` | about 1 KB | the same |
| `lxml(bytes)` | any depth | any depth |
| `scrapy(w3lib+parsel)` | any depth | starts before byte 1024 |

## Same label, different characters

These need no trickery, just ordinary pages:

| case | bytes and label | Chrome | wrong answers |
|---|---|---|---|
| `latin1-label` | `0x96` as `iso-8859-1` | `99–149` | `99\x96149` (Crawlee, jsoup, the JDK), `99<?>149` |
| `eucjp-wave` | `A1C1 ADA1` as `euc-jp` | `～ ①` | `〜 <?><?>` (Python's codec), `<?><?> <?><?>` |
| `gb18030-pua` | `A3A0` as `gb18030` | `a　b` (U+3000) | `a<PUA:E5E5>b` (Python and the JDK) |

Chrome reads a page labelled `iso-8859-1` as windows-1252, so `0x96` is an en dash. A literal
ISO-8859-1 decoder turns it into an invisible control, and the price range `99–149` reads as `99149`.

## Crawlee for JavaScript

`crawlee(cheerio)` and `crawlee(jsdom)` are Crawlee 3.18.2's `CheerioCrawler` and `JSDOMCrawler`.
They decode with the same code and still return different text on 34 of 48 cases.

- **The document's `<meta charset>` is never read.** With no charset in the header, the body is
  UTF-8. On `late-meta`, Chrome shows `1.299,00 €` and `crawlee(cheerio)` returns `1.299,00 <?>`.
- **The header outranks a BOM.** On `bom-vs-http` (a UTF-8 BOM, `charset=windows-1252` in the
  header), Chrome shows `café — “Excellent”` and `crawlee(cheerio)` returns
  `cafÃ© â€” â€œExcellentâ€<?>`.
- **`JSDOMCrawler` decodes twice.** Crawlee transcodes the body to UTF-8, then passes it to jsdom
  with `contentType: 'text/html'` and no charset, so jsdom reads the UTF-8 bytes as windows-1252.
  On `eucjp-wave` `crawlee(cheerio)` returns Chrome's `～ ①` and `crawlee(jsdom)` returns
  `ï½ž â‘ `. Passing `text/html;charset=utf-8` would fix it.
- **An unknown label loses the page.** On `iso2022jp` and `http-x-user-defined`, both crawlers raise
  `served with unsupported charset`. Chrome shows `社会` for the first, and so do jsdom, `jsoup(http-charset)`,
  the JDK client and Crawlee for Python.
- **htmlparser2 invents content.** `CheerioCrawler` parses with htmlparser2 (`_useHtmlParser2: true`). cheerio's default
  backend, parse5 (`fetch.text+cheerio`), matches Chrome on `noscript`, `foster` and `endtag-attr`,
  where `crawlee(cheerio)` returns `Out of stock`, `moved` and `hidden from real parsers`.

## Crawlee for Python

Crawlee for Python 1.11.1 now decodes with the header's charset or the document's declaration, and gets `http-vs-meta`, `latin1-label` and
`iso2022jp` right. Its two crawlers differ on 15 of 48 cases. `crawlee.py(bs4)`
(`BeautifulSoupCrawler`) disagrees with Chrome on 19 and `crawlee.py(parsel)` (`ParselCrawler`) on
26. Both use Python's CJK codecs, so both get `eucjp-wave` and `gb18030-pua` wrong.

## Java

`jsoup(http-charset)` is what `Jsoup.connect(url).get()` does, and `jsoup(bytes)` is jsoup sniffing
for itself. The first raises `UnsupportedCharsetException` on `x-user-defined` and decodes
`iso-8859-1` literally. Both parse `utf32-bom` into tags and return `日本 😀`, where Chrome
reads UTF-16LE and shows the markup as text.

`jdk-http.ofString+jsoup` decodes with `java.net.http`'s `BodyHandlers.ofString()`: the header's
charset or UTF-8, with no BOM and no `<meta>`. It gets `bom-vs-http` and `late-meta` wrong for that
reason, and disagrees with Chrome on 35 of 48.

## Stacks that drive a browser

`results/browser-stacks.json` holds ten of them, measured on 2026-11-04 (Playwright 1.64.1,
Puppeteer 25.16.0, Selenium 4.52.0, Crawlee 3.18.2, Crawlee for Python 1.11.0, Scrapy 2.19.0 with
scrapy-playwright 0.0.48). Read in the page, Firefox and WebKit agree with the reference on every public
case, and the Chromium-based stacks differ only on `body-meta-512k`. They loaded it from the local
server, and Chrome's guess for that page depends on how the bytes arrive (see the case's note). The three that serialise the DOM and re-parse it get every encoding case right, because
the DOM is already text, and bring back the tree bugs: `scrapy-playwright` misses `noscript`,
`template`, `demo-price` and `demo-stock`.

## Mechanisms that did not split anyone

`indented-bom` and `truncated-tag` are documented divergences that every reader here gets right.
They stay in the corpus so nobody has to test them again.

## Caveats

- One browser with one locale. The fallback for an undeclared page depends on the locale, so a
  browser set to another language can give another answer on `no-declaration`.
- The browser column mixes Chrome 148 and Chrome 156. Chrome 156 gives the stored Chrome 148 value
  on all 32 iframe cases.
- The Crawlee columns reach code that Crawlee doesn't export. `make verify-crawlee` runs real
  crawlers over real HTTP and checks every Crawlee cell against them: 192 of 192 match.
