"""A real Scrapy crawl through scrapy-playwright: `python -m mojibake_tests.scrapy_playwright_sweep
<base-url> <out.json>`, with the case list as JSON on stdin.

Configured the way scrapy-playwright's README says: its download handler for http and https, the
asyncio reactor, and `meta={"playwright": True}` on each request. The callback uses
`response.css(...).getall()`, which runs on the HtmlResponse scrapy-playwright builds from
`page.content()`: the browser's DOM serialised to HTML, then re-parsed by Scrapy's own parser.
Run in its own process because a Twisted reactor cannot be restarted.
"""
import json
import sys

import scrapy
from scrapy.crawler import CrawlerProcess

BASE, OUT = sys.argv[1], sys.argv[2]
CASES = json.load(sys.stdin)
RESULTS = {}


class CaseSpider(scrapy.Spider):
    name = "mojibake-cases"

    async def start(self):
        for c in CASES:
            yield scrapy.Request("%s/c/%s" % (BASE, c["id"]), meta={"playwright": True, "case": c},
                                 dont_filter=True, callback=self.parse, errback=self.failed)

    def parse(self, response):
        c = response.meta["case"]
        RESULTS[c["id"]] = response.css(c["sel"]).getall()

    def failed(self, failure):
        c = failure.request.meta["case"]
        RESULTS[c["id"]] = ["ERR:" + repr(failure.value)[:90]]


process = CrawlerProcess(settings={
    "DOWNLOAD_HANDLERS": {
        "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    },
    "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    "LOG_LEVEL": "ERROR",
    "CONCURRENT_REQUESTS": 8,
    "RETRY_ENABLED": False,
    "TELNETCONSOLE_ENABLED": False,
})
process.crawl(CaseSpider)
process.start()
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(RESULTS, f, ensure_ascii=False)
