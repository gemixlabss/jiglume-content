#!/usr/bin/env python3
"""Writes the short, localised display titles into catalog.json.

The app never shows an image's source title ("European rabbit (Oryctolagus
cuniculus) kitten"); it shows a short subject in the player's language
("Yavru tavşan"). Subjects and their 20 translations live in
tools/display_titles.txt, the image → subject mapping in
tools/display_title_assign.txt. The catalog gets a shared `titles` table and
a `titleKey` per puzzle. Images without a subject fall back to the category
name in the app; validate_catalog.py reports them.
"""
from __future__ import annotations

import sys

from common import ROOT, load_catalog, log, save_catalog

LANGS = ["en", "tr", "de", "fr", "es", "pt-BR", "it", "ru", "ar", "ja", "ko", "zh-Hans", "hi", "id", "nl",
         "pl", "uk", "vi", "th", "sv"]


def load_titles() -> dict[str, dict[str, str]]:
    titles = {}
    for n, line in enumerate((ROOT / "tools" / "display_titles.txt").read_text().splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        key, names = parts[0], parts[1:]
        if len(names) != len(LANGS) or not all(names):
            raise SystemExit(f"display_titles.txt:{n}: {key}: expected {len(LANGS)} names, got {len(names)}")
        titles[key] = dict(zip(LANGS, names))
    return titles


def load_assign() -> dict[str, str]:
    out = {}
    for line in (ROOT / "tools" / "display_title_assign.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, ids = line.split(":", 1)
        for pid in ids.split():
            out[pid] = key.strip()
    return out


def main() -> int:
    titles, assign = load_titles(), load_assign()
    cat = load_catalog()
    used = set()
    missing = []
    for p in cat["puzzles"]:
        key = assign.get(p["id"])
        if key is None:
            p.pop("titleKey", None)
            missing.append(p["id"])
            continue
        if key not in titles:
            raise SystemExit(f"{p['id']}: unknown subject {key!r}")
        p["titleKey"] = key
        used.add(key)
    cat["titles"] = {k: titles[k] for k in sorted(used)}
    save_catalog(cat)
    for pid in missing:
        log(f"  no display title: {pid}")
    print(f"display titles: {len(cat['puzzles']) - len(missing)} images, {len(used)} subjects, {len(missing)} missing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
