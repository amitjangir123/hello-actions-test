
import urllib.request
from bs4 import BeautifulSoup

url = "https://djpunjab.is/song/4"

request = urllib.request.Request(
    url,
    headers={"User-Agent": "PersonalMusicCatalogResearch/1.0"}
)

with urllib.request.urlopen(request, timeout=15) as response:
    html = response.read().decode("utf-8", "replace")

soup = BeautifulSoup(html, "html.parser")

print("========== PAGE TITLE ==========")
print(soup.title.get_text(strip=True) if soup.title else "None")

print("\n========== META TAGS ==========")
for tag in soup.find_all("meta"):
    print(tag)

print("\n========== HEADINGS ==========")
for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
    print(tag.get_text(" ", strip=True))

print("\n========== STRUCTURED DATA ==========")
for tag in soup.find_all(
    "script", attrs={"type": "application/ld+json"}
):
    print(tag.get_text(strip=True)[:3000])

print("\n========== PAGE TEXT ==========")
print(soup.get_text(" ", strip=True)[:4000])
