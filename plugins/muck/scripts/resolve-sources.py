#!/usr/bin/env python3
"""Resolve a mixed list of sources to local file paths.

Accepts local paths, HTTP(S) URLs, and Google Drive refs. Writes fetched
content to --out-dir as plain text and emits one resolved local path per
line on stdout. Local paths pass through unchanged.

Supported source shapes:

  path/to/file.md                 local file (passthrough)
  https://example.com/post        fetched, HTML-stripped, written as .txt
  gdrive://<file-id>              fetched via `gws` CLI
  https://docs.google.com/document/d/<id>/...
  https://drive.google.com/file/d/<id>/...
  gdrive-folder://<folder-id>     expanded to child docs via `gws`
  https://drive.google.com/drive/folders/<id>

Usage:
    resolve-sources.py --out-dir DIR src1 src2 ...
    resolve-sources.py --out-dir /tmp/muck https://example.com/post gdrive://ABC123

Exit codes:
    0  all sources resolved
    1  argument or IO error
    2  one or more sources failed to resolve (partial success is not OK)
"""

import argparse
import html
import ipaddress
import json
import re
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError

USER_AGENT = "muck-resolve-sources/1.0"
FETCH_TIMEOUT_SEC = 30
MAX_FETCH_BYTES = 5 * 1024 * 1024  # 5 MiB — a single blog post is <100 KiB

# Tags whose textual content is irrelevant to prose analysis.
DROP_TAGS = {
    "script", "style", "noscript", "nav", "header", "footer", "aside",
    "form", "button", "svg", "canvas", "iframe", "figure", "figcaption",
    "picture", "source", "video", "audio", "object", "embed",
}
# Preferred main-content containers, in priority order.
MAIN_TAGS = ("article", "main")
BLOCK_TAGS = {
    "p", "br", "div", "section", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "pre", "tr", "td",
}


