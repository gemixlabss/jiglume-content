#!/usr/bin/env python3
"""Re-fetches catalog images in higher resolution so that every puzzle stays
sharp at 1000 pieces after the app's "fill the board" crop.

Rule (see common.cell_pixels): after cropping to the phone board aspect
(3:4) and to a square (tablets), a 1000-piece grid must still get at least
MIN_CELL_PIXELS source pixels per cell. A 3:2 landscape photo needs about
3300 × 2200 px for that, so the stored images (≤ 3000 px, many 1920 px
Commons thumbnails) are re-fetched from the original where it is large
enough: Wikimedia Commons originals, Rijksmuseum IIIF, Met primary images.

Images whose source is too small — or cannot be re-fetched — are listed and
removed with --remove.

Resumable: progress is kept in tools/.upgrade_state.json (git-ignored).

    tools/upgrade_resolution.py            # upgrade what can be upgraded
    tools/upgrade_resolution.py --report   # counts only, no downloads
    tools/upgrade_resolution.py --remove   # also drop images that still fail
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from collections import Counter

from PIL import Image

from common import (FULL_LONG_SIDE, ROOT, WEBP_QUALITY, cell_pixels, http_get, http_json, load_catalog, log,
                    MIN_CELL_PIXELS, save_catalog)
from enhance import appeal, enhance
from imaging import encode_webp, fit_long_side, open_upright, trim_flat_border
from vividness import metrics as vivid_metrics

Image.MAX_IMAGE_PIXELS = 400_000_000
STATE = ROOT / "tools" / ".upgrade_state.json"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def passes(w: int, h: int) -> bool:
    return cell_pixels(w, h) >= MIN_CELL_PIXELS


# Panoramas need a longer stored side for their short side to pass the rule.
MAX_STORED_LONG_SIDE = 6144


def target_long_side(w: int, h: int) -> int:
    """Stored long side: FULL_LONG_SIDE, or more (up to MAX_STORED_LONG_SIDE,
    never upscaled) when a wide image needs it to pass the rule."""
    long_side = max(w, h)
    target = min(FULL_LONG_SIDE, long_side)
    while not passes(*_scaled(w, h, target)) and target < min(long_side, MAX_STORED_LONG_SIDE):
        target = min(target + 128, long_side, MAX_STORED_LONG_SIDE)
    return target


def _scaled(w: int, h: int, long_side: int) -> tuple[int, int]:
    s = min(1.0, long_side / max(w, h))
    return round(w * s), round(h * s)


def stored_size(w: int, h: int) -> tuple[int, int]:
    return _scaled(w, h, target_long_side(w, h))


# ---------------------------------------------------------------------------
# Sources: return (width, height, download-url) of the largest available image.

def commons_sizes(puzzles: list[dict]) -> dict[str, tuple[int, int, str]]:
    titles = {p["id"]: urllib.parse.unquote(p["sourceUrl"].split("/wiki/", 1)[1]).replace("_", " ")
              for p in puzzles}
    out = {}
    ids = list(titles)
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        d = http_json(COMMONS_API, params={"action": "query", "format": "json", "prop": "imageinfo",
                                           "iiprop": "size|url", "titles": "|".join(titles[x] for x in chunk)})
        norm = {n["to"]: n["from"] for n in d["query"].get("normalized", [])}
        by_title = {}
        for pg in d["query"]["pages"].values():
            if "imageinfo" in pg:
                ii = pg["imageinfo"][0]
                by_title[pg["title"]] = ii
                by_title[norm.get(pg["title"], pg["title"])] = ii
        for x in chunk:
            ii = by_title.get(titles[x]) or by_title.get("File:" + titles[x].removeprefix("File:"))
            if ii:
                out[x] = (ii["width"], ii["height"], ii["url"])
        time.sleep(2)
    return out


def download_url(p: dict, size: list) -> str:
    """Commons: a render from commons.wikimedia.org/w/thumb.php at the stored
    size (upload.wikimedia.org throttles originals and uncached sizes for
    shared cloud IPs; the thumb.php endpoint on the main host does not)."""
    w, h, url = size
    if source_of(p) != "commons":
        return url
    target = stored_size(w, h)[0]
    name = urllib.parse.unquote(p["sourceUrl"].split("/wiki/", 1)[1]).removeprefix("File:")
    return "https://commons.wikimedia.org/w/thumb.php?" + urllib.parse.urlencode({"f": name, "w": target})


def rijks_size(p: dict) -> tuple[int, int, str] | None:
    from fetch_rijksmuseum import record
    raw = json.dumps(record(p["sourceUrl"]))
    m = re.search(r"https://iiif\.micr\.io/([A-Za-z0-9]+)/", raw)
    if not m:
        return None
    info = http_json(f"https://iiif.micr.io/{m.group(1)}/info.json")
    w, h = info["width"], info["height"]
    n = target_long_side(w, h)
    return w, h, f"https://iiif.micr.io/{m.group(1)}/full/!{n},{n}/0/default.jpg"


def met_size(p: dict) -> tuple[int, int, str] | None:
    m = re.search(r"/(\d+)/?$", p["sourceUrl"])
    if not m:
        return None
    o = http_json(f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{m.group(1)}")
    url = o.get("primaryImage")
    if not url:
        return None
    # Size unknown until downloaded: assume large, check after download.
    return 10_000, 10_000, url


def nasa_size(p: dict) -> tuple[int, int, str] | None:
    from fetch_nasa import orig_url
    url = orig_url(p["sourceUrl"].rstrip("/").rsplit("/", 1)[1])
    return (10_000, 10_000, url) if url and url.endswith("~orig.jpg") else None


def si_size(p: dict) -> tuple[int, int, str] | None:
    """Smithsonian Open Access: find the record by title, match its link."""
    from fetch_smithsonian import best_media, search
    title = re.sub(r"\s*\(Smithsonian [A-Z]+\)$", "", p["title"]).replace('"', "")
    for row in search(f'"{title}"'):
        dnr = row.get("content", {}).get("descriptiveNonRepeating", {})
        if dnr.get("record_link") == p["sourceUrl"] or dnr.get("guid") == p["sourceUrl"]:
            best = best_media(row)
            if best:
                url, w, h = best
                return w, h, url
    return None


def source_of(p: dict) -> str:
    host = urllib.parse.urlparse(p["sourceUrl"]).netloc
    if "commons.wikimedia.org" in host:
        return "commons"
    if "rijksmuseum" in host:
        return "rijks"
    if "metmuseum" in host:
        return "met"
    if "nasa.gov" in host:
        return "nasa"
    if "si.edu" in host or "cooperhewitt" in host or "n2t.net" in host:
        return "si"
    return "other"


# ---------------------------------------------------------------------------

def reprocess(p: dict, data: bytes) -> bool:
    img = trim_flat_border(open_upright(data))
    full = fit_long_side(img, target_long_side(*img.size))
    if not passes(*full.size):
        log(f"  {p['id']}: still too small after download ({full.size[0]}x{full.size[1]})")
        return False
    full = enhance(full)
    (ROOT / p["imagePath"]).write_bytes(encode_webp(full, WEBP_QUALITY))
    p["width"], p["height"] = full.size
    p["quality"] = vivid_metrics(full)
    p["appeal"] = appeal(p["quality"])
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--pause", type=float, default=8, help="seconds between downloads")
    ap.add_argument("--retry", action="store_true", help="look again at images that failed before")
    args = ap.parse_args()

    cat = load_catalog()
    state = json.loads(STATE.read_text()) if STATE.exists() else {"done": [], "failed": {}, "sizes": {}}
    if args.retry:
        for k in [k for k, v in state["failed"].items() if not v.startswith("too small after")]:
            state["failed"].pop(k)
            state["sizes"].pop(k, None)
    todo = [p for p in cat["puzzles"] if not passes(p["width"], p["height"]) and p["id"] not in state["done"]]
    log(f"{len(cat['puzzles'])} puzzles, {len(todo)} below {MIN_CELL_PIXELS} px/cell at 1000 pieces")

    # Original sizes.
    commons = [p for p in todo if source_of(p) == "commons" and p["id"] not in state["sizes"]]
    if commons:
        for k, v in commons_sizes(commons).items():
            state["sizes"][k] = v
        STATE.write_text(json.dumps(state))
    for p in todo:
        if p["id"] in state["sizes"] or p["id"] in state["failed"]:
            continue
        src = source_of(p)
        try:
            size = {"rijks": rijks_size, "met": met_size, "nasa": nasa_size, "si": si_size}.get(src, lambda _: None)(p)
        except Exception as e:  # noqa: BLE001
            log(f"  {p['id']}: size lookup failed: {e}")
            size = None
        if size is None:
            state["failed"][p["id"]] = f"no larger source ({src})"
        else:
            state["sizes"][p["id"]] = size
        STATE.write_text(json.dumps(state))

    upgradable = [p for p in todo if p["id"] in state["sizes"] and passes(*stored_size(*state["sizes"][p["id"]][:2]))]
    for p in todo:
        if p["id"] in state["sizes"] and p not in upgradable:
            w, h, _ = state["sizes"][p["id"]]
            state["failed"][p["id"]] = f"original only {w}x{h}"
    STATE.write_text(json.dumps(state))
    log(f"upgradable {len(upgradable)}, hopeless {len([p for p in todo if p['id'] in state['failed']])}")

    if not args.report:
        for i, p in enumerate(upgradable):
            if p["id"] in state["done"] or p["id"] in state["failed"]:
                continue
            url = download_url(p, state["sizes"][p["id"]])
            log(f"[{i + 1}/{len(upgradable)}] {p['id']} ← {url[:90]}")
            try:
                ok = reprocess(p, http_get(url, timeout=300, attempts=8))
            except Exception as e:  # noqa: BLE001
                log(f"  download failed: {e}")
                state["failed"][p["id"]] = f"download failed: {e}"[:200]
                ok = None
            if ok:
                state["done"].append(p["id"])
                save_catalog(cat)
            elif ok is False:
                state["failed"][p["id"]] = "too small after download"
            STATE.write_text(json.dumps(state))
            time.sleep(args.pause)

    still = [p for p in cat["puzzles"] if not passes(p["width"], p["height"])]
    by_cat = Counter(p["categoryId"] for p in cat["puzzles"])
    drop = Counter(p["categoryId"] for p in still)
    log("category: kept / total  (after removing images below the rule)")
    for c in sorted(by_cat):
        log(f"  {c:13s} {by_cat[c] - drop[c]:3d} / {by_cat[c]}")
    if args.remove and still:
        ids = {p["id"] for p in still}
        for p in still:
            for rel in (p["imagePath"], p["thumbPath"]):
                (ROOT / rel).unlink(missing_ok=True)
            log(f"removed {p['id']}: {state['failed'].get(p['id'], 'below the rule')}")
        cat["puzzles"] = [p for p in cat["puzzles"] if p["id"] not in ids]
        save_catalog(cat)
    print(f"below rule: {len(still)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
