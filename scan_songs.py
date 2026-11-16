
import csv
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from bs4 import BeautifulSoup

BASE = "https://djpunjab.is"

START_ID = 0
END_ID = 9
DELAY_SECONDS = 3

CSV_FILE = "songs.csv"
USER_AGENT = "PersonalMusicCatalogResearch/1.0"

FIELDS = ["song_id", "title", "artist", "album", "url"]


def log(message):
    print(message, flush=True)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def get_meta(soup, name):
    tag = (
        soup.find("meta", attrs={"property": name})
        or soup.find("meta", attrs={"name": name})
    )

    if tag:
        return clean(tag.get("content"))

    return ""


def person_name(value):
    if isinstance(value, str):
        return clean(value)

    if isinstance(value, dict):
        return clean(value.get("name"))

    if isinstance(value, list):
        return ", ".join(
            filter(None, [person_name(v) for v in value])
        )

    return ""


def get_jsonld(soup):
    for script in soup.find_all(
        "script", attrs={"type": "application/ld+json"}
    ):
        try:
            data = json.loads(script.string or script.get_text())

            def find_record(obj):
                if isinstance(obj, list):
                    for item in obj:
                        result = find_record(item)
                        if result:
                            return result

                if isinstance(obj, dict):
                    types = obj.get("@type", [])
                    if isinstance(types, str):
                        types = [types]

                    if "MusicRecording" in types:
                        return obj

                    for value in obj.values():
                        result = find_record(value)
                        if result:
                            return result

                return None

            result = find_record(data)

            if result:
                return result

        except (ValueError, TypeError):
            pass

    return {}


def labeled_value(soup, label):
    pattern = re.compile(
        rf"^{re.escape(label)}\s*:\s*(.+)$",
        re.I
    )

    for text in soup.stripped_strings:
        match = pattern.match(clean(text))

        if match:
            return clean(match.group(1))

    return ""


def extract_song(song_id, html, final_url):
    soup = BeautifulSoup(html, "html.parser")

    path = urllib.parse.urlparse(final_url).path

    match = re.search(
        r"(?:/song/|mp3-song-)(\d+)(?:\.html)?/?$",
        path,
        re.I
    )

    if not match or int(match.group(1)) != song_id:
        return None, "Invalid song URL"

    structured = get_jsonld(soup)

    title = clean(structured.get("name"))

    artist = person_name(
        structured.get("byArtist")
        or structured.get("artist")
    )

    album = person_name(structured.get("inAlbum"))

    if not artist:
        artist = get_meta(soup, "music:musician")

    if not artist:
        artist = labeled_value(soup, "Singer")

    if not artist:
        artist = labeled_value(soup, "Artist")

    if not album:
        album = get_meta(soup, "music:album")

    if not album:
        album = labeled_value(soup, "Album")

    if not title:
        title = labeled_value(soup, "Song")

    if not title:
        title = get_meta(soup, "og:title")

        title = re.sub(
            r"\s*(?:mp3 song download|download mp3).*",
            "",
            title,
            flags=re.I
        ).strip()

        if artist and title.lower().endswith(artist.lower()):
            title = title[:-len(artist)].strip(" -|")

        elif title:
            log(
                f"[{song_id:03d}] WARNING | "
                "Title may contain artist name"
            )

    if not title:
        return None, "No song title extracted"

    return {
        "song_id": str(song_id),
        "title": title,
        "artist": artist,
        "album": album,
        "url": final_url
    }, "OK"


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


def load_existing():
    songs = {}

    try:
        with open(
            CSV_FILE, newline="", encoding="utf-8"
        ) as f:
            for row in csv.DictReader(f):
                sid = row.get("song_id", "")

                if sid.isdigit():
                    songs[sid] = {
                        field: row.get(field, "")
                        for field in FIELDS
                    }

    except FileNotFoundError:
        pass

    return songs


def save_csv(songs):
    with open(
        CSV_FILE, "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()

        for sid in sorted(songs, key=int):
            writer.writerow(songs[sid])


def main():
    log("================================")
    log("DJ PUNJAB SONG SCANNER")
    log(f"Scanning IDs {START_ID} to {END_ID}")
    log("================================")

    robots = check_robots()

    if robots is None:
        log("Cannot verify access rules. Stopping.")
        return

    songs = load_existing()

    found = 0
    not_found = 0
    errors = 0

    for sid in range(START_ID, END_ID + 1):
        url = f"{BASE}/song/{sid}"

        if not robots.can_fetch(USER_AGENT, url):
            log(f"[{sid:03d}] SKIPPED | robots.txt")
            continue

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
                log(f"[{sid:03d}] NOT FOUND | HTTP 404")

            else:
                errors += 1
                log(f"[{sid:03d}] ERROR | HTTP {e.code}")

                if e.code in (403, 429):
                    log("Access restricted. Stopping.")
                    break

        except Exception as e:
            errors += 1
            log(f"[{sid:03d}] ERROR | {e}")
            break

        time.sleep(DELAY_SECONDS)

    save_csv(songs)

    log("========== SUMMARY ==========")
    log(f"Found: {found}")
    log(f"Not found: {not_found}")
    log(f"Errors: {errors}")
    log(f"Total CSV records: {len(songs)}")
    log("=============================")


if __name__ == "__main__":
    main()
