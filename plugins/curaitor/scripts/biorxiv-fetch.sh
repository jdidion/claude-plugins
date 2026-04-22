#!/usr/bin/env bash
# biorxiv-fetch.sh — Fetch a cloudflare-protected PDF via `cmux browser`
# and stream it in chunks to avoid eval-size limits.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/biorxiv-fetch.sh <PDF_URL> <OUTPUT_PATH>

  PDF_URL       bioRxiv/medRxiv PDF link or any URL blocked by cloudflare.
  OUTPUT_PATH   Local filesystem path to write the PDF.

Fetches the PDF via the cmux browser harness, streaming it in ~3 MB chunks
so it can be fed into mcp__pdf-reader__read_pdf.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 2 ]]; then
  usage >&2
  exit 1
fi

URL="$1"
OUT="$2"
B64="${OUT}.b64"
CHUNK=3000000

if ! command -v cmux >/dev/null 2>&1; then
  echo "error: cmux not available. Fallback: cmux browser snapshot --compact manually." >&2
  exit 1
fi

echo "[1/6] goto $URL" >&2
cmux browser goto "$URL" >/dev/null

echo "[2/6] wait for load-state complete" >&2
cmux browser wait --load-state complete --timeout-ms 15000 >/dev/null

echo "[3/6] fetching bytes into window.__pdfBuf" >&2
cmux browser eval "window.__pdfBuf = null; fetch(location.href, {credentials:'include'}).then(r => r.arrayBuffer()).then(b => { window.__pdfBuf = b; return b.byteLength; })" >/dev/null

# Poll up to 30s for buffer to be populated.
for i in $(seq 1 30); do
  READY=$(cmux browser eval "window.__pdfBuf ? window.__pdfBuf.byteLength : 0" | tr -d '[:space:]"')
  if [[ "$READY" =~ ^[0-9]+$ && "$READY" -gt 0 ]]; then
    break
  fi
  sleep 1
done

SIZE=$(cmux browser eval "window.__pdfBuf.byteLength" | tr -d '[:space:]"')
if [[ ! "$SIZE" =~ ^[0-9]+$ || "$SIZE" -le 0 ]]; then
  echo "error: fetch timed out or returned empty buffer (size=$SIZE)" >&2
  exit 1
fi

echo "[4/6] total size: $SIZE bytes" >&2
: > "$B64"

OFFSET=0
while [[ "$OFFSET" -lt "$SIZE" ]]; do
  echo "[5/6] chunk offset=$OFFSET" >&2
  cmux browser eval "btoa(String.fromCharCode.apply(null, new Uint8Array(window.__pdfBuf.slice($OFFSET, $OFFSET+$CHUNK))))" \
    | tr -d '[:space:]"' >> "$B64"
  OFFSET=$((OFFSET + CHUNK))
done

echo "[6/6] decoding to $OUT" >&2
base64 -d "$B64" > "$OUT"
rm -f "$B64"

echo "$OUT ($SIZE bytes)"
