
import csv
import json
import os
import re
import sys
import time
import subprocess
import urllib.robotparser
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURATION
# ==========================================

BASE = "https://djpunjab.is"

BATCH_SIZE = 300000
DELAY_SECONDS = 0.001
CHECKPOINT_EVERY = 25
PUSH_EVERY = 100

CSV_FILE = "songs.csv"
STATE_FILE = "scan_state.json"
HTTP400_FILE = "http400_ids.csv"

USER_AGENT = "PersonalMusicCatalogResearch/1.0"
REQUEST_TIMEOUT = (5, 15)
MAX_HTML_BYTES = 2 * 1024 * 1024

FIELDS = ["song_id", "title", "artist", "album", "url"]

COLS = (12, 8, 12, 8, 27, 22, 22)


# ==========================================
# LOGGING
# ==========================================

def log(message):
    sys.stdout.write(str(message).rstrip() + "\n")
    sys.stdout.flush()


def shorten(value, width):
    value = str(value or "-")
    if len(value) > width - 1:
        return value[:width - 4] + "..."
    return value


def print_header():
    headers = (
        "PROGRESS", "ID", "STATUS", "TIME",
        "SONG TITLE", "ARTIST", "ALBUM"
    )

    line = "".join(
        f"{name:<{width}}"
        for name, width in zip(headers, COLS)
    )

    log(line)
    log("-" * sum(COLS))


def print_row(
    progress,
    sid,
    status,
    elapsed,
    title="-",
    artist="-",
    album="-"
):
    values = (
        progress,
        f"{sid:06d}",
        status,
        f"{elapsed:.2f}s",
        title,
        artist,
        album
    )

    line = "".join(
        f"{shorten(value, width):<{width}}"
        for value, width in zip(values, COLS)
    )

    log(line)


def clean(value):
    return re.sub(
        r"\s+", " ", str(value or "")
    ).strip()


# ==========================================
# STATE MANAGEMENT
# ==========================================

def atomic_write_json(path, data):
    temp = path + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

    os.replace(temp, path)


def load_state():
    if not os.path.exists(STATE_FILE):
        log("No scan state found. Starting at ID 0.")
        return 0

    with open(STATE_FILE, encoding="utf-8") as f:
        state = json.load(f)

    next_id = state.get("next_id")

    if type(next_id) is not int or next_id < 0:
        raise ValueError("Invalid next_id")

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
        log("Creating new CSV database.")
        return songs

    with open(
        CSV_FILE,
        newline="",
        encoding="utf-8"
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

    log(f"Loaded {len(songs)} songs")
    return songs


def save_csv(songs):
    temp = CSV_FILE + ".tmp"

    with open(
        temp,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=FIELDS
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
        for row in csv.DictReader(f):
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
    save_csv(songs)
    save_http400_ids(http400_ids)
    save_state(next_id)

    log(
        f"CHECKPOINT | Next ID: {next_id} | "
        f"Songs: {len(songs)} | "
        f"HTTP 400: {len(http400_ids)}"
    )


# ==========================================
# GITHUB PUSH
# ==========================================

def push_to_github():
    log("")
    log("========== GITHUB SYNC ==========")

    subprocess.run(
        [
            "git", "add",
            CSV_FILE,
            STATE_FILE,
            HTTP400_FILE
        ],
        check=True
    )

    changes = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        check=False
    )

    if changes.returncode == 0:
        log("No changes to push")
        return

    if changes.returncode != 1:
        raise RuntimeError("Git diff failed")

    subprocess.run(
        [
            "git", "commit",
            "-m",
            "[skip ci] Update song database and scan state"
        ],
        check=True
    )

    subprocess.run(
        [
            "git", "push",
            "origin",
            "HEAD:main"
        ],
        check=True
    )

    log("GitHub push successful")
    log("=================================")
    log("")


# ==========================================
# HTML PARSING
# ==========================================

FIELD_PATTERN = re.compile(
    r"\b(Track|Artist|Album|Playtime)\s*:\s*(.*?)"
    r"(?=\s+(?:Track|Artist|Album|Playtime)\s*:|$)",
    re.I
)

SONG_URL_PATTERN = re.compile(
    r"(?:/song/|mp3-song-)(\d+)(?:\.html)?/?$",
    re.I
)


def extract_song(song_id, html, final_url):
    path = urlparse(final_url).path

    match = SONG_URL_PATTERN.search(path)

    if not match or int(match.group(1)) != song_id:
        return None, "Invalid song URL"

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    values = {}

    for match in FIELD_PATTERN.finditer(text):
        key = match.group(1).lower()

        if key not in values:
            values[key] = clean(match.group(2))

    title = values.get("track", "")
    artist = values.get("artist", "")
    album = values.get("album", "")

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
# HTTP SESSION
# ==========================================

def create_session():
    session = requests.Session()

    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml"
    })

    adapter = requests.adapters.HTTPAdapter(
        pool_connections=2,
        pool_maxsize=2,
        max_retries=0
    )

    session.mount("https://", adapter)

    return session


