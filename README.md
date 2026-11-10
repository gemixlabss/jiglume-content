# jiglume-content

Image archive for the [Jiglume](https://github.com/gemixlabss/jiglume) jigsaw app:
openly licensed photos and public-domain art, with a JSON catalog the app reads.

```
catalog.json                  the catalog (schema below)
manifest.json                 points to the current release tag — the only file read from `main`
images/<category>/<id>.webp   3000 px long side, WebP q85, never cropped
thumbs/<id>.webp              480 px long side
LICENSES.md                   author, licence and source of every image (generated)
tools/                        fetch / process / publish scripts (Python 3 + Pillow + numpy)
```

## Licence policy

Only licences that allow **commercial use and modification** (a jigsaw is a cut-up image):

| accepted | rejected |
|---|---|
| CC0 1.0, public domain (PD-\*, PDM), CC BY 2.0 / 3.0 / 4.0, Pexels License | CC BY-SA (share-alike), any NC or ND variant, GFDL, fair use, unclear / missing licence |

* Wikimedia Commons licences are read from the API's `extmetadata`
  (`LicenseShortName`, `Artist`, `AttributionRequired`, `Restrictions`) — never guessed.
  The search is pre-filtered with Commons structured data (P275 licence / P6216 status)
  and every file is re-checked; files with personality-rights or trademark
  restrictions, and CC BY files without an author, are rejected.
* CC BY images carry author + licence + source link in `catalog.json` and `LICENSES.md`;
  the app shows them in the puzzle preview.
* Images where a recognisable person, a logo/brand or a commercial product is prominent
  are excluded (keyword filter on title/description/categories, then a manual visual
  review of contact sheets; rejected ids are removed with `tools/remove_image.py`).

## catalog.json (schemaVersion 1)

```jsonc
{
  "schemaVersion": 1,            // the app ignores catalogs with a newer schema
  "contentVersion": "v3",        // release tag
  "generatedAt": "2026-11-09",
  "categories": [
    { "id": "nature", "order": 1, "icon": "forest",       // Material icon name
      "l10nKey": "category_nature",                        // translated in the app (20 languages)
      "names": { "en": "Nature", "tr": "Doğa" } }          // fallback names
  ],
  "puzzles": [
    { "id": "nature-1a2b3c4d", "categoryId": "nature", "title": "…",
      "imagePath": "images/nature/nature-1a2b3c4d.webp", "thumbPath": "thumbs/nature-1a2b3c4d.webp",
      "width": 3000, "height": 2000, "dominantColor": "#3a5f2b",
      "photographer": "Jane Doe", "sourceUrl": "https://commons.wikimedia.org/wiki/File:…",
      "license": "CC BY 4.0", "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
      "attributionRequired": true, "addedAt": "2026-11-09", "isNew": true }
  ]
}
```

Unknown fields are ignored by the app, so fields can be added without a schema bump.

## Delivery & caching

* **Content is immutable per release.** Every publish makes a content commit tagged `vN`
  (human-readable) and the manifest points at that commit's **SHA**:
  `https://cdn.jsdelivr.net/gh/gemixlabss/jiglume-content@<sha>/<path>` with
  `https://raw.githubusercontent.com/gemixlabss/jiglume-content/<sha>/<path>` as fallback
  (`bases` in `manifest.json`, tried in order by the app). A SHA is as immutable as a tag,
  so jsDelivr may cache it forever — no stale images, no purges needed — and it keeps
  working even in environments that refuse tag pushes.
* jsDelivr serves GitHub repositories up to a size limit; when a release is too large for
  it, the app silently falls back to raw.githubusercontent.com (second base).
* **Only `manifest.json` is read from a moving ref (`main`)**, and it is tiny. Method chosen
  to keep it fresh:
  1. The app reads it first from **raw.githubusercontent.com**, which caches for ~5 minutes
     (`Cache-Control: max-age=300`), so a new release is visible within minutes.
  2. Fallback: `cdn.jsdelivr.net/gh/…@main/manifest.json`. jsDelivr caches branch URLs for up
     to 7 days, so `publish.sh` calls `https://purge.jsdelivr.net/gh/gemixlabss/jiglume-content@main/manifest.json`
     after every push.
* The app downloads `catalog.json` only when `manifest.latest` differs from its cached copy.

## Quality rules

`add_images.py` rejects automatically: long side < 2000 px, perceptual duplicates, near-monochrome
(colourfulness < 6) and flat/blurry images (edge density < 0.05). Every batch is then reviewed on
contact sheets; weak images (text, diagrams, archival B/W, logos/insignia, people, wrong category,
spacecraft parts in Earth photos…) go into `tools/review_rejected.json` with a reason and are never
fetched again.

## Completing the archive (target: ≥ 15 per category, ≥ 220 total)

The cloud session that built v2 shares an IP that Wikimedia rate-limits hard, so some categories are
still short (see LICENSES.md for current counts). From any normal connection:

```bash
pip install -r tools/requirements.txt
export SI_API_KEY=...            # free key from https://api.data.gov/signup/ (optional)
tools/publish.sh --fetch --fetch-only   # fill inbox/ up to 18 per category
python3 tools/contact_sheet.py --inbox  # review review/sheet_*.jpg; reject with tools/review_rejected.json
tools/publish.sh                        # process, validate, release vN, purge CDN
```

## Adding content (one command)

```bash
pip install -r tools/requirements.txt

# drop images into inbox/<category>/ (with a JSON sidecar, see tools/add_images.py), or fetch:
tools/publish.sh --fetch      # fetch (Commons, Met, Pexels if PEXELS_API_KEY is set) + publish
tools/publish.sh              # publish whatever is in inbox/
```

`publish.sh` runs: `add_images.py` (resize without cropping, WebP, thumbnail, dominant colour,
pHash duplicate check, rejects < 2000 px) → `build_licenses.py` → `validate_catalog.py` →
content commit + tag `vN` → `manifest.json` pointing at that commit's SHA → push → purge the jsDelivr manifest.

Individual tools:

| tool | purpose |
|---|---|
| `fetch_nasa.py` | NASA Image and Video Library — public domain; items crediting third parties (ESA, ©, courtesy, agencies…) or showing logos/insignia/people are rejected |
| `fetch_smithsonian.py` | Smithsonian Open Access — only when record **and** media file say `CC0`; needs a free api.data.gov key in `SI_API_KEY` (never stored) |
| `fetch_rijksmuseum.py` | Rijksmuseum Linked Art — only records carrying the CC0 statement; `--category/--terms` |
| `fetch_museums.py` | The Met Open Access (CC0, `isPublicDomain` checked per object); `--category/--terms` |
| `fetch_commons.py` | Wikimedia Commons, strict licence filter (see above); `--extra-query 'hastemplate:"PD-USGov-NPS"'` / `PD-USGov-FWS` for US National Park Service and Fish & Wildlife photos |
| `fetch_pexels.py` | not used any more (Pexels stopped issuing API keys); kept for reference |
| `contact_sheet.py` | id-labelled review sheets (`--inbox`) for the manual quality check |
| `add_images.py` | process `inbox/` into the archive |
| `remove_image.py <id>…` | remove images (their hash stays known, so they are not re-added) |
| `build_licenses.py`, `validate_catalog.py`, `write_manifest.py` | used by `publish.sh` |

Sources that are **not** used: the Art Institute of Chicago image server and the Met API sit
behind bot challenges for scripted clients (we do not work around them), and the Rijksmuseum
API needs a key. Public-domain reproductions of museum paintings are taken from Wikimedia
Commons instead, with the licence read from Commons.

Network etiquette: the tools identify themselves with a descriptive User-Agent, honour
`Retry-After` on HTTP 429 and keep request counts low (one search per category pass).
