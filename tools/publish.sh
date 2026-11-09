#!/usr/bin/env bash
# One-command content release.
#
#   tools/publish.sh            # process inbox/, then release
#   tools/publish.sh --fetch    # also fetch new images first (Commons, Met, Pexels if PEXELS_API_KEY)
#
# Steps: [fetch] → add_images → LICENSES.md → validate → next tag (vN) →
# manifest.json → commit + tag + push → purge jsDelivr's cached @main manifest.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--fetch" ]]; then
  python3 tools/fetch_commons.py --per-category "${PER_CATEGORY:-20}"
  python3 tools/fetch_museums.py --count "${PER_CATEGORY:-20}"
  python3 tools/fetch_pexels.py   # no-op without PEXELS_API_KEY
fi

python3 tools/add_images.py
python3 tools/build_licenses.py
python3 tools/validate_catalog.py

git fetch --tags --quiet origin || true
last=$(git tag --list 'v*' | sed 's/^v//' | sort -n | tail -1)
next="v$(( ${last:-0} + 1 ))"
python3 tools/write_manifest.py "$next"

git add -A
git commit -m "Content $next" --quiet
git tag "$next"
git push origin HEAD:main "$next"

# jsDelivr caches branch URLs for up to 7 days; tags are immutable and need
# no purge. Purge the only moving file so the CDN fallback is fresh too.
curl -fsS "https://purge.jsdelivr.net/gh/gemixlabss/jiglume-content@main/manifest.json" >/dev/null \
  && echo "jsDelivr manifest purged" || echo "warning: jsDelivr purge failed (raw.githubusercontent.com is still fresh)"
echo "Published $next"
