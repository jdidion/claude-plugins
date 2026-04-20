#!/usr/bin/env python3
"""Pod envelope helpers (Shape A — markdown with YAML frontmatter).

Implements the Pod v1 envelope spec for the handoff payload kind:
https://github.com/jdidion/curaitor/blob/main/docs/SPEC-pod-envelope.md

Provides:
  - ULID generation (zero-dep)
  - sha256 body fingerprinting
  - Shape A read/write with legacy flat-frontmatter fallback
  - Seen-pod store for idempotency

CLI:
  pod.py compile --from F --to T --slug S --body-file BODY [--out PATH]
  pod.py verify <file>
  pod.py seen-check <id>
  pod.py seen-mark <id> [--path PATH]
"""

import argparse
import hashlib
import json
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

POD_FORMAT_VERSION = 1
HANDOFF_PAYLOAD_VERSION = 1

HANDOFFS_DIR = Path.home() / ".claude" / "handoffs"
SEEN_FILE = HANDOFFS_DIR / "seen.json"

CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    """Generate a 26-char Crockford base32 ULID (48-bit ms timestamp + 80-bit random)."""
    ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_int = int.from_bytes(secrets.token_bytes(10), "big")
    combined = (ts_ms << 80) | rand_int
    return "".join(CROCKFORD_ALPHABET[(combined >> (i * 5)) & 0x1F] for i in range(25, -1, -1))


def _canonicalize_body(body: str) -> bytes:
    """Canonicalize body for fingerprinting per Pod v1 Shape A.

    Strip a leading BOM, normalize CRLF/CR line endings to LF, and encode as
    UTF-8 without BOM. This matches the spec's canonicalization rule so writers
    and readers in different runtimes produce identical fingerprints.
    """
    if body.startswith("\ufeff"):
        body = body.lstrip("\ufeff")
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    return body.encode("utf-8")


def fingerprint(body: str) -> str:
    """Compute sha256 fingerprint of the payload body (canonicalized per Pod v1)."""
    digest = hashlib.sha256(_canonicalize_body(body)).hexdigest()
    return f"sha256-{digest}"


def verify_fingerprint(envelope: dict, body: str) -> bool:
    """Check that envelope.fingerprint matches sha256 of canonicalized body."""
    claimed = envelope.get("fingerprint", "")
    return claimed == fingerprint(body)


def _split_frontmatter(text: str):
    """Split a markdown file into (frontmatter_text, body). Returns (None, text) if no frontmatter."""
    if not text.startswith("---"):
        return None, text
    rest = text[3:]
    end = rest.find("\n---")
    if end == -1:
        return None, text
    fm = rest[:end].lstrip("\n")
    body_start = end + 4
    if body_start < len(rest) and rest[body_start] == "\n":
        body_start += 1
    return fm, rest[body_start:]


def _parse_flat_frontmatter(fm_text: str) -> dict:
    """Minimal YAML-ish parser for legacy flat frontmatter (key: value lines)."""
    result = {}
    for line in fm_text.splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, v = line.split(":", 1)
            result[k.strip()] = v.strip()
    return result


def parse_shape_a(text: str) -> dict:
    """Parse a Shape A pod.

    Returns:
        {
          "envelope": {...},      # Pod envelope fields
          "payload_meta": {...},  # Payload-kind fields (e.g. handoff.slug)
          "body": "...",          # Markdown body after closing ---
          "legacy": bool,         # True if we fell back to flat frontmatter
          "fingerprint_ok": bool, # True if envelope.fingerprint matches body
        }

    Raises:
        ValueError if the frontmatter is missing or unparseable.
    """
    fm_text, body = _split_frontmatter(text)
    if fm_text is None:
        raise ValueError("no YAML frontmatter found")

    if yaml is not None:
        try:
            data = yaml.safe_load(fm_text) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"invalid YAML frontmatter: {e}") from e
    else:
        data = _parse_flat_frontmatter(fm_text)

    if isinstance(data, dict) and "pod" in data:
        envelope = data.get("pod", {})
        payload_kind = envelope.get("payload", {}).get("kind", "handoff")
        payload_meta = data.get(payload_kind, {})
        return {
            "envelope": envelope,
            "payload_meta": payload_meta,
            "body": body,
            "legacy": False,
            "fingerprint_ok": verify_fingerprint(envelope, body),
        }

    envelope = {
        "format": "pod",
        "version": POD_FORMAT_VERSION,
        "id": None,
        "createdAt": data.get("timestamp", ""),
        "from": data.get("from", ""),
        "to": data.get("to", ""),
        "payload": {"kind": "handoff", "version": HANDOFF_PAYLOAD_VERSION},
        "fingerprint": None,
    }
    payload_meta = {"slug": data.get("slug", "")}
    return {
        "envelope": envelope,
        "payload_meta": payload_meta,
        "body": body,
        "legacy": True,
        "fingerprint_ok": False,
    }