def check_robots(session):
    try:
        response = session.get(
            BASE + "/robots.txt",
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        robots = urllib.robotparser.RobotFileParser()
        robots.parse(response.text.splitlines())

        log("robots.txt checked successfully")
        return robots

    except requests.RequestException as e:
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

    log("=" * 60)
    log("DJ PUNJAB CSV SCANNER")
    log(f"Scanning IDs: {start_id} to {end_id}")
    log(f"Batch size: {BATCH_SIZE}")
    log(f"Push every: {PUSH_EVERY} IDs")
    log("=" * 60)

    session = create_session()

    found = 0
    not_found = 0
    errors = 0
    skipped = 0
    completed = 0

    next_id = start_id
    interrupted = False
    started_at = time.perf_counter()

    try:
        robots = check_robots(session)

        if robots is None:
            raise RuntimeError(
                "Cannot verify crawling rules"
            )

        print_header()

        for sid in range(start_id, end_id + 1):
            progress = (
                f"{sid - start_id + 1:05d}/{BATCH_SIZE}"
            )

            url = f"{BASE}/song/{sid}"

            if not robots.can_fetch(USER_AGENT, url):
                skipped += 1
                interrupted = True
                log(
                    f"[{sid:06d}] SKIPPED | robots.txt"
                )
                break

            request_start = time.perf_counter()

            try:
                response = session.get(
                    url,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                    stream=True
                )

                status = response.status_code
                html = b""

                if status == 200:
                    for chunk in response.iter_content(
                        chunk_size=16384
                    ):
                        html += chunk

                        if len(html) > MAX_HTML_BYTES:
                            raise ValueError(
                                "HTML response too large"
                            )

                final_url = response.url
                response.close()

                elapsed = (
                    time.perf_counter() - request_start
                )

                if status in (400, 404):
                    not_found += 1

                    if status == 400:
                        http400_ids.add(sid)

                    print_row(
                        progress,
                        sid,
                        f"HTTP {status}",
                        elapsed
                    )

                elif status in (403, 429):
                    errors += 1
                    interrupted = True

                    print_row(
                        progress,
                        sid,
                        f"HTTP {status}",
                        elapsed
                    )

                    log("Access restricted. Stopping.")
                    break

                elif status != 200:
                    errors += 1
                    interrupted = True

                    print_row(
                        progress,
                        sid,
                        f"HTTP {status}",
                        elapsed
                    )
                    break

                else:
                    final_host = (
                        urlparse(final_url).hostname or ""
                    )

                    if final_host not in (
                        "djpunjab.is",
                        "www.djpunjab.is"
                    ):
                        errors += 1
                        interrupted = True
                        log("Unexpected redirect host")
                        break

                    song, reason = extract_song(
                        sid,
                        html,
                        final_url
                    )

                    if song:
                        old = songs.get(str(sid), {})

                        for field in ("artist", "album"):
                            if not song[field]:
                                song[field] = old.get(
                                    field, ""
                                )

                        songs[str(sid)] = song
                        http400_ids.discard(sid)
                        found += 1

                        print_row(
                            progress,
                            sid,
                            "FOUND",
                            elapsed,
                            song["title"],
                            song["artist"],
                            song["album"]
                        )

                    elif reason == "Invalid song URL":
                        not_found += 1

                        print_row(
                            progress,
                            sid,
                            "NOT FOUND",
                            elapsed
                        )

                    else:
                        errors += 1
                        interrupted = True

                        print_row(
                            progress,
                            sid,
                            "UNPARSED",
                            elapsed
                        )

                        log(f"Reason: {reason}")
                        break

            except (requests.RequestException, ValueError) as e:
                errors += 1
                interrupted = True

                elapsed = (
                    time.perf_counter() - request_start
                )

                print_row(
                    progress,
                    sid,
                    "ERROR",
                    elapsed
                )

                log(f"Reason: {e}")
                break

            next_id = sid + 1
            completed += 1

            if completed % CHECKPOINT_EVERY == 0:
                checkpoint(
                    songs,
                    next_id,
                    http400_ids
                )

            if completed % PUSH_EVERY == 0:
                checkpoint(
                    songs,
                    next_id,
                    http400_ids
                )
                push_to_github()
                print_header()

            if sid < end_id:
                time.sleep(DELAY_SECONDS)

    finally:
        checkpoint(
            songs,
            next_id,
            http400_ids
        )

        session.close()

        elapsed_total = (
            time.perf_counter() - started_at
        )

        log("")
        log("=" * 50)
        log("SCAN SUMMARY")
        log("=" * 50)
        log(f"Found:           {found}")
        log(f"Not found:       {not_found}")
        log(f"Errors:          {errors}")
        log(f"Skipped:         {skipped}")
        log(f"Processed:       {completed}")
        log(f"CSV records:     {len(songs)}")
        log(f"HTTP 400 IDs:    {len(http400_ids)}")
        log(f"Next ID:         {next_id}")
        log(f"Elapsed:         {elapsed_total:.2f}s")
        log("=" * 50)

    # Push any remaining changes after the batch.
    push_to_github()

    if interrupted or errors:
        raise RuntimeError(
            f"Scan interrupted at ID {next_id}"
        )


if __name__ == "__main__":
    main()
