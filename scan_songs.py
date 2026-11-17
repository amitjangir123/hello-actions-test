
import csv
import json
import os
import re
import subprocess
import sys
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURATION
# ==========================================

BASE = "https://djpunjab.is"

BATCH_SIZE = 10000
DELAY_SECONDS = 0.001
CHECKPOINT_EVERY = 25
PUSH_EVERY = 1000

CSV_FILE = "songs.csv"
STATE_FILE = "scan_state.json"
HTTP400_FILE = "http400_ids.csv"

USER_AGENT = "PersonalMusicCatalogResearch/1.0"
REQUEST_TIMEOUT = (5, 15)
MAX_HTML_BYTES = 2 * 1024 * 1024

FIELDS = ["song_id", "title", "artist", "album", "url"]

# ==========================================
# FORMATTED LOGGING
# ==========================================

COLS = (10, 8, 12, 8, 27, 22, 22)


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

    sys.stdout.write(line.rstrip() + "\n")
    sys.stdout.flush()
