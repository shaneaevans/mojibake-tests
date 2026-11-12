"""A page a site could serve to feed bots a WRONG price — no bot detection, no cloaking, one
response for everybody.

The visible number and the extracted number differ because the two readers disagree about how many
DIGITS the bytes contain.

**The mechanism.** GB18030's four-byte form is `(0x81-0xFE, 0x30-0x39, 0x81-0xFE, 0x30-0x39)` —
bytes 2 and 4 are ASCII digits. Choose `0xAD` as the lead: in windows-1252 that is SOFT HYPHEN,
which every browser renders as nothing. So the four bytes `AD 32 AD 39` are:

    windows-1252  ->  <invisible> 2 <invisible> 9     a person reads the digits "29"
    gb18030       ->  one CJK character                a scraper reads no digits at all

Wrap that in a price and the same element says two things:

    bytes:         31  AD 32 AD 39  39 2C 30 30
    browser:       "1" + (inv)2(inv)9 + "9,00"   -> renders  1299,00
    gb18030:       "1" + <one CJK char> + "9,00" -> strips to   19,00

**Steering the two readers apart.** A `<meta charset>` inside a COMMENT: w3lib has no comment
handling and takes its first regex hit, so Scrapy decodes the page as gb18030. WHATWG's prescan
skips comments, so the browser reaches the real `<meta charset=windows-1252>` after it.

Nothing here is malformed, nothing is hidden behind a User-Agent check, and a diff of the served
HTML against what the browser shows reveals nothing: the bytes really do mean both things.
"""

NAME = "fake price"
CONTENT_TYPE = "text/html"          # deliberately no charset: the decoy has to win on its own
NOTE = ("gb18030 4-byte form swallows two digits that windows-1252 renders as invisible soft "
        "hyphens; a commented-out <meta charset> steers w3lib away from the browser's answer")

_SHY = 0xAD


def _digits(prefix, d1, d2, suffix):
    """`prefix` + two digits only a windows-1252 reader can see + `suffix`."""
    return prefix + bytes([_SHY, ord(d1), _SHY, ord(d2)]) + suffix


# 1299,00 to a person; 19,00 to a gb18030 reader.
PRICE = _digits(b"1", "2", "9", b"9,00")
# 4,7 stars to a person; 4,7 -> 47 is not the interesting one, so the rating carries the same trick
# in the other direction: 4,9 visible, 4 to a scraper.
RATING = _digits(b"4,", "9", "1", b"")

BODY = (
    b'<!DOCTYPE html>\n'
    b'<html lang="de">\n'
    b'<head>\n'
    b'  <!-- <meta charset="gb18030"> -->\n'
    b'  <meta charset="windows-1252">\n'
    b'  <title>Aurora 14 Notebook</title>\n'
    b'</head>\n'
    b'<body>\n'
    b'  <h1 class="name">Aurora 14 Notebook</h1>\n'
    b'  <div class="offer">\n'
    b'    <span class="price">' + PRICE + b' \x80</span>\n'
    b'    <span class="rating">' + RATING + b'</span>\n'
    b'  </div>\n'
    b'</body>\n'
    b'</html>\n'
)

TITLES = {
    "fake-price": "a commented-out gb18030 <meta> and soft hyphens inside a price",
    "fake-rating": "the same trick inside a star rating",
}

CASES = [
    ("fake-price", ".price::text"),
    ("fake-rating", ".rating::text"),
]

# Measured (Chrome 148 / en-GB). `.price::text`, 6 distinct answers across 12 readers:
#
#   browser                     1<SHY>2<SHY>99,00 EUR   renders 1299,00 EUR
#   scrapy(w3lib+parsel)        1<one CJK char>9,00     strips to     19,00     <== the wrong price
#   selectolax(lexbor)          1<one CJK char>9,00     strips to     19,00
#   frostwork / lxml / html5lib 1<SHY>2<SHY>99,00 EUR   agrees with the browser
#   requests.text+lxml / +bs4   1<SHY>2<SHY>99,00 \x80  right digits, euro sign lost
#   parsel(body=) / regex       1<?>2<?>99,00           UTF-8 default, soft hyphen is invalid UTF-8
#   requests+apparent / dammit  1!2!99,00 C             charset_normalizer guessed a third encoding
#
# The rendering claim is measured, not assumed: the price element's rendered width is 67.90625px,
# exactly the width of the string "1299,00 EUR" and not of any spelling where the separators are
# visible. The soft hyphens occupy no space at all.
