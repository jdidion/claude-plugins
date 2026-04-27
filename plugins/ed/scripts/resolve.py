#!/usr/bin/env python3
"""Resolve editor / viewer / flag commands for a file.

Prints a single shell-ready string on stdout. With --provenance, prints a
second line to stderr naming the source (config key / env var / fallback).

Subcommands:
  edit <path> [--override <cmd>]
      Editor command for <path>. Ladder:
        override → config.extensions.<ext>.editor → config.defaults.editor
        → $VISUAL → $EDITOR → "vi"

  view <path> [--live]
      Viewer command for <path>. Ladder:
        config.extensions.<ext>.viewer_live (if --live) →
        config.extensions.<ext>.viewer → config.defaults.viewer →
        $VIEWER → $ED_DEFAULT_VIEWER → "less"

  viewer-configured <path> [--live]
      Like `view`, but returns ONLY if an explicit viewer is configured for
      this extension (extensions.<ext>.viewer[_live]). Prints empty string
      and exits 0 otherwise. Drives /ed:edit's "open viewer only if
      configured for this type" logic.

  edit-flag <editor-cmd>
      Flag(s) that put <editor-cmd>'s first token into "edit / insert"
      mode, e.g. --edit for hx. Lookup order:
        config.editors.<bin>.edit_flag → built-in default → empty string
      Empty means "no special flag; the editor is always edit-capable by
      default".

  readonly-flag <editor-cmd>
      Flag(s) that put <editor-cmd>'s first token into read-only mode.
      Same lookup as edit-flag. Empty means "this editor has no read-only
      mode; the /ed:view fallback should just open it normally (and warn)".

Config layout (all keys optional):

    [defaults]
    editor = "hx"
    viewer = "micro"

    [extensions.md]
    viewer = "glow -p"
    viewer_live = "bash -c 'while :; do clear; glow \"$1\"; sleep 1; done' --"

    [editors.hx]
    edit_flag = ""          # hx has no special edit flag; empty disables the built-in default
    readonly_flag = ""      # hx has no read-only mode

    [editors.vi]
    readonly_flag = "-R"

Config sources, merged (repo wins on conflict):
  1. User:  $XDG_CONFIG_HOME/ed/config.toml  (default ~/.config/ed/config.toml)
  2. Repo:  <repo-root>/.ed.toml
"""

import argparse
import os
import pathlib
import shlex
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


# Built-in per-editor metadata. User/repo config can override per-key.
BUILTIN_EDITORS: dict[str, dict[str, str]] = {
    "hx":       {"edit_flag": "",              "readonly_flag": ""},
    "helix":    {"edit_flag": "",              "readonly_flag": ""},
    "vi":       {"edit_flag": "",              "readonly_flag": "-R"},
    "vim":      {"edit_flag": "",              "readonly_flag": "-R"},
    "nvim":     {"edit_flag": "",              "readonly_flag": "-R"},
    "nano":     {"edit_flag": "",              "readonly_flag": "-v"},
    "emacs":    {"edit_flag": "",              "readonly_flag": "--eval '(setq buffer-read-only t)'"},
    "micro":    {"edit_flag": "",              "readonly_flag": "-readonly true"},
    "code":     {"edit_flag": "",              "readonly_flag": ""},
    "subl":     {"edit_flag": "",              "readonly_flag": ""},
    "kakoune":  {"edit_flag": "-i",            "readonly_flag": ""},
    "kak":      {"edit_flag": "-i",            "readonly_flag": ""},
}


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
    user_path = (
        pathlib.Path(os.environ.get("XDG_CONFIG_HOME", str(pathlib.Path.home() / ".config")))
        / "ed" / "config.toml"
    )
    merged = _load_toml(user_path)

    start = file_path.parent if file_path.exists() else pathlib.Path.cwd()
    repo_root = _find_repo_root(start)
    if repo_root:
        repo_cfg = _load_toml(repo_root / ".ed.toml")
        if "defaults" in repo_cfg:
            merged.setdefault("defaults", {}).update(repo_cfg["defaults"])
        for section in ("extensions", "editors"):
            if section in repo_cfg:
                merged_section = merged.setdefault(section, {})
                for key, val in repo_cfg[section].items():
                    merged_section.setdefault(key, {}).update(val)
    return merged


