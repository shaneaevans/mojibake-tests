# Lab notebook

The dated log of this lab, newest entry first. An entry says what was measured, on which versions,
and what is still open. [results/FINDINGS.md](results/FINDINGS.md) holds the current results.

## First public release (2026-11-12)

48 cases, 25 readers, and a browser column of Chrome 148 (32 cases, iframe) and Chrome 156 (16
cases, top-level), UI locale en-GB. `results/FINDINGS.md` was rewritten from a fresh sweep on this
date. `make discriminate`, `make audit-nav` and `make verify-crawlee` pass.

Open:

- **`browser-stacks.json` dates from 2026-11-04.** It was measured with Playwright 1.64.1 and
  Scrapy 2.19.0. The pins have moved to Playwright for Node 1.65.0 and Scrapy 2.20.0, whose browser
  builds were not downloaded, so `make browser-stacks` has not been re-run.
- **`body-meta-512k` has no single Chrome answer.** Chrome guesses the encoding from the first
  network chunk that settles it, so the answer depends on the server and the network. From
  mojibake.wtf, Chrome 156 read windows-1252 on 42 of 46 loads and windows-874 on 4. The lab's own
  server, which writes the page in one call, gets windows-874. The case is captured live
  (`capture="live"`), so its reference is the majority answer from the real site.
- **Four cases are held back from mojibake.wtf** (`late-meta`, `past-4096`, `invalid-then-valid`,
  `x-user-defined`). Their decoy points at the fallback encoding, so deleting the declaration
  doesn't change the answer. The first three can move to a label nothing falls back to, as the
  depth demos did. `x-user-defined` can't, because its target is windows-1252 by definition.
- **Nine iframe cells store the inherited charset.** `indented-bom`, `vertical-tab`, `nul-split`,
  `noscript`, `template`, `foster`, `bogus-comment`, `endtag-attr` and `truncated-tag` grade
  correctly, but their `charset` field is the harness page's UTF-8. Capture them top-level before
  quoting a charset.
- **The browser column spans two Chrome builds.** Recapturing every case in one build would remove
  that caveat.

Readers worth adding: `httpx` (its `.text` rules differ from requests'), `pandas.read_html`,
`trafilatura`, `@crawlee/linkedom` and a `curl | iconv` pipeline.
