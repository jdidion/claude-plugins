#!/usr/bin/env python3
"""Resolve the editor or viewer command for a given file.

Looks up the per-extension override chain and falls back to environment
variables and then a hardcoded default. Prints the resolved command (as a
single shell-ready string) to stdout. Exits 0 even if it falls all the way
through — the caller decides whether the default is acceptable.

Usage:
  resolve.py edit <path> [--override <cmd>]
  resolve.py view <path> [--live]

Config search order (first hit wins for a given key):
  1. Repo-local TOML:  <repo-root>/.ed.toml
  2. User TOML:        $XDG_CONFIG_HOME/ed/config.toml  (default ~/.config/ed/config.toml)

Resolution ladder per role, for file with lowercased extension <ext>:

  edit:
    1. --override <cmd>                       (skill passes the user's inline override)
    2. config.extensions[ext].editor
    3. config.defaults.editor
    4. $VISUAL
    5. $EDITOR
    6. "vi"

  view (--live flag from the skill; only affects step 2):
    1. config.extensions[ext].viewer_live  (only if --live)
    2. config.extensions[ext].viewer
    3. config.defaults.viewer
    4. $VIEWER
    5. $ED_DEFAULT_VIEWER
    6. "less"

Config TOML shape (all keys optional):

    [defaults]
    editor = "hx"
    viewer = "less"

    [extensions.md]
    editor = "hx"
    viewer = "glow -p"
    viewer_live = "bash -c 'while :; do clear; glow \"$1\"; sleep 1; done' --"

    [extensions.pdf]
    viewer = "zathura"

Exit 0 always prints a command on stdout. Exit 2 on argument errors.
"""

import argparse
import os
import pathlib
import subprocess
import sys

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    tomllib = None
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        pass


def _find_repo_root(start: pathlib.Path) -> pathlib.Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    root = result.stdout.strip()
    return pathlib.Path(root) if root else None


def _load_toml(path: pathlib.Path) -> dict:
    if not path.is_file() or tomllib is None:
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, ValueError):
        return {}


def load_config(file_path: pathlib.Path) -> dict:
    """Merge user + repo config. Repo wins on conflict."""
    user_path = (
        pathlib.Path(os.environ.get("XDG_CONFIG_HOME", str(pathlib.Path.home() / ".config")))
        / "ed" / "config.toml"
    )
    merged = _load_toml(user_path)

    start = file_path.parent if file_path.exists() else pathlib.Path.cwd()
    repo_root = _find_repo_root(start)
    if repo_root:
        repo_cfg = _load_toml(repo_root / ".ed.toml")
        # Shallow merge defaults, deep merge extensions.
        if "defaults" in repo_cfg:
            merged.setdefault("defaults", {}).update(repo_cfg["defaults"])
        if "extensions" in repo_cfg:
            merged_ext = merged.setdefault("extensions", {})
            for key, val in repo_cfg["extensions"].items():
                merged_ext.setdefault(key, {}).update(val)
    return merged


def resolve_edit(file_path: pathlib.Path, override: str | None, config: dict) -> str:
    ext = file_path.suffix.lstrip(".").lower()

    if override:
        return override

    ext_cmd = config.get("extensions", {}).get(ext, {}).get("editor")
    if ext_cmd:
        return ext_cmd

    default_cmd = config.get("defaults", {}).get("editor")
    if default_cmd:
        return default_cmd

    for env in ("VISUAL", "EDITOR"):
        val = os.environ.get(env)
        if val:
            return val

    return "vi"


def resolve_view(file_path: pathlib.Path, live: bool, config: dict) -> tuple[str, str]:
    """Return (command, provenance_label). Provenance helps the skill explain what it ran."""
    ext = file_path.suffix.lstrip(".").lower()
    ext_cfg = config.get("extensions", {}).get(ext, {})

    if live and ext_cfg.get("viewer_live"):
        return ext_cfg["viewer_live"], f"config extensions.{ext}.viewer_live"
    if ext_cfg.get("viewer"):
        return ext_cfg["viewer"], f"config extensions.{ext}.viewer"
    default_cmd = config.get("defaults", {}).get("viewer")
    if default_cmd:
        return default_cmd, "config defaults.viewer"
    for env in ("VIEWER", "ED_DEFAULT_VIEWER"):
        val = os.environ.get(env)
        if val:
            return val, f"${env}"
    return "less", "fallback (less)"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="role", required=True)

    pe = sub.add_parser("edit", help="Resolve the editor command for a file.")
    pe.add_argument("path")
    pe.add_argument("--override", default=None, help="Explicit editor command from the user.")

    pv = sub.add_parser("view", help="Resolve the viewer command for a file.")
    pv.add_argument("path")
    pv.add_argument("--live", action="store_true", help="Prefer the live-reload variant if defined.")

    # Shared: --provenance prints a second line with where the command came from.
    for sp in (pe, pv):
        sp.add_argument("--provenance", action="store_true",
                        help="Print a second line to stderr naming the source (config key / env var).")

    args = p.parse_args()

    file_path = pathlib.Path(args.path).expanduser().resolve()
    config = load_config(file_path)

    if args.role == "edit":
        cmd = resolve_edit(file_path, args.override, config)
        prov = "override" if args.override else "resolved"
    else:
        cmd, prov = resolve_view(file_path, args.live, config)

    print(cmd)
    if args.provenance:
        print(prov, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
