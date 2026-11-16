
import csv
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

BASE = "https://djpunjab.is"
START_ID = 0
END_ID = 99
DELAY_SECONDS = 3
CSV_FILE = "songs.csv"

FIELDS = ["song_id", "title", "artist", "album", "url"]


class SongParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.page_title = ""

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.page_title += data


def extract_song(song_id, html, final_url):
    parser = SongParser()
    parser.feed(html)

    path = urllib.parse.urlparse(final_url).path

    match = re.search(
        r"(?:/song/|mp3-song-)(\d+)(?:\.html)?/?$",
        path,
        re.I
    )

    if not match or int(match.group(1)) != song_id:
        return None, "Redirected or invalid song URL"

    title_match = re.match(
        r"(.+?)\s+mp3 song download\b",
        parser.page_title.strip(),
        re.I
    )

    if not title_match:
        return None, "No recognizable song title"

    song = {
        "song_id": str(song_id),
        "title": title_match.group(1).strip(),
        "artist": "",
        "album": "",
        "url": final_url
    }

    return song, "Valid song page"


def main():
    robots = urllib.robotparser.RobotFileParser()
    robots.set_url(BASE + "/robots.txt")

    try:
        robots.read()
        if robots.mtime() == 0:
            print("ERROR: Could not verify robots.txt", flush=True)
            return
    except Exception as e:
        print(f"ERROR: robots.txt: {e}", flush=True)
        return

    existing = {}

    try:
        with open(CSV_FILE, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["song_id"]] = row
    except FileNotFoundError:
        pass

    found = 0
    not_found = 0
    errors = 0

    print(
        f"Starting scan: IDs {START_ID} to {END_ID}",
        flush=True
    )

    for song_id in range(START_ID, END_ID + 1):
        url = f"{BASE}/song/{song_id}"

        if not robots.can_fetch("*", url):
            print(
                f"[{song_id:03d}] SKIPPED | Disallowed by robots.txt",
                flush=True
            )
            continue

        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "PersonalMusicCatalogResearch/1.0"
                }
            )

            with urllib.request.urlopen(
                request, timeout=15
            ) as response:
                status = response.status
                final_url = response.geturl()
                html = response.read().decode(
                    "utf-8", errors="replace"
                )

            song, reason = extract_song(
                song_id, html, final_url
            )

            if song:
                existing[str(song_id)] = song
                found += 1

                print(
                    f"[{song_id:03d}] FOUND | HTTP {status} | "
                    f"Title: {song['title']} | "
                    f"Artist: {song['artist'] or 'Unknown'} | "
                    f"URL: {song['url']}",
                    flush=True
                )
            else:
                not_found += 1
                print(
                    f"[{song_id:03d}] NOT FOUND | HTTP {status} | "
                    f"{reason}",
                    flush=True
                )

        except urllib.error.HTTPError as e:
            if e.code == 404:
                not_found += 1
                print(
                    f"[{song_id:03d}] NOT FOUND | HTTP 404",
                    flush=True
                )
            else:
                errors += 1
                print(
                    f"[{song_id:03d}] ERROR | HTTP {e.code}",
                    flush=True
                )

                if e.code in (403, 429):
                    print(
                        "Access restricted. Stopping scan.",
                        flush=True
                    )
                    break

        except Exception as e:
            errors += 1
            print(
                f"[{song_id:03d}] ERROR | {e}",
                flush=True
            )
            print(
                "Stopping after unexpected error.",
                flush=True
            )
            break

        time.sleep(DELAY_SECONDS)

    with open(
        CSV_FILE, "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()

        for key in sorted(existing, key=int):
            writer.writerow(existing[key])

    print("\n========== SCAN SUMMARY ==========", flush=True)
    print(f"Songs found: {found}", flush=True)
    print(f"Not found:   {not_found}", flush=True)
    print(f"Errors:      {errors}", flush=True)
    print(f"CSV records: {len(existing)}", flush=True)
    print("==================================", flush=True)


if __name__ == "__main__":
    main()
