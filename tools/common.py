"""Shared helpers for the jiglume-content tools.

Only Pillow and numpy are required (see tools/requirements.txt).
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog.json"
MANIFEST = ROOT / "manifest.json"
LICENSES = ROOT / "LICENSES.md"
INBOX = ROOT / "inbox"
PHASH_INDEX = ROOT / "tools" / "phash_index.json"

SCHEMA_VERSION = 1
REPO = "gemixlabss/jiglume-content"
USER_AGENT = f"JiglumeContentTools/1.0 (https://github.com/{REPO})"

# Image processing rules.
FULL_LONG_SIDE = 3000
THUMB_LONG_SIDE = 640  # 2-column grids on 3× phones stay sharp
MIN_LONG_SIDE = 1900  # Commons 1920 px thumbnails (larger steps are throttled for shared IPs)
WEBP_QUALITY = 85
THUMB_QUALITY = 80
DUPLICATE_HAMMING = 8  # pHash distance at or below which two images are "the same"

# Category definitions: the single source of truth, written into catalog.json.
# `l10nKey` is resolved by the app's localisation files (20 languages); the
# `names` map is a fallback for app versions that do not know the key yet.
CATEGORIES = [
    {"id": "nature", "order": 1, "icon": "forest", "names": {"en": "Nature", "tr": "Doğa"}},
    {"id": "animals", "order": 2, "icon": "pets", "names": {"en": "Animals", "tr": "Hayvanlar"}},
    {"id": "cities", "order": 3, "icon": "location_city", "names": {"en": "Cities", "tr": "Şehirler"}},
    {"id": "travel", "order": 4, "icon": "flight_takeoff", "names": {"en": "Travel", "tr": "Seyahat"}},
    {"id": "sea", "order": 5, "icon": "beach_access", "names": {"en": "Sea & Beach", "tr": "Deniz & Sahil"}},
    {"id": "mountains", "order": 6, "icon": "landscape", "names": {"en": "Mountains", "tr": "Dağlar"}},
    {"id": "flowers", "order": 7, "icon": "local_florist", "names": {"en": "Flowers", "tr": "Çiçekler"}},
    {"id": "food", "order": 8, "icon": "restaurant", "names": {"en": "Food", "tr": "Yemek"}},
    {"id": "art", "order": 9, "icon": "palette", "names": {"en": "Art", "tr": "Sanat"}},
    {"id": "architecture", "order": 10, "icon": "account_balance", "names": {"en": "Architecture", "tr": "Mimari"}},
    {"id": "night", "order": 11, "icon": "nights_stay", "names": {"en": "Night & Sky", "tr": "Gece & Gökyüzü"}},
    {"id": "seasons", "order": 12, "icon": "eco", "names": {"en": "Seasons", "tr": "Mevsimler"}},
    {"id": "patterns", "order": 13, "icon": "texture", "names": {"en": "Colorful & Patterns", "tr": "Renkli & Desenler"}},
    {"id": "vehicles", "order": 14, "icon": "directions_railway", "names": {"en": "Vehicles", "tr": "Araçlar"}},
]
for _c in CATEGORIES:
    _c["l10nKey"] = f"category_{_c['id']}"
CATEGORY_IDS = {c["id"] for c in CATEGORIES}


# --------------------------------------------------------------------------
# Licences

LICENSE_URLS = {
    "CC0 1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "Public domain": "https://creativecommons.org/publicdomain/mark/1.0/",
    "CC BY 2.0": "https://creativecommons.org/licenses/by/2.0/",
    "CC BY 3.0": "https://creativecommons.org/licenses/by/3.0/",
    "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
    "Pexels License": "https://www.pexels.com/license/",
}
ATTRIBUTION_LICENSES = {"CC BY 2.0", "CC BY 3.0", "CC BY 4.0"}


def normalize_license(short_name: str | None) -> str | None:
    """Maps a Commons `LicenseShortName` to an accepted licence, or None.

    Accepted: CC0, public domain (PD-*, PDM, "Public domain"), CC BY 2.0 /
    3.0 / 4.0. Everything else is rejected — notably any BY-SA, NC or ND
    variant, GFDL, "fair use" and unknown / empty values. Never guesses.
    """
    if not short_name:
        return None
    s = html.unescape(re.sub(r"<[^>]+>", "", short_name)).strip().lower()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return None
    # Hard rejections first, so "CC BY-SA 4.0" can never match "CC BY 4.0".
    if re.search(r"(^|[^a-z])(sa|nc|nd)([^a-z]|$)", s) or any(
        bad in s for bad in ("share", "noncommercial", "non-commercial", "noderiv", "fair use",
                             "gfdl", "gnu", "copyrighted", "all rights reserved", "unknown")):
        return None
    if s in {"cc0", "cc0 1.0", "cc-zero", "cc zero", "cc0 1.0 universal"}:
        return "CC0 1.0"
    if s in {"public domain", "pd", "pdm", "public domain mark", "pdm 1.0", "public domain mark 1.0"} or s.startswith("pd-"):
        return "Public domain"
    m = re.fullmatch(r"cc[ -]by[ -]([234])\.0", s)
    if m:
        return f"CC BY {m.group(1)}.0"
    return None


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", value))
    return re.sub(r"\s+", " ", text).strip()


# Words that suggest a recognisable person, a logo/brand or a commercial
# product is prominent. Matched against title, description and categories.
EXCLUDE_WORDS = [
    "portrait", "people", "person", "persons", "woman", "women", "man ", " men", "girl", "boy",
    "child", "children", "kid", "crowd", "face", "faces", "selfie", "model", "bride", "groom",
    "wedding", "tourist", "tourists", "cyclist", "runner", "player", "musician", "dancer",
    "logo", "logos", "brand", "trademark", "advert", "billboard", "packaging", "product",
    "label", "store", "shop", "supermarket", "restaurant interior", "nude", "nudity",
    "protest", "demonstration", "military", "weapon", "gun", "police", "funeral", "accident",
    "fire truck", "ambulance", "car show", "auto show", "mercedes", "bmw", "toyota", "ford ",
    "coca", "pepsi", "mcdonald", "starbucks", "airline", "airways", "boeing", "airbus",
]


def looks_excluded(*texts: str) -> str | None:
    hay = " " + " ".join(t.lower() for t in texts if t) + " "
    for w in EXCLUDE_WORDS:
        if w in hay:
            return w.strip()
    return None


# --------------------------------------------------------------------------
# Catalog I/O

def empty_catalog() -> dict:
    return {"schemaVersion": SCHEMA_VERSION, "contentVersion": None, "generatedAt": None,
            "categories": CATEGORIES, "puzzles": []}


def load_catalog() -> dict:
    if CATALOG.exists():
        cat = json.loads(CATALOG.read_text(encoding="utf-8"))
        cat["categories"] = CATEGORIES  # definitions live in code
        return cat
    return empty_catalog()


def save_catalog(cat: dict) -> None:
    cat["schemaVersion"] = SCHEMA_VERSION
    cat["generatedAt"] = date.today().isoformat()
    cat["puzzles"].sort(key=lambda p: (next(c["order"] for c in CATEGORIES if c["id"] == p["categoryId"]), p["id"]))
    CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def review_rejected_ids() -> set[str]:
    """Ids rejected in manual review (tools/review_rejected.json): never re-fetched."""
    p = ROOT / "tools" / "review_rejected.json"
    return set(json.loads(p.read_text())) if p.exists() else set()


def category_count(category: str) -> int:
    """Images a category already has: published in the catalog + waiting in inbox/."""
    published = sum(1 for p in load_catalog()["puzzles"] if p["categoryId"] == category)
    return published + len(list((INBOX / category).glob("*.json")))


def load_phash_index() -> dict:
    return json.loads(PHASH_INDEX.read_text()) if PHASH_INDEX.exists() else {}


def save_phash_index(index: dict) -> None:
    PHASH_INDEX.write_text(json.dumps(index, indent=1, sort_keys=True) + "\n")


# --------------------------------------------------------------------------
# HTTP with polite retries (Wikimedia & museum APIs rate-limit shared IPs)

def http_get(url: str, *, params: dict | None = None, headers: dict | None = None,
             attempts: int = 12, timeout: int = 60) -> bytes:
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    delay = 4.0
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            retry = e.headers.get("Retry-After")
            wait = max(delay, float(retry) if retry and retry.isdigit() else 0)
            log(f"  HTTP {e.code}, retrying in {wait:.0f}s")
            time.sleep(wait)
            delay = min(delay * 1.6, 90)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == attempts - 1:
                raise
            log(f"  network error {e}, retrying in {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 1.6, 90)
    raise RuntimeError("unreachable")


def http_json(url: str, **kw) -> dict:
    return json.loads(http_get(url, **kw))


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)
