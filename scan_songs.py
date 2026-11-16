
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
USER_AGENT = "PersonalMusicCatalogResearch/1.0"

FIELDS = ["song_id", "title", "artist", "album", "url"]


class SongParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.page_title = ""
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "title":
            self.in_title = True

        if tag == "meta":
            key = attrs.get("property") or attrs.get("name")
            if key:
                self.meta[key.lower()] = attrs.get("content", "")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.page_title += data


def check_robots():
    url = BASE + "/robots.txt"

    print(f"Checking robots.txt: {url}", flush=True)

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT}
    )

    try:
        with urllib.request.urlopen(
            request, timeout=15
        ) as response:
            status = response.status
            content = response.read().decode(
                "utf-8", errors="replace"
            )

        print(f"robots.txt HTTP: {status}", flush=True)
        print("robots.txt contents:", flush=True)
        print(content[:2000], flush=True)

        robots = urllib.robotparser.RobotFileParser()
        robots.parse(content.splitlines())

        return robots

    except urllib.error.HTTPError as e:
        print(
            f"robots.txt HTTP error: {e.code}",
            flush=True
        )
        return None

    except Exception as e:
        print(
            f"robots.txt request failed: {e}",
            flush=True
        )
        return None


def extract_song(song_id, html, final_url):
    parser = SongParser()
    parser.feed(html)

    path = urllib.parse.urlparse(final_url).path

    match = re.search(
        r"(?:/song/|mp3-song-)(\d+)(?:\.html)?/?$",
        path,
        re.I
    )

    if not match:
        return None, "Not a recognized song URL"

    if int(match.group(1)) != song_id:
        return None, "Song ID mismatch"

    page_title = parser.page_title.strip()

    title_match = re.match(
        r"(.+?)\s+mp3 song download\b",
        page_title,
        re.I
    )

    if not title_match:
        return None, "No recognizable song title"

    # Do not guess where title ends and artist begins.
    combined_title = title_match.group(1).strip()

    song = {
        "song_id": str(song_id),
        "title": combined_title,
        "artist": "",
        "album": "",
        "url": final_url
    }

    return song, "Valid song page"


def load_existing():
    existing = {}

    try:
        with open(
            CSV_FILE, newline="", encoding="utf-8"
        ) as file:
            reader = csv.DictReader(file)

            for row in reader:
                song_id = row.get("song_id", "")

                if song_id.isdigit():
                    existing[song_id] = {
                        field: row.get(field, "")
                        for field in FIELDS
                    }

        print(
            f"Loaded {len(existing)} existing records",
            flush=True
        )

    except FileNotFoundError:
        print(
            "No existing CSV. Starting new database.",
            flush=True
        )

    return existing


def save_csv(existing):
    with open(
        CSV_FILE, "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=FIELDS
        )
        writer.writeheader()

        for key in sorted(existing, key=int):
            writer.writerow(existing[key])

    print(
        f"Saved {len(existing)} records to {CSV_FILE}",
        flush=True
    )


def main():
    print("==================================", flush=True)
    print("DJ PUNJAB SONG SCANNER", flush=True)
    print(f"ID range: {START_ID} to {END_ID}", flush=True)
    print(f"Delay: {DELAY_SECONDS} seconds", flush=True)
    print("==================================", flush=True)

    existing = load_existing()
    robots = check_robots()

    if robots is None:
        print(
            "SCAN STOPPED: Could not verify crawling rules.",
            flush=True
        )
        save_csv(existing)
        return

    found = 0
    not_found = 0
    errors = 0
    skipped = 0

    for song_id in range(START_ID, END_ID + 1):
        url = f"{BASE}/song/{song_id}"

        if not robots.can_fetch(USER_AGENT, url):
            skipped += 1
            print(
                f"[{song_id:03d}] SKIPPED | robots.txt",
                flush=True
            )
            continue

        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT}
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
                    f"[{song_id:03d}] FOUND | "
                    f"HTTP {status} | "
                    f"Title: {song['title']} | "
                    f"URL: {song['url']}",
                    flush=True
                )
            else:
                not_found += 1

                print(
                    f"[{song_id:03d}] NOT FOUND | "
                    f"HTTP {status} | {reason}",
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
                        "Access restricted. Stopping.",
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
                "Unexpected error. Stopping.",
                flush=True
            )
            break

        time.sleep(DELAY_SECONDS)

    save_csv(existing)

    print("\n========== SCAN SUMMARY ==========", flush=True)
    print(f"Found:       {found}", flush=True)
    print(f"Not found:   {not_found}", flush=True)
    print(f"Errors:      {errors}", flush=True)
    print(f"Skipped:     {skipped}", flush=True)
    print(f"CSV records: {len(existing)}", flush=True)
    print("==================================", flush=True)


if __name__ == "__main__":
    main()
