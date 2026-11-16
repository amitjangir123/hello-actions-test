
import re
import sqlite3
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

DB_FILE = "songs.db"
USER_AGENT = "PersonalMusicCatalogResearch/1.0"


def log(message):
    print(message, flush=True)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


# ==========================================
# DATABASE
# ==========================================

def create_database():
    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS songs (
            song_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            artist TEXT,
            album TEXT,
            url TEXT NOT NULL
        )
    """)

    # External-content full-text search index.
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS songs_fts
        USING fts5(
            title,
            artist,
            album,
            content='songs',
            content_rowid='song_id'
        )
    """)

    # Keep the search index synchronized
    # whenever song records change.
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS songs_ai
        AFTER INSERT ON songs BEGIN
            INSERT INTO songs_fts(
                rowid, title, artist, album
            )
            VALUES (
                new.song_id,
                new.title,
                new.artist,
                new.album
            );
        END;

        CREATE TRIGGER IF NOT EXISTS songs_ad
        AFTER DELETE ON songs BEGIN
            INSERT INTO songs_fts(
                songs_fts, rowid, title, artist, album
            )
            VALUES (
                'delete',
                old.song_id,
                old.title,
                old.artist,
                old.album
            );
        END;

        CREATE TRIGGER IF NOT EXISTS songs_au
        AFTER UPDATE ON songs BEGIN
            INSERT INTO songs_fts(
                songs_fts, rowid, title, artist, album
            )
            VALUES (
                'delete',
                old.song_id,
                old.title,
                old.artist,
                old.album
            );

            INSERT INTO songs_fts(
                rowid, title, artist, album
            )
            VALUES (
                new.song_id,
                new.title,
                new.artist,
                new.album
            );
        END;
    """)

    # Populate the FTS index when upgrading
    # an existing database without an index.
    count = conn.execute(
        "SELECT COUNT(*) FROM songs"
    ).fetchone()[0]

    if count:
        conn.execute("""
            INSERT INTO songs_fts(songs_fts)
            VALUES ('rebuild')
        """)

    conn.commit()
    log(f"SQLite database ready: {DB_FILE}")

    return conn


def save_song(conn, song):
    conn.execute("""
        INSERT INTO songs (
            song_id, title, artist, album, url
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(song_id) DO UPDATE SET
            title = excluded.title,
            artist = excluded.artist,
            album = excluded.album,
            url = excluded.url
    """, (
        song["song_id"],
        song["title"],
        song["artist"],
        song["album"],
        song["url"]
    ))

    # Commit each valid song so the current
    # runner retains progress between requests.
    conn.commit()


# ==========================================
# HTML PARSING
# ==========================================

def get_labeled_value(soup, label):
    """
    Extract page fields such as:

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
    soup = BeautifulSoup(html, "html.parser")

    path = urllib.parse.urlparse(final_url).path

    match = re.search(
        r"(?:/song/|mp3-song-)(\d+)(?:\.html)?/?$",
        path,
        re.I
    )

    if not match or int(match.group(1)) != song_id:
        return None, "Invalid song URL"

    title = get_labeled_value(soup, "Track")
    artist = get_labeled_value(soup, "Artist")
    album = get_labeled_value(soup, "Album")

    if not title:
        return None, "Track title missing"

    return {
        "song_id": song_id,
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
    log("================================")
    log("DJ PUNJAB SQLITE SONG SCANNER")
    log(f"Scanning IDs {START_ID} to {END_ID}")
    log("================================")

    robots = check_robots()

    if robots is None:
        raise RuntimeError(
            "Cannot verify crawling rules"
        )

    conn = create_database()

    found = 0
    not_found = 0
    errors = 0
    skipped = 0

    try:
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
                    save_song(conn, song)
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
                log(f"[{sid:03d}] ERROR | {e}")
                log("Stopping after unexpected error.")
                break

            time.sleep(DELAY_SECONDS)

        total = conn.execute(
            "SELECT COUNT(*) FROM songs"
        ).fetchone()[0]

        log("")
        log("========== SCAN SUMMARY ==========")
        log(f"Found this run: {found}")
        log(f"Not found:      {not_found}")
        log(f"Errors:         {errors}")
        log(f"Skipped:        {skipped}")
        log(f"Total DB songs: {total}")
        log("==================================")

        # Test SQLite full-text search.
        log("")
        log("========== SEARCH TEST ==========")

        rows = conn.execute("""
            SELECT s.song_id, s.title, s.artist
            FROM songs_fts
            JOIN songs s
                ON s.song_id = songs_fts.rowid
            WHERE songs_fts MATCH ?
            LIMIT 10
        """, ("kuldeep",)).fetchall()

        for row in rows:
            log(
                f"ID: {row[0]} | "
                f"Title: {row[1]} | "
                f"Artist: {row[2]}"
            )

        log(f"Search results: {len(rows)}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
