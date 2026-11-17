
import csv
import json
import os
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

BATCH_SIZE = 100
DELAY_SECONDS = 0.001
CHECKPOINT_EVERY = 25

CSV_FILE = "songs.csv"
STATE_FILE = "scan_state.json"
HTTP400_FILE = "http400_ids.csv"

USER_AGENT = "PersonalMusicCatalogResearch/1.0"

FIELDS = [
    "song_id",
    "title",
    "artist",
    "album",
    "url"
]


# ==========================================
# HELPERS
# ==========================================

def log(message):
    print(message, flush=True)


def clean(value):
    return re.sub(
        r"\s+", " ", str(value or "")
    ).strip()


def atomic_write_json(path, data):
    temp = path + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

    os.replace(temp, path)


# ==========================================
# STATE MANAGEMENT
# ==========================================

def load_state():
    if not os.path.exists(STATE_FILE):
        log("No scan state found. Starting at ID 0.")
        return 0

    with open(STATE_FILE, encoding="utf-8") as f:
        state = json.load(f)

    next_id = state.get("next_id")

    if type(next_id) is not int or next_id < 0:
        raise ValueError(
            "Invalid next_id in scan_state.json"
        )

    log(f"Resuming from ID {next_id}")
    return next_id


def save_state(next_id):
    atomic_write_json(
        STATE_FILE,
        {"next_id": next_id}
    )


# ==========================================
# CSV DATABASE
# ==========================================

def load_existing():
    songs = {}

    if not os.path.exists(CSV_FILE):
        log("No existing CSV. Creating new database.")
        return songs

    with open(
        CSV_FILE, newline="", encoding="utf-8"
    ) as f:
        reader = csv.DictReader(f)

        if not reader.fieldnames or not set(
            FIELDS
        ).issubset(reader.fieldnames):
            raise ValueError("Invalid CSV columns")

        for row in reader:
            sid = row.get("song_id", "")

            if sid.isdigit():
                songs[sid] = {
                    field: row.get(field, "")
                    for field in FIELDS
                }

    log(f"Loaded {len(songs)} existing songs")
    return songs


def save_csv(songs):
    temp = CSV_FILE + ".tmp"

    with open(
        temp, "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=FIELDS
        )

        writer.writeheader()

        for sid in sorted(songs, key=int):
            writer.writerow(songs[sid])

        f.flush()
        os.fsync(f.fileno())

    os.replace(temp, CSV_FILE)


# ==========================================
# HTTP 400 TRACKING
# ==========================================

def load_http400_ids():
    ids = set()

    if not os.path.exists(HTTP400_FILE):
        return ids

    with open(
        HTTP400_FILE,
        newline="",
        encoding="utf-8"
    ) as f:
        reader = csv.DictReader(f)

        for row in reader:
            sid = row.get("song_id", "")
            if sid.isdigit():
                ids.add(int(sid))

    return ids


