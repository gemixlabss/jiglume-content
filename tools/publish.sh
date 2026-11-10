#!/usr/bin/env bash
# One-command content release.
#
#   tools/publish.sh            # process inbox/, then release
#   tools/publish.sh --fetch    # also fetch new images first (Commons, Met, Pexels if PEXELS_API_KEY)
#
# Steps: [fetch] → add_images → LICENSES.md → validate → content commit + tag vN →
# manifest.json (→ that commit's SHA) commit → push → purge jsDelivr's cached @main manifest.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--fetch" ]]; then
  # Fills every category up to PER_CATEGORY (published + inbox), cheapest
  # sources first. Rejected ids (tools/review_rejected.json) are never re-fetched.
  # Run tools/contact_sheet.py --inbox afterwards and review before publishing!
  n="${PER_CATEGORY:-18}"
  python3 tools/fetch_nasa.py --per-category "$n"
  if [[ -n "${SI_API_KEY:-}" ]]; then
    python3 tools/fetch_smithsonian.py --per-category "$n"
  else
    echo "SI_API_KEY not set — skipping Smithsonian (free key: https://api.data.gov/signup/)"
  fi
  python3 tools/fetch_rijksmuseum.py --count 8
  python3 tools/fetch_museums.py --count "$n"
  python3 tools/fetch_commons.py --per-category "$n" --terms sources_usgov.json \
    --extra-query 'hastemplate:"PD-USGov-NPS"' --no-quality-pass
  python3 tools/fetch_commons.py --per-category "$n" --terms sources_usgov.json \
    --extra-query 'hastemplate:"PD-USGov-FWS"' --no-quality-pass --only animals,nature,sea
  python3 tools/fetch_commons.py --per-category "$n"
  # Pexels is no longer used (new API keys are not issued); fetch_pexels.py is kept for reference.
  if [[ "${2:-}" == "--fetch-only" ]]; then exit 0; fi
fi

python3 tools/add_images.py
python3 tools/build_licenses.py
python3 tools/validate_catalog.py

git fetch --tags --quiet origin || true
last=$(git tag --list 'v*' | sed 's/^v//' | sort -n | tail -1)
next="v$(( ${last:-0} + 1 ))"

# 1. Content commit (images + catalog), tagged vN.
python3 tools/write_manifest.py stamp "$next"
git add -A -- . ':!manifest.json'
# Optional extra commit-message paragraph (e.g. trailers): PUBLISH_COMMIT_EXTRA="..."
git commit -m "Content $next" ${PUBLISH_COMMIT_EXTRA:+-m "$PUBLISH_COMMIT_EXTRA"} --quiet
ref=$(git rev-parse HEAD)
git tag "$next"

# 2. Manifest commit pointing at the content commit's SHA.
python3 tools/write_manifest.py manifest "$next" "$ref"
git add manifest.json
git commit -m "Manifest → $next" ${PUBLISH_COMMIT_EXTRA:+-m "$PUBLISH_COMMIT_EXTRA"} --quiet

git push origin HEAD:main
# Tags are for humans; the app uses the SHA, so a refused tag push is not fatal.
git push origin "$next" || echo "warning: could not push tag $next (the app does not need it)"

# jsDelivr caches branch URLs for up to 7 days; tags are immutable and need
# no purge. Purge the only moving file so the CDN fallback is fresh too.
curl -fsS "https://purge.jsdelivr.net/gh/gemixlabss/jiglume-content@main/manifest.json" >/dev/null \
  && echo "jsDelivr manifest purged" || echo "warning: jsDelivr purge failed (raw.githubusercontent.com is still fresh)"
echo "Published $next"
