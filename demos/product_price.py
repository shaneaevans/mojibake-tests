"""A product page that quotes a DIFFERENT price to a browser than to a scraper, with no mojibake
to give it away.

Three independent mechanisms, each sufficient on its own:

  1. <template>     the browser puts template children in a DocumentFragment: never rendered, never
                    matched by querySelector. Every HTML-parsing scraper treats them as ordinary
                    descendants -- and the decoy is FIRST in document order, so `.get()` takes it.
  2. charset label  `iso-8859-1` MEANS windows-1252 to every browser (the WHATWG label table), where
                    0x80 is EURO SIGN and 0x96 is EN DASH. Python's literal `latin_1` codec makes
                    them U+0080 / U+0096 -- invisible C1 controls. The currency symbol disappears and
                    the price RANGE `1.999-2.499` collapses into the number `1.9992.499`.
  3. <noscript>     rawtext when scripting is enabled (a browser), real markup to every parser.
"""

NAME = "product page"
CONTENT_TYPE = "text/html; charset=iso-8859-1"
NOTE = "template decoy + iso-8859-1 label + noscript, in one realistic page"

BODY = (
    b'<!DOCTYPE html>\n'
    b'<html lang="en">\n'
    b'<head>\n'
    b'  <title>Aurora 14 Laptop</title>\n'
    b'</head>\n'
    b'<body>\n'
    b'  <h1 class="name">Aurora 14 Laptop</h1>\n'
    b'\n'
    b'  <template>\n'
    b'    <div class="product">\n'
    b'      <span class="price">1.099,00 \x80</span>\n'
    b'      <span class="stock">In stock</span>\n'
    b'    </div>\n'
    b'  </template>\n'
    b'\n'
    b'  <div class="product">\n'
    b'    <span class="price">2.499,00 \x80</span>\n'
    b'    <span class="range">1.999\x962.499</span>\n'
    b'    <span class="stock">In stock</span>\n'
    b'  </div>\n'
    b'\n'
    b'  <noscript><span class="stock">Out of stock</span></noscript>\n'
    b'</body>\n'
    b'</html>\n'
)

TITLES = {
    "demo-price": "product page: a <template> price, an iso-8859-1 label and a <noscript>",
    "demo-range": "product page: a price range joined by 0x96",
    "demo-stock": "product page: stock level, with a second one in <noscript>",
}

CASES = [
    ("demo-price", ".price::text"),
    ("demo-range", ".range::text"),
    ("demo-stock", ".stock::text"),
]

# Measured (Chrome 148 / en-GB):
#
#   selector          browser        scrapy/parsel .get()   raw parsel / lxml / bs4
#   .price::text      2.499,00 EUR   1.099,00 EUR           1.099,00 <U+0080>
#   .range::text      1.999-2.499    1.999-2.499            1.9992.499
#   .stock::text      In stock       In stock (3 nodes)     In stock (3 nodes)
