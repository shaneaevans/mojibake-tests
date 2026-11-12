# Contributing

Pull requests are welcome, especially a reader for a stack that isn't here yet, a case that splits
the readers in a way the corpus doesn't already show, or a correction to a measurement.

Every number in this repo came out of a run, so a pull request that changes a number has to show
the run. Paste the output of `make summary`, or `make matrix <case-id>` for a single case, from
before and after your change.

## Adding a reader

A reader is one `@reader("name", "note")` function in `mojibake_tests/readers.py`. It takes
`(content_type, body_bytes, selector)` and returns the list of strings the stack extracts.

- Drive the stack the way its users drive it. The `requests.text+bs4` column goes through a real
  `requests.Response`, because the point is what `requests`' own `.text` does.
- Pin the version in `requirements.txt` (or `js/package.json`, or the `Makefile` for the JVM).
  A version bump changes the answers, so the pin is part of the measurement.
- Extract text the way the browser probe does: the selected element's direct child text nodes,
  undecorated. A helper that collapses whitespace answers a different question.
- A reader in JavaScript or Java is one entry in `js/reader.js` or `java/Reader.java` plus one
  `_remote(...)` line in `readers.py`. Don't reimplement the stack's encoding decision in Python.
- An exception is an answer. Let it show as `ERR:` rather than catching it.

## Adding a case

A case is one `case(...)` call in `mojibake_tests/cases.py`: exact bytes, exact `Content-Type`, one
selector, and a note saying which readers you expect to get it wrong and why.

- If the right answer depends on the browser's fallback encoding, mark it `nav="top-level"`. An
  iframe inherits its parent's encoding, which hides the fallback.
- A decoy declaration must point at an encoding nothing falls back to, or a reader that ignores it
  lands on the same text by accident. `make discriminate` checks this.
- Capture the browser answer for the new case (`make browser` or `make capture-top`) and commit the
  updated `results/browser.json`. `make summary` won't grade a case without a browser cell measured
  on its current bytes.

A mechanism that turns out not to split the readers is still worth adding, with a note saying so.
That saves the next person from testing it again.

## Before you open the pull request

Run `make audit-nav` and `make discriminate` if you added or changed a case, and
`make verify-crawlee` if you touched a Crawlee column. [AGENTS.md](AGENTS.md) describes the traps
those checks exist for.
