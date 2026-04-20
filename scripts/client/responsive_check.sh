#!/usr/bin/env bash
# responsive_check.sh — take screenshots of key public pages at mobile/tablet/landscape
# viewports for manual comparison against design.
#
# Usage:
#   ./scripts/client/responsive_check.sh [url]
#
# Defaults to https://scitex-orochi.com. Output dir:
#   GITIGNORED/responsive-screenshots/<ISO-timestamp>/
#
# Requires: playwright-cli (npm i -g @playwright/cli) on PATH.
#
# Viewports:
#   iPhone 13        390x844  (portrait)
#   iPad             768x1024 (portrait)
#   Mobile landscape 844x390
#
# See todo#94.

set -euo pipefail

BASE_URL="${1:-https://scitex-orochi.com}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
OUT_DIR="${REPO_ROOT}/GITIGNORED/responsive-screenshots/${STAMP}"
SESSION="responsive-check-$$"

mkdir -p "${OUT_DIR}"

if ! command -v playwright-cli >/dev/null 2>&1; then
    echo "ERROR: playwright-cli not found on PATH." >&2
    echo "Install with: npm install -g @playwright/cli" >&2
    exit 1
fi

cleanup() {
    playwright-cli -s="${SESSION}" close >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Page -> path
declare -A PAGES=(
    [landing]="/"
    [signin]="/signin/"
)

# Viewport label -> "WxH"
declare -a VIEWPORTS=(
    "iphone13:390:844"
    "ipad:768:1024"
    "mobile-landscape:844:390"
)

echo "==> Base URL: ${BASE_URL}"
echo "==> Output:   ${OUT_DIR}"

playwright-cli -s="${SESSION}" open "${BASE_URL}" >/dev/null

for page_name in "${!PAGES[@]}"; do
    page_path="${PAGES[$page_name]}"
    url="${BASE_URL}${page_path}"
    echo "==> ${page_name}: ${url}"
    playwright-cli -s="${SESSION}" goto "${url}" >/dev/null

    for vp in "${VIEWPORTS[@]}"; do
        label="${vp%%:*}"
        rest="${vp#*:}"
        w="${rest%%:*}"
        h="${rest#*:}"
        out="${OUT_DIR}/${page_name}-${label}.png"
        playwright-cli -s="${SESSION}" resize "${w}" "${h}" >/dev/null
        playwright-cli -s="${SESSION}" screenshot \
            --filename "${out}" --full-page >/dev/null
        echo "    ${label} (${w}x${h}) -> ${out##"${REPO_ROOT}"/}"
    done
done

echo "Done. Review screenshots in: ${OUT_DIR}"
