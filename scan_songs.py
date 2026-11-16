
import csv
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from bs4 import BeautifulSoup

# ==========================================
# CONFIGURATION
# ==========================================

BASE = "https://djpunjab.is"

START_ID = 0
END_ID = 9

DELAY_SECONDS = 3

CSV_FILE = "songs.csv"

USER_AGENT = "PersonalMusicCatalogResearch/1.0"

FIELDS = [
    "song_id",
    "title",
    "artist",
    "album",
    "url"
]


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def log(message):
    print(message, flush=True)


def clean(value):
    return re.sub(
        r"\s+", " ", str(value or "")
    ).strip()


def get_labeled_value(soup, label):
    """
    Extract fields such as:

    Track : Taithon Door Sohniya Ve
    Artist : Kuldeep Rasila
    Album : Taithon Door Sohniya Ve
    Playtime : 5:23 min
    """

    text = soup.get_text(" ", strip=True)

    pattern = re.compile(
        rf"\b{re.escape(label)}\s*:\s*(.*?)"
        rf"(?=\s+(?:Track|Artist|Album|Playtime)\s*:|$)",
        re.I
    )

    match = pattern.search(text)

    if match:
        return clean(match.group(1))

    return ""


def extract_song(song_id, html, final_url):
    """
    Extract metadata from a valid song page.
    """

    soup = BeautifulSoup(html, "html.parser")

    # Verify that the final URL contains
    # the requested song ID.
    path = urllib.parse.urlparse(final_url).path

    match = re.search(
        r"(?:/song/|mp3-song-)(\d+)(?:\.html)?/?$",
        path,
        re.I
    )

    if not match:
        return None, "Invalid song URL"

    if int(match.group(1)) != song_id:
        return None, "Song ID mismatch"

    # Extract actual page fields
    title = get_labeled_value(soup, "Track")
    artist = get_labeled_value(soup, "Artist")
    album = get_labeled_value(soup, "Album")

    if not title:
        return None, "Track title missing"

    song = {
        "song_id": str(song_id),
        "title": title,
        "artist": artist,
        "album": album,
        "url": final_url
    }

    return song, "OK"


def check_robots():
    """
    Verify website crawling rules.
    """

    url = BASE + "/robots.txt"

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT}
    )

    try:
        with urllib.request.urlopen(
            request, timeout=15
        ) as response:
            content = response.read().decode(
                "utf-8", "replace"
            )

        robots = urllib.robotparser.RobotFileParser()
        robots.parse(content.splitlines())

        log("robots.txt checked successfully")

        return robots

    except Exception as e:
        log(f"robots.txt ERROR: {e}")
        return None


def load_existing():
    """
    Load previously discovered songs.
    """

    songs = {}

    try:
        with open(
            CSV_FILE,
            newline="",
            encoding="utf-8"
        ) as file:

            reader = csv.DictReader(file)

            for row in reader:
                sid = row.get("song_id", "")

                if sid.isdigit():
                    songs[sid] = {
                        field: row.get(field, "")
                        for field in FIELDS
                    }

        log(f"Loaded {len(songs)} existing songs")

    except FileNotFoundError:
        log("No existing CSV. Creating new database.")

    return songs


def save_csv(songs):
    """
    Save all songs sorted by song ID.
    """

    with open(
        CSV_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS
        )

        writer.writeheader()

        for sid in sorted(songs, key=int):
            writer.writerow(songs[sid])

    log(
        f"CSV saved successfully: {len(songs)} songs"
    )


# ==========================================
# MAIN SCANNER
# ==========================================

def main():

    log("================================")
    log("DJ PUNJAB SONG SCANNER")
    log(f"Scanning IDs {START_ID} to {END_ID}")
    log("================================")

    robots = check_robots()

    if robots is None:
        log("Cannot verify crawling rules. Stopping.")
        return

    songs = load_existing()

    found = 0
    not_found = 0
    errors = 0
    skipped = 0

    for sid in range(START_ID, END_ID + 1):

        url = f"{BASE}/song/{sid}"

        if not robots.can_fetch(USER_AGENT, url):
            skipped += 1
            log(
                f"[{sid:03d}] SKIPPED | robots.txt"
            )
            continue

        try:

            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=15
            ) as response:

                html = response.read().decode(
                    "utf-8", "replace"
                )

                final_url = response.geturl()
                status = response.status

            song, reason = extract_song(
                sid,
                html,
                final_url
            )

            if song:

                songs[str(sid)] = song
                found += 1

                log(
                    f"[{sid:03d}] FOUND | "
                    f"HTTP {status} | "
                    f"Title: {song['title']} | "
                    f"Artist: {song['artist'] or 'Unknown'} | "
                    f"Album: {song['album'] or 'Unknown'}"
                )

            else:

                not_found += 1

                log(
                    f"[{sid:03d}] NOT FOUND | "
                    f"{reason}"
                )

        except urllib.error.HTTPError as e:

            if e.code == 404:

                not_found += 1

                log(
                    f"[{sid:03d}] NOT FOUND | HTTP 404"
                )

            else:

                errors += 1

                log(
                    f"[{sid:03d}] ERROR | HTTP {e.code}"
                )

                if e.code in (403, 429):
                    log("Access restricted. Stopping.")
                    break

        except Exception as e:

            errors += 1

            log(
                f"[{sid:03d}] ERROR | {e}"
            )

            break

        time.sleep(DELAY_SECONDS)

    save_csv(songs)

    log("")
    log("========== SCAN SUMMARY ==========")
    log(f"Found:       {found}")
    log(f"Not found:   {not_found}")
    log(f"Errors:      {errors}")
    log(f"Skipped:     {skipped}")
    log(f"CSV records: {len(songs)}")
    log("==================================")


if __name__ == "__main__":
    main()
