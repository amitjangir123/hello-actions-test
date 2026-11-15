
import urllib.request
from html.parser import HTMLParser

url = "https://djpunjab.is/song/308243"

print("Connecting to:", url)

req = urllib.request.Request(
    url,
    headers={"User-Agent": "Mozilla/5.0"}
)

class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data

try:
    with urllib.request.urlopen(req, timeout=20) as response:
        html = response.read().decode("utf-8", errors="replace")
        print("HTTP status:", response.status)

    parser = TitleParser()
    parser.feed(html)

    print("Page title:", parser.title.strip())

except Exception as e:
    print("Error:", e)
    raise