def resolve_edit(file_path: pathlib.Path, override: str | None, config: dict) -> tuple[str, str]:
    ext = file_path.suffix.lstrip(".").lower()
    if override:
        return override, "override"
    ext_cmd = config.get("extensions", {}).get(ext, {}).get("editor")
    if ext_cmd:
        return ext_cmd, f"config extensions.{ext}.editor"
    default_cmd = config.get("defaults", {}).get("editor")
    if default_cmd:
        return default_cmd, "config defaults.editor"
    for env in ("VISUAL", "EDITOR"):
        val = os.environ.get(env)
        if val:
            return val, f"${env}"
    return "vi", "fallback (vi)"


def resolve_view(file_path: pathlib.Path, live: bool, config: dict) -> tuple[str, str]:
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


def resolve_viewer_configured(file_path: pathlib.Path, live: bool, config: dict) -> tuple[str, str]:
    """Return a viewer only if explicitly configured for this extension. Otherwise empty."""
    ext = file_path.suffix.lstrip(".").lower()
    ext_cfg = config.get("extensions", {}).get(ext, {})
    if live and ext_cfg.get("viewer_live"):
        return ext_cfg["viewer_live"], f"config extensions.{ext}.viewer_live"
    if ext_cfg.get("viewer"):
        return ext_cfg["viewer"], f"config extensions.{ext}.viewer"
    return "", f"no viewer configured for .{ext}"


def _editor_bin(editor_cmd: str) -> str:
    tokens = shlex.split(editor_cmd)
    if not tokens:
        return ""
    bin_path = tokens[0]
    return os.path.basename(bin_path)


def resolve_editor_flag(editor_cmd: str, kind: str, config: dict) -> tuple[str, str]:
    """kind ∈ {'edit_flag', 'readonly_flag'}. User config wins over built-in."""
    binary = _editor_bin(editor_cmd)
    user_cfg = config.get("editors", {}).get(binary, {})
    if kind in user_cfg:
        return user_cfg[kind], f"config editors.{binary}.{kind}"
    if binary in BUILTIN_EDITORS and kind in BUILTIN_EDITORS[binary]:
        return BUILTIN_EDITORS[binary][kind], f"built-in {binary}.{kind}"
    return "", f"no {kind} known for {binary!r}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="role", required=True)

    pe = sub.add_parser("edit")
    pe.add_argument("path")
    pe.add_argument("--override", default=None)

    pv = sub.add_parser("view")
    pv.add_argument("path")
    pv.add_argument("--live", action="store_true")

    pvc = sub.add_parser("viewer-configured")
    pvc.add_argument("path")
    pvc.add_argument("--live", action="store_true")

    pef = sub.add_parser("edit-flag")
    pef.add_argument("editor_cmd")

    prf = sub.add_parser("readonly-flag")
    prf.add_argument("editor_cmd")

    for sp in (pe, pv, pvc, pef, prf):
        sp.add_argument("--provenance", action="store_true",
                        help="Print a second line to stderr naming the source.")

    args = p.parse_args()

    if args.role in ("edit", "view", "viewer-configured"):
        file_path = pathlib.Path(args.path).expanduser().resolve()
        config = load_config(file_path)
        if args.role == "edit":
            cmd, prov = resolve_edit(file_path, args.override, config)
        elif args.role == "view":
            cmd, prov = resolve_view(file_path, args.live, config)
        else:
            cmd, prov = resolve_viewer_configured(file_path, args.live, config)
    else:
        # edit-flag / readonly-flag — no file path, use cwd for repo-config discovery.
        config = load_config(pathlib.Path.cwd())
        kind = "edit_flag" if args.role == "edit-flag" else "readonly_flag"
        cmd, prov = resolve_editor_flag(args.editor_cmd, kind, config)

    print(cmd)
    if args.provenance:
        print(prov, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
