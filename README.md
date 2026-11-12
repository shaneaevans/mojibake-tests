# mojibake-tests

A browser and a scraper can read the same HTTP response and get different text. This repo measures
that gap. It has 48 test cases, each an exact set of bytes with an exact `Content-Type`, served over
real HTTP. It reads each one with Chrome and with 25 scraping stacks in Python, JavaScript and Java,
and reports every place they disagree.

The public version is [mojibake.wtf](https://mojibake.wtf). It serves every case at its own URL, so
you can point your own scraper at it.

## Why it matters

A page does not have to detect a bot to feed it bad data. `demos/fake_price.py` is one response
with nothing malformed in it. Chrome shows `1299,00 €`. Scrapy 2.19 on w3lib 2.4.1 extracts
`19,00`, because it obeys a `<meta charset=gb18030>` inside an HTML comment that the browser
ignores. Chrome reads the price's extra bytes as soft hyphens, which don't render. Decoded as
GB18030, the same bytes swallow the digits around them. Ten of the current stacks still get that
page wrong, among them `requests` with Beautiful Soup and both cheerio stacks.

Most cases are less deliberate than that. They are the shapes real pages have: a UTF-8 page with no
declaration, a `<meta charset>` 5 KB down, a BOM that contradicts the header, `windows-1252` bytes
labelled `iso-8859-1`.

## What it found

From `make summary` on 2026-11-12: 46 of the 48 cases produce more than one distinct answer across
the 25 readers. On one case, `http-x-user-defined`, they give 7 different answers. Disagreements with
Chrome, out of 48:

| reader | disagrees | | reader | disagrees |
|---|---|---|---|---|
| `jsdom(bytes)` | 7 | | `selectolax(lexbor)` | 27 |
| `frostwork` (0.2.2) | 8 | | `jsoup(http-charset)` | 27 |
| `scrapy` (2.20.0) | 8 | | `jsoup(bytes)` | 29 |
| `scrapy(w3lib+parsel)` | 14 | | `requests.text+lxml` | 32 |
| `crawlee(jsdom)` | 18 | | `requests.text+bs4` | 32 |
| `html5lib` | 19 | | `requests.text+parsel` | 34 |
| `crawlee.py(bs4)` | 19 | | `fetch.text+cheerio` | 35 |
| `lxml(bytes)` | 20 | | `jdk-http.ofString+jsoup` | 35 |
| `requests+apparent` | 23 | | `crawlee(cheerio)` | 36 |
| `bs4+dammit` | 26 | | `parsel(body=)` | 38 |
| `crawlee.py(parsel)` | 26 | | `regex scraper` | 38 |

`scrapy+frostwork` and `web-poet+frostwork` give the same answers as `scrapy`. Each reader's
docstring in `mojibake_tests/readers.py` says exactly what it calls. The library versions are pinned
in `requirements.txt`, `js/package-lock.json` and the `Makefile`. A version bump moves a column, so
these numbers belong to those versions.

`make browser-stacks` measures ten stacks that drive a real browser, and `make pinned-stacks`
measures older Scrapy and an unreleased Frostwork checkout. [results/FINDINGS.md](results/FINDINGS.md)
says what all of them get wrong and why, and [NOTEBOOK.md](NOTEBOOK.md) lists what is still open.

The browser is the standard throughout. A scraper exists to see what the user sees, so where a
spec, a library or this repo's own expectations disagree with what Chrome rendered, Chrome is right.

## Running it

You need Python 3 and `make`. Node and a JDK are optional: without them the JavaScript and Java
columns report `ERR:` in every cell instead of disappearing, so the totals stay honest. It has been
run with Python 3.14, Node 26 and JDK 21 on macOS.

```bash
make bootstrap          # venv, pinned Python readers, and the Node and JVM readers if present
make matrix             # every reader against every case, joined with the recorded browser column
make summary            # distinct answers per case, and which readers disagree with the browser
make demo               # the assembled demo pages through every reader
```

Those three read `results/browser.json`, the recorded Chrome answers, so they need no browser. To
measure a browser yourself:

```bash
make browser            # serves the cases; open http://127.0.0.1:8765/ in the browser to measure
make capture-top        # headless Chrome, one top-level load per case that needs it (CHROME=<binary>)
make audit-nav          # loads every case both ways and fails on a split nobody declared
make discriminate       # fails if a decoy case can't tell a declaration honoured from one ignored
make verify-crawlee     # checks the Crawlee columns against real Crawlee crawls over real HTTP
```

`make browser-stacks` needs `requirements-browsers.txt` and `playwright install chromium firefox
webkit`. `make pinned-stacks` measures a Frostwork checkout at `../frostwork`, or wherever
`FROSTWORK_CHECKOUT` points, and keeps the recorded column if there is none. `make verify-live`
fetches every public case from mojibake.wtf and fails if a byte or a header has changed.

The browser column records how each cell was loaded, the browser build and locale, and a
fingerprint of the bytes it measured. `make summary` refuses to grade a cell whose fingerprint no
longer matches its case. The fallback encoding depends on the browser's locale. The recorded column
is Chrome with the UI locale en-GB, and a different locale can give a different answer on the
cases with no declaration.

## Layout

| path | what |
|---|---|
| `mojibake_tests/cases.py` | the cases: exact bytes, `Content-Type`, one selector, and what it tests |
| `mojibake_tests/readers.py` | the readers, one `@reader` function per scraping stack |
| `mojibake_tests/bridge.py` | long-lived Node, JVM and Python workers, so a reader can be in any language |
| `mojibake_tests/serve.py` | serves each case byte for byte and hosts the browser harness |
| `mojibake_tests/capture.py` | top-level browser capture over the DevTools protocol |
| `js/`, `java/` | the JavaScript and Java readers (cheerio, jsdom, Crawlee, jsoup) |
| `demos/` | assembled pages: a realistic response that lies to a scraper |
| `results/` | the recorded browser columns and the write-ups |

## Contributing

A new reader, a new case or a correction is welcome. [CONTRIBUTING.md](CONTRIBUTING.md) says what
a pull request needs, and [AGENTS.md](AGENTS.md) lists the measurement traps this repo has already
fallen into.

## Licence

[Apache License 2.0](LICENSE).
