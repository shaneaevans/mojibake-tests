PY := .venv/bin/python
PORT ?= 8765

# Every version here IS a measurement subject, exactly like the pins in requirements.txt: these
# libraries disagree with each other and with the browser, so a bump moves a column.
JSOUP_VERSION ?= 1.24.1
GSON_VERSION ?= 2.15.0
MAVEN ?= https://repo1.maven.org/maven2

.PHONY: help bootstrap py-bootstrap js-bootstrap java-bootstrap serve browser capture-top \
        audit-nav discriminate matrix summary demo verify-crawlee export-site verify-live browser-stacks pinned-stacks clean

help:
	@echo "bootstrap       venv + deps + the Node and JVM readers"
	@echo "serve           serve the cases on :$(PORT) (browser harness at /)"
	@echo "browser         serve, then open http://127.0.0.1:$(PORT)/ to capture the iframe cases"
	@echo "capture-top     headless Chrome, one top-level navigation per nav=top-level case"
	@echo "audit-nav       every case iframe AND top-level in one build; fails on an undeclared split"
	@echo "discriminate    fails on any decoy case whose honoured and ignored readings coincide"
	@echo "matrix          full reader x case matrix (joins results/browser.json if present)"
	@echo "summary         distinct answers per case + who disagrees with the browser"
	@echo "demo            run the assembled demo pages through every reader"
	@echo "verify-crawlee  check the crawlee(*) columns against a real crawler over real HTTP"
	@echo "browser-stacks  the browser-driven stacks (Playwright, Selenium, scrapy-playwright...) over real HTTP"
	@echo "pinned-stacks   other versions: Scrapy 2.19.0 on w3lib 2.4.1 and 2.5.0, the Frostwork checkout"
	@echo ""
	@echo "Maintaining mojibake.wtf (contributors can ignore these):"
	@echo "export-site     SITE=<dir>: write the public corpus to <dir>/data/cases.json"
	@echo "verify-live     fetch every public case from $(LIVE) and fail on any byte or header change"

bootstrap: py-bootstrap js-bootstrap java-bootstrap

py-bootstrap:
	python3 -m venv .venv
	.venv/bin/pip install -q -U pip
	.venv/bin/pip install -q -r requirements.txt

# The JS and JVM readers are optional: without them those columns report
# ERR per cell rather than vanishing, so the ratio a sweep prints stays honest.
js-bootstrap:
	@command -v node >/dev/null || { echo "SKIP js: node not on PATH (the JS columns will ERR)"; exit 0; }
	cd js && npm install --no-audit --no-fund --loglevel=error

java-bootstrap:
	@command -v javac >/dev/null || { echo "SKIP java: javac not on PATH (the JVM columns will ERR)"; exit 0; }
	@mkdir -p java/lib java/build
	@test -f java/lib/jsoup-$(JSOUP_VERSION).jar || \
	  curl -sSL -o java/lib/jsoup-$(JSOUP_VERSION).jar \
	    $(MAVEN)/org/jsoup/jsoup/$(JSOUP_VERSION)/jsoup-$(JSOUP_VERSION).jar
	@test -f java/lib/gson-$(GSON_VERSION).jar || \
	  curl -sSL -o java/lib/gson-$(GSON_VERSION).jar \
	    $(MAVEN)/com/google/code/gson/gson/$(GSON_VERSION)/gson-$(GSON_VERSION).jar
	javac -cp "java/lib/*" -d java/build java/Reader.java

serve:
	$(PY) -m mojibake_tests.serve

browser:
	@echo "starting server; open http://127.0.0.1:$(PORT)/ in the browser you want to measure."
	@echo "the page loads every nav=iframe case in a same-origin iframe and merges the answers"
	@echo "into results/browser.json. An iframe with no charset declaration INHERITS the parent's"
	@echo "encoding, so the nav=top-level cases are not loaded here: \`make capture-top\` does them."
	$(PY) -m mojibake_tests.serve

# CHROME=<binary> to measure another build; CAPTURE_LANG=<tag> for another locale.
capture-top:
	$(PY) -m mojibake_tests.capture

audit-nav:
	$(PY) -m mojibake_tests.capture --audit

discriminate:
	$(PY) -m mojibake_tests.discriminate --browser

matrix:
	$(PY) -m mojibake_tests.report

summary:
	$(PY) -m mojibake_tests.summary

demo:
	$(PY) -m mojibake_tests.report demo-price demo-range demo-stock

# The crawlee(*) columns reach Crawlee's own decoder past a transcription of one module-private
# function. This is what keeps that transcription honest: same corpus, real crawler, real HTTP.
verify-crawlee:
	$(PY) -m mojibake_tests.verify_crawlee

# mojibake.wtf serves the corpus from a Cloudflare Worker in $(SITE). verify-live checks the
# deployed site against cases.py, so neither the export nor any hop in between can change a byte
# without failing it. LIVE=http://127.0.0.1:8787 checks `wrangler dev` instead.
LIVE ?= https://mojibake.wtf
export-site:
	@test -n "$(SITE)" || { echo "set SITE=<path to the mojibake.wtf checkout>"; exit 1; }
	$(PY) -m mojibake_tests.export_site $(SITE)

verify-live:
	$(PY) -m mojibake_tests.verify_live $(LIVE)

# Needs requirements-browsers.txt installed and `playwright install chromium firefox webkit`.
browser-stacks:
	$(PY) -m mojibake_tests.browser_stacks

# Stacks at other versions than requirements.txt: Scrapy 2.19.0 on w3lib 2.4.1 and 2.5.0, and the
# unreleased Frostwork built in FROSTWORK_CHECKOUT (default: a `frostwork` checkout next to this one).
pinned-stacks:
	$(PY) -m mojibake_tests.pinned_sweep

clean:
	rm -rf .venv **/__pycache__ js/node_modules java/build java/lib/*.jar