def save_http400_ids(ids):
    temp = HTTP400_FILE + ".tmp"

    with open(
        temp,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:
        writer = csv.writer(f)
        writer.writerow(["song_id"])

        for sid in sorted(ids):
            writer.writerow([sid])

        f.flush()
        os.fsync(f.fileno())

    os.replace(temp, HTTP400_FILE)


def checkpoint(songs, next_id, http400_ids):
    # Write data before advancing scan state.
    save_csv(songs)
    save_http400_ids(http400_ids)
    save_state(next_id)

    log(
        f"CHECKPOINT | Next ID: {next_id} | "
        f"Songs: {len(songs)} | "
        f"HTTP 400 IDs: {len(http400_ids)}"
    )


# ==========================================
# HTML PARSING
# ==========================================

def get_labeled_value(soup, label):
    text = soup.get_text(" ", strip=True)

    pattern = re.compile(
        rf"\b{re.escape(label)}\s*:\s*(.*?)"
        rf"(?=\s+(?:Track|Artist|Album|Playtime)\s*:|$)",
        re.I
    )

    match = pattern.search(text)

    return clean(match.group(1)) if match else ""


def extract_song(song_id, html, final_url):
    path = urllib.parse.urlparse(final_url).path

    match = re.search(
        r"(?:/song/|mp3-song-)(\d+)(?:\.html)?/?$",
        path,
        re.I
    )

    if not match or int(match.group(1)) != song_id:
        return None, "Invalid song URL"

    soup = BeautifulSoup(html, "html.parser")

    title = get_labeled_value(soup, "Track")
    artist = get_labeled_value(soup, "Artist")
    album = get_labeled_value(soup, "Album")

    if not title:
        return None, "Track title missing"

    return {
        "song_id": str(song_id),
        "title": title,
        "artist": artist,
        "album": album,
        "url": final_url
    }, "OK"


# ==========================================
# ROBOTS.TXT
# ==========================================

def check_robots():
    request = urllib.request.Request(
        BASE + "/robots.txt",
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


# ==========================================
# MAIN SCANNER
# ==========================================

def main():
    songs = load_existing()
    http400_ids = load_http400_ids()

    start_id = load_state()
    end_id = start_id + BATCH_SIZE - 1

    log("================================")
    log("DJ PUNJAB RESUMABLE CSV SCANNER")
    log(f"Scanning IDs {start_id} to {end_id}")
    log(f"Batch size: {BATCH_SIZE}")
    log("================================")

    robots = check_robots()

    if robots is None:
        raise RuntimeError(
            "Cannot verify crawling rules"
        )

    found = 0
    not_found = 0
    errors = 0
    skipped = 0
    completed = 0

    next_id = start_id

    try:
        for sid in range(start_id, end_id + 1):
            url = f"{BASE}/song/{sid}"

            if not robots.can_fetch(USER_AGENT, url):
                skipped += 1
                log(
                    f"[{sid:06d}] SKIPPED | robots.txt"
                )
                break

            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": USER_AGENT}
                )

                with urllib.request.urlopen(
                    request, timeout=15
                ) as response:
                    html = response.read().decode(
                        "utf-8", "replace"
                    )
                    final_url = response.geturl()
                    status = response.status

                song, reason = extract_song(
                    sid, html, final_url
                )

                if song:
                    old = songs.get(str(sid), {})

                    for field in ("artist", "album"):
                        if not song[field]:
                            song[field] = old.get(field, "")

                    songs[str(sid)] = song
                    found += 1

                    log(
                        f"[{sid:06d}] FOUND | "
                        f"HTTP {status} | "
                        f"Title: {song['title']} | "
                        f"Artist: {song['artist'] or 'Unknown'} | "
                        f"Album: {song['album'] or 'Unknown'}"
                    )

                elif reason == "Invalid song URL":
                    not_found += 1
                    log(
                        f"[{sid:06d}] NOT FOUND | "
                        f"{reason}"
                    )

                else:
                    errors += 1
                    log(
                        f"[{sid:06d}] UNPARSED | {reason}"
                    )
                    break

            except urllib.error.HTTPError as e:
                if e.code in (400, 404):
                    not_found += 1

                    if e.code == 400:
                        http400_ids.add(sid)

                    log(
                        f"[{sid:06d}] NOT FOUND | "
                        f"HTTP {e.code}"
                    )
                else:
                    errors += 1
                    log(
                        f"[{sid:06d}] ERROR | "
                        f"HTTP {e.code}"
                    )

                    if e.code in (403, 429):
                        log("Access restricted. Stopping.")

                    break

            except Exception as e:
                errors += 1
                log(
                    f"[{sid:06d}] ERROR | {e}"
                )
                break

            # Advance after FOUND, 400, 404,
            # or a recognized invalid song URL.
            next_id = sid + 1
            completed += 1

            if completed % CHECKPOINT_EVERY == 0:
                checkpoint(
                    songs, next_id, http400_ids
                )

            if sid < end_id:
                time.sleep(DELAY_SECONDS)

    finally:
        checkpoint(
            songs, next_id, http400_ids
        )

        log("")
        log("========== SCAN SUMMARY ==========")
        log(f"Found:       {found}")
        log(f"Not found:   {not_found}")
        log(f"Errors:      {errors}")
        log(f"Skipped:     {skipped}")
        log(f"Processed:   {completed}")
        log(f"CSV records: {len(songs)}")
        log(f"HTTP 400 IDs: {len(http400_ids)}")
        log(f"Next ID:     {next_id}")
        log("==================================")


if __name__ == "__main__":
    main()