def format_shape_a(pod_env: dict, payload_meta: dict, body: str) -> str:
    """Emit a Shape A pod as markdown with YAML frontmatter.

    Hand-formatted (no PyYAML emitter) to keep the writer zero-dep and output stable.
    `pod_env` must include format, version, id, createdAt, from, to, payload{kind,version},
    and fingerprint.
    """
    lines = ["---", "pod:"]
    lines.append(f"  format: {pod_env['format']}")
    lines.append(f"  version: {pod_env['version']}")
    lines.append(f"  id: {pod_env['id']}")
    lines.append(f"  createdAt: {pod_env['createdAt']}")
    lines.append(f"  from: {_yaml_scalar(pod_env['from'])}")
    lines.append(f"  to: {_yaml_scalar(pod_env['to'])}")
    lines.append("  payload:")
    lines.append(f"    kind: {pod_env['payload']['kind']}")
    lines.append(f"    version: {pod_env['payload']['version']}")
    lines.append(f"  fingerprint: {pod_env['fingerprint']}")
    for opt in ("exportedBy", "note", "inReplyTo", "supersedes"):
        if pod_env.get(opt):
            lines.append(f"  {opt}: {_yaml_scalar(pod_env[opt])}")
    kind = pod_env["payload"]["kind"]
    if payload_meta:
        lines.append(f"{kind}:")
        for k, v in payload_meta.items():
            lines.append(f"  {k}: {_yaml_scalar(v)}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + body


def _yaml_scalar(v) -> str:
    """Quote a scalar if it contains YAML special characters; otherwise emit plain."""
    if v is None:
        return "null"
    s = str(v)
    if not s:
        return '""'
    if s[0] in "!&*[]{}|>#%@`,\"'" or s.startswith("- ") or s.endswith(":"):
        return json.dumps(s)
    if any(c in s for c in ":#\n"):
        return json.dumps(s)
    return s


def build_envelope(from_id: str, to_id: str, slug: str, body: str,
                   created_at: str | None = None, exported_by: str | None = None) -> tuple:
    """Build a complete handoff pod envelope + payload_meta for the given body.

    Returns (pod_env, payload_meta).
    """
    pod_env = {
        "format": "pod",
        "version": POD_FORMAT_VERSION,
        "id": ulid(),
        "createdAt": created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "from": from_id,
        "to": to_id,
        "payload": {"kind": "handoff", "version": HANDOFF_PAYLOAD_VERSION},
        "fingerprint": fingerprint(body),
    }
    if exported_by:
        pod_env["exportedBy"] = exported_by
    payload_meta = {"slug": slug}
    return pod_env, payload_meta


class SeenStore:
    """Tracks seen pod IDs for idempotency. Append-only JSON at ~/.claude/handoffs/seen.json."""

    def __init__(self, path: Path = SEEN_FILE):
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except (json.JSONDecodeError, IOError):
                pass
        return {"version": 1, "pods": {}}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2) + "\n")

    def has(self, pod_id: str) -> bool:
        return pod_id in self._data["pods"]

    def mark(self, pod_id: str, **meta):
        entry = {"seen_at": datetime.now(timezone.utc).isoformat()}
        entry.update(meta)
        self._data["pods"][pod_id] = entry
        self.save()

    def get(self, pod_id: str) -> dict:
        return self._data["pods"].get(pod_id, {})


def cmd_compile(args):
    body_text = Path(args.body_file).read_text(encoding="utf-8")
    pod_env, payload_meta = build_envelope(
        from_id=args.from_id,
        to_id=args.to_id,
        slug=args.slug,
        body=body_text,
        exported_by=args.exported_by,
    )
    out_text = format_shape_a(pod_env, payload_meta, body_text)
    out_path = args.out
    if not out_path:
        inbox_dir = HANDOFFS_DIR / "inbox" / args.to_id
        inbox_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(inbox_dir / f"{pod_env['id']}-{args.slug}.md")
    Path(out_path).write_bytes(out_text.encode("utf-8"))
    print(json.dumps({
        "id": pod_env["id"],
        "path": out_path,
        "from": pod_env["from"],
        "to": pod_env["to"],
        "slug": args.slug,
        "fingerprint": pod_env["fingerprint"],
        "createdAt": pod_env["createdAt"],
    }, indent=2))


def cmd_verify(args):
    text = Path(args.file).read_text(encoding="utf-8")
    parsed = parse_shape_a(text)
    result = {
        "file": args.file,
        "id": parsed["envelope"].get("id"),
        "legacy": parsed["legacy"],
        "fingerprint_ok": parsed["fingerprint_ok"],
    }
    print(json.dumps(result, indent=2))
    if parsed["legacy"]:
        sys.exit(2)
    if not parsed["fingerprint_ok"]:
        sys.exit(1)


def cmd_seen_check(args):
    store = SeenStore()
    entry = store.get(args.id)
    if entry:
        print(json.dumps({"seen": True, **entry}, indent=2))
    else:
        print(json.dumps({"seen": False}, indent=2))
        sys.exit(1)


def cmd_seen_mark(args):
    store = SeenStore()
    meta = {}
    if args.path:
        meta["path"] = args.path
    store.mark(args.id, **meta)
    print(f"Marked seen: {args.id}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_compile = sub.add_parser("compile", help="Wrap a body file in a Pod envelope and write to inbox")
    p_compile.add_argument("--from", dest="from_id", required=True)
    p_compile.add_argument("--to", dest="to_id", required=True)
    p_compile.add_argument("--slug", required=True)
    p_compile.add_argument("--body-file", required=True)
    p_compile.add_argument("--out", help="Output path (default: ~/.claude/handoffs/inbox/<to>/<id>-<slug>.md)")
    p_compile.add_argument("--exported-by", help="Free-form authoring principal")
    p_compile.set_defaults(func=cmd_compile)

    p_verify = sub.add_parser("verify", help="Verify fingerprint of a pod file")
    p_verify.add_argument("file")
    p_verify.set_defaults(func=cmd_verify)

    p_check = sub.add_parser("seen-check", help="Check if a pod ID has been seen")
    p_check.add_argument("id")
    p_check.set_defaults(func=cmd_seen_check)

    p_mark = sub.add_parser("seen-mark", help="Mark a pod ID as seen")
    p_mark.add_argument("id")
    p_mark.add_argument("--path", help="Path to the pod file (for audit)")
    p_mark.set_defaults(func=cmd_seen_mark)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