class _Extractor(HTMLParser):
    """Collect visible text, biased toward <article>/<main> when present.

    Strategy: record text globally and also into per-region buffers. After
    parsing, prefer article, else main, else global-minus-chrome.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._drop_depth = 0
        self._regions: list[tuple[str, list[str]]] = []  # stack of (tag, buf)
        self._article: list[str] | None = None
        self._main: list[str] | None = None
        self._global: list[str] = []

    def _current_buffers(self) -> list[list[str]]:
        bufs: list[list[str]] = [self._global]
        for _, buf in self._regions:
            bufs.append(buf)
        return bufs

    def handle_starttag(self, tag, attrs):
        del attrs
        tag = tag.lower()
        if tag in DROP_TAGS:
            self._drop_depth += 1
            return
        if tag == "article" and self._article is None:
            self._article = []
            self._regions.append((tag, self._article))
        elif tag == "main" and self._main is None:
            self._main = []
            self._regions.append((tag, self._main))
        if tag in BLOCK_TAGS:
            for buf in self._current_buffers():
                buf.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in DROP_TAGS and self._drop_depth > 0:
            self._drop_depth -= 1
            return
        if self._regions and self._regions[-1][0] == tag:
            self._regions.pop()
        if tag in BLOCK_TAGS:
            for buf in self._current_buffers():
                buf.append("\n")

    def handle_data(self, data):
        if self._drop_depth > 0 or not data.strip():
            return
        for buf in self._current_buffers():
            buf.append(data)

    def best_text(self) -> str:
        if self._article:
            return _normalize("".join(self._article))
        if self._main:
            return _normalize("".join(self._main))
        return _normalize("".join(self._global))


def _normalize(text: str) -> str:
    text = html.unescape(text)
    # Collapse whitespace: each line trimmed, blank-line boundaries preserved.
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    blank = False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip() + "\n"


def extract_text_from_html(html_text: str) -> str:
    parser = _Extractor()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception as exc:  # malformed HTML shouldn't crash the pipeline
        print(f"warn: HTML parse error ({exc}); falling back to raw text", file=sys.stderr)
        return _normalize(re.sub(r"<[^>]+>", " ", html_text))
    return parser.best_text()


# ---------- SSRF guard ----------


_PRIVATE_NETS = [
    ipaddress.ip_network(n) for n in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
        "127.0.0.0/8", "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10",
    )
]


def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if any(ip in net for net in _PRIVATE_NETS):
            return False
    return True


def _check_http_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"refused non-http(s) scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise ValueError(f"refused url without host: {url!r}")
    if not _is_public_host(parsed.hostname):
        raise ValueError(f"refused private/internal host: {parsed.hostname!r}")


# ---------- HTTP fetch ----------


def fetch_http(url: str, out_dir: Path) -> Path:
    _check_http_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
        ctype = resp.headers.get("Content-Type", "")
        raw = resp.read(MAX_FETCH_BYTES + 1)
        if len(raw) > MAX_FETCH_BYTES:
            raise ValueError(f"response exceeded {MAX_FETCH_BYTES} bytes: {url}")
    try:
        body = raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
    except LookupError:
        body = raw.decode("utf-8", errors="replace")
    if "html" in ctype.lower():
        text = extract_text_from_html(body)
    else:
        text = _normalize(body)
    out_path = out_dir / (_slug_for_url(url) + ".txt")
    out_path.write_text(text, encoding="utf-8")
    return out_path


def _slug_for_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    base = (parsed.netloc + parsed.path).strip("/").replace("/", "-")
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-") or "page"
    return base[:80]


# ---------- Google Drive ----------


GDRIVE_DOC_URL = re.compile(
    r"^https?://(?:docs|drive)\.google\.com/(?:document|spreadsheets|presentation|file)/d/([A-Za-z0-9_-]+)"
)
GDRIVE_FOLDER_URL = re.compile(
    r"^https?://drive\.google\.com/drive/folders/([A-Za-z0-9_-]+)"
)
GDRIVE_SCHEME = re.compile(r"^gdrive://([A-Za-z0-9_-]+)$")
GDRIVE_FOLDER_SCHEME = re.compile(r"^gdrive-folder://([A-Za-z0-9_-]+)$")


# Google-native MIME types that require export (vs. raw media download).
_GOOGLE_NATIVE_MIMES = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.drawing": "image/png",
}


def _gws(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["gws", *args],
        capture_output=True, text=True, timeout=120, cwd=str(cwd) if cwd else None,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gws {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def _gws_json(args: list[str]) -> dict:
    proc = _gws(args)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gws {' '.join(args)} returned non-JSON: {exc}") from exc


def _file_metadata(file_id: str) -> dict:
    """Return `{id, name, mimeType}` for a Drive file."""
    params = json.dumps({"fileId": file_id, "fields": "id,name,mimeType"})
    return _gws_json(["drive", "files", "get", "--params", params])


def fetch_gdrive_file(file_id: str, out_dir: Path) -> Path:
    """Download a Drive file to a local text file via `gws`.

    Google-native docs are exported as text; other files are downloaded raw.
    Requires the `gws` CLI on PATH and prior authentication.
    """
    meta = _file_metadata(file_id)
    mime = meta.get("mimeType", "")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", meta.get("name") or file_id)[:60]

    if mime in _GOOGLE_NATIVE_MIMES:
        out_mime = _GOOGLE_NATIVE_MIMES[mime]
        rel_name = f"gdrive-{file_id}-{safe_name}.txt"
        params = json.dumps({"fileId": file_id, "mimeType": out_mime})
        _gws(["drive", "files", "export", "--params", params, "--output", rel_name], cwd=out_dir)
    else:
        rel_name = f"gdrive-{file_id}-{safe_name}"
        params = json.dumps({"fileId": file_id, "alt": "media"})
        _gws(["drive", "files", "get", "--params", params, "--output", rel_name], cwd=out_dir)

    out_path = out_dir / rel_name
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"gws download produced no content for {file_id}")
    return out_path


def fetch_gdrive_folder(folder_id: str, out_dir: Path) -> list[Path]:
    """List and download every non-folder file in a Drive folder via `gws`."""
    q = f"'{folder_id}' in parents and trashed = false"
    params = json.dumps({"q": q, "fields": "files(id,name,mimeType)", "pageSize": 100})
    listing = _gws_json(["drive", "files", "list", "--params", params])
    paths: list[Path] = []
    errors: list[str] = []
    for f in listing.get("files", []):
        if f.get("mimeType") == "application/vnd.google-apps.folder":
            continue  # skip subfolders; caller can target them explicitly
        fid = f["id"]
        try:
            paths.append(fetch_gdrive_file(fid, out_dir))
        except Exception as exc:
            errors.append(f"{fid} ({f.get('name', '?')}): {exc}")
    if errors and not paths:
        raise RuntimeError("no files downloaded from folder; errors: " + "; ".join(errors))
    for e in errors:
        print(f"warn: {e}", file=sys.stderr)
    return paths


# ---------- Dispatch ----------


def resolve_one(src: str, out_dir: Path) -> list[Path]:
    # Local file — passthrough (resolve to absolute for the caller's convenience).
    p = Path(src)
    if p.exists() and p.is_file():
        return [p.resolve()]

    # Drive explicit schemes
    m = GDRIVE_SCHEME.match(src)
    if m:
        return [fetch_gdrive_file(m.group(1), out_dir)]
    m = GDRIVE_FOLDER_SCHEME.match(src)
    if m:
        return fetch_gdrive_folder(m.group(1), out_dir)

    # Drive URLs
    m = GDRIVE_FOLDER_URL.match(src)
    if m:
        return fetch_gdrive_folder(m.group(1), out_dir)
    m = GDRIVE_DOC_URL.match(src)
    if m:
        return [fetch_gdrive_file(m.group(1), out_dir)]

    # Generic HTTP(S)
    if src.startswith(("http://", "https://")):
        return [fetch_http(src, out_dir)]

    raise ValueError(f"unrecognized source (not a local file, URL, or gdrive ref): {src!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+", help="mix of local paths, URLs, gdrive refs")
    ap.add_argument("--out-dir", type=Path, help="directory for fetched files (default: mkdtemp)")
    args = ap.parse_args()

    if args.out_dir is None:
        args.out_dir = Path(tempfile.mkdtemp(prefix="muck-resolve-"))
    else:
        args.out_dir.mkdir(parents=True, exist_ok=True)

    resolved: list[Path] = []
    failures: list[str] = []
    for src in args.sources:
        try:
            resolved.extend(resolve_one(src, args.out_dir))
        except (HTTPError, URLError, RuntimeError, ValueError) as exc:
            failures.append(f"{src}: {exc}")

    for p in resolved:
        print(p)
    for f in failures:
        print(f"error: {f}", file=sys.stderr)
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
