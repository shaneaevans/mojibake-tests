# AGENTS.md: working in mojibake-tests

A differential lab for the gap between what a **browser** shows a person and what a **scraper**
extracts from the identical HTTP response. Read [README.md](README.md) first, then
[results/FINDINGS.md](results/FINDINGS.md) for the current results and [NOTEBOOK.md](NOTEBOOK.md)
for what is open.

## Build & run

```bash
make bootstrap                          # venv + pinned readers, plus the Node and JVM readers
make serve                              # cases on :8765; the harness page is at /
make capture-top                        # headless Chrome, top-level, for the nav="top-level" cases
make audit-nav                          # every case both ways in one build; fails on undeclared splits
make discriminate                       # every decoy case can tell honoured from ignored
make matrix                             # reader x case matrix
make summary                            # distinct answers per case, who disagrees with the browser
make verify-crawlee                     # the crawlee(*) columns vs a real crawler over real HTTP
```

The bench spans three runtimes. `js/` and `java/` hold the JavaScript and Java halves (cheerio,
jsdom, Crawlee, jsoup), driven over `mojibake_tests/bridge.py`; both are optional and report `ERR:`
per cell when the runtime is missing.

The browser column is captured two ways. `make browser` serves a harness page that loads every
`nav="iframe"` case in a same-origin iframe and merges the answers into `results/browser.json`;
`make capture-top` drives headless Chrome over the DevTools protocol, one fresh tab and one
top-level navigation per `nav="top-level"` case. Every cell records how it was loaded, the browser
build and locale, and a fingerprint of the bytes it was measured on; `make summary` refuses to grade
a cell whose fingerprint no longer matches its case, and an iframe answer never replaces a top-level
one.

## The rules

- **The browser is the standard.** Not the spec, not w3lib, not lxml. A scraper exists to see what
  the user sees, so where anything disagrees with what the browser actually rendered, the browser is
  right and the other reader has a bug. This is also the rule now applied to Frostwork.
- **Measure, never assert.** Every row in every table here came out of a run. "Browsers do X" is not
  a finding; a captured `browser.json` is. Spec text is a hypothesis to test, not a citation to
  quote.
- **A negative result is a result.** A mechanism that turns out NOT to split the field must be
  written down as such — `indented-bom` and `truncated-tag` are in the corpus precisely because they
  are documented divergences that did not reproduce. Deleting them would leave the next person to
  re-derive the same dead end.
- **Show the invisible.** The dangerous divergences are C1 controls, private-use code points and
  zero-width characters — printing them raw shows nothing at all, which is how they ship. Values go
  through `report.show()`, which renders them as `\x96` / `<PUA:F7E9>` / `<?>`.
- **An `ERR:` is an answer.** A reader that raises has told you something; never let a stack drop
  out of a sweep silently, or the ratio reported is over the cases that happened to survive.

## The five traps this harness has already fallen into

- **iframe charset inheritance.** An iframe whose document declares no encoding inherits the
  parent's. That silently made `no-declaration` read UTF-8 when a top-level navigation reads
  windows-1252 — i.e. the harness reported the browser agreeing with the scrapers on the single most
  common shape on the web. Any case whose expected answer depends on the *fallback* must be
  navigated to top-level, and cases meant to test a declaration should carry a real one so the
  fallback never enters the answer. That is now a declaration (`nav="top-level"`) plus a check:
  `make audit-nav` loads every case both ways in one build and fails on a split nobody declared.
- **A decoy needs a distinguishable target.** A `<meta charset=windows-1252>` decoy proves nothing
  when windows-1252 is also the browser's fallback: both sides land on the same answer and the case
  grades AGREE while the mechanism works perfectly. Point decoys at an encoding nothing falls back
  to, and prove it: `make discriminate` deletes each decoy and fails if the reading does not move.
- **An async handler answers in completion order.** The first cut of the Node worker replied from a
  fire-and-forget `on('line')` listener, so a slow stack's answer landed in a fast stack's row:
  every value plausible, the columns silently permuted. Requests are serialized and every reply
  carries its `id` back. Anything that fans out has to be able to say which question it answered.
- **A sweep that swept nothing looks like a clean pass.** Both Crawlee crawlers in
  `js/crawlee_sweep.js` shared the default request queue, so the second found every URL already
  handled, crawled zero pages, and produced zero mismatches. Coverage is now asserted before
  agreement — a reader that answered no cases agrees with everything.
- **One reader's imports change another reader's answer.** `import frostwork.encoding` (pulled in by
  w3lib 2.6, Scrapy 2.20 and web-poet 0.25) registers `x-user-defined` and `replacement` as Python
  codecs, process-wide. With every reader in one process, `requests`' .text and parsel decoded
  `x-user-defined` only because the Scrapy column had run first, and that went out to mojibake.wtf.
  Those readers now run in `py_worker.py`, and the sweep fails if the codec appears in the bench
  process. A column must give the same answer run alone in a fresh process as it does in the sweep.

## Adding to the lab

- **A reader** is one `@reader("name", "note")` function in `readers.py` taking
  `(content_type, body_bytes, selector)`. Prefer driving the stack the way its users drive it — the
  point of `requests.text+bs4` is requests' *own* `.text` rules, so it must go through a real
  `requests.Response`, not a hand-picked codec.
- **A reader in another language** is one entry in `js/reader.js` or `java/Reader.java` plus one
  `_remote(...)` line in `readers.py`. `bridge.py` keeps one long-lived process per runtime and
  speaks a line protocol to it; a whole sweep costs a few seconds. Two rules
  there: extract the *same* `E::text` definition the browser probe uses (direct child text nodes,
  undecorated — jsoup's `text()` collapses whitespace and would be answering a different question),
  and never reimplement the stack's encoding decision in Python. If the decision point is
  module-private, as Crawlee's `parseContentTypeFromResponse` is, transcribe it and add a
  verification that runs the real thing over real HTTP — `make verify-crawlee` is the pattern.
- **A case** is one `case(...)` call in `cases.py`: exact bytes, exact `Content-Type`, one selector,
  and a `note` saying which reader is expected to be wrong and why.
- **A demo** is a module in `demos/` exporting `NAME`, `CONTENT_TYPE`, `BODY`, `NOTE`, `CASES`, and
  registered in `cases.register_demos()` so the browser harness grades it like any other case.
