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
import shutil
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


# Viewers that self-watch or have their own reload mechanism. The
# entr auto-wrapper skips these — wrapping would either fight their
# built-in watcher or never work (opening an external app).
SELF_WATCHING_VIEWERS: frozenset[str] = frozenset({
    "code",          # VS Code watches the filesystem itself.
    "subl",          # Sublime Text same.
    "cmux",          # `cmux browser open ...` — cmux handles its own lifecycle.
    "open",          # macOS `open` hands off to the registered app.
    "xdg-open",      # Linux equivalent; same reasoning.
})


# Flags on specific viewers that switch them into an alt-screen / pager
# TUI mode. entr's SIGTERM leaves those TUI processes in stopped (T)
# state instead of killing them cleanly, so hot-reload breaks silently.
# We strip these flags from the *synthesized* viewer_live command; the
# non-live path (/ed:view without --live) keeps them as configured.
TUI_FLAGS_TO_STRIP: dict[str, frozenset[str]] = {
    "glow":  frozenset({"-p", "--pager"}),
    "bat":   frozenset({"--paging=always"}),
}


# Viewers that stay in alt-screen mode no matter what flags you pass.
# entr -r can't restart them cleanly. Emit a warning when autowrap is
# about to apply to one of these; users can opt out with --no-autowrap
# or an explicit viewer_live.
ALT_SCREEN_VIEWERS: frozenset[str] = frozenset({
    "frogmouth",    # Textual app; doesn't exit cleanly on SIGTERM.
    "mdless",       # Wraps less internally.
    "less",         # Always alt-screen; user probably didn't mean this as a viewer.
})


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


def _viewer_bin(viewer_cmd: str) -> str:
    tokens = shlex.split(viewer_cmd)
    if not tokens:
        return ""
    return os.path.basename(tokens[0])


def _entr_available() -> bool:
    return shutil.which("entr") is not None


def _wrap_with_entr(viewer_cmd: str) -> str:
    """Wrap a non-watching viewer so entr restarts it on file change.

    Uses a bash -c wrapper where $1 is the file path supplied by the caller:
        bash -c 'echo "$1" | entr -r <viewer-cmd> "$1"' --

    Returns a string the skill can shell in as:
        <wrapper> <file-path>
    The trailing `--` is the bash argv[0]; $1 takes the path. This keeps
    quoting correct even for paths with spaces.
    """
    # shlex.quote the inner command string so any single quotes inside
    # viewer_cmd survive the `bash -c '...'` outer quoting.
    inner = f'echo "$1" | entr -r {viewer_cmd} "$1"'
    return f"bash -c {shlex.quote(inner)} --"


def _strip_tui_flags(viewer_cmd: str) -> tuple[str, list[str]]:
    """Strip known alt-screen/pager flags for the entr-wrapped path.

    Returns (stripped_cmd, removed_flags). Only applies to viewers listed
    in TUI_FLAGS_TO_STRIP — unknown binaries pass through unchanged.

    Rationale: glow -p enters Bubble Tea alt-screen mode; SIGTERM from
    entr leaves it in stopped (T) state, breaking hot-reload. Plain glow
    prints to stdout and exits, so entr can restart it cleanly. The
    non-wrapped /ed:view path still keeps the flag for interactive use.
    """
    tokens = shlex.split(viewer_cmd)
    if not tokens:
        return viewer_cmd, []
    bin_name = os.path.basename(tokens[0])
    strippable = TUI_FLAGS_TO_STRIP.get(bin_name)
    if not strippable:
        return viewer_cmd, []
    kept = [tokens[0]]
    removed = []
    for tok in tokens[1:]:
        if tok in strippable or (tok.startswith("--") and tok.split("=", 1)[0] + "=" in strippable):
            removed.append(tok)
        else:
            kept.append(tok)
    return shlex.join(kept), removed


def _maybe_autowrap_live(viewer_cmd: str) -> tuple[str, str]:
    """Auto-wrap viewer_cmd with entr for hot-reload if possible.

    Returns (wrapped_or_passthrough_cmd, synthesis_note).
    Skip rules:
      - The viewer's binary is in SELF_WATCHING_VIEWERS (already handles reload).
      - entr is not on PATH (caller should emit a stderr hint).

    Before wrapping, strip TUI/alt-screen flags that break entr -r (e.g.
    glow -p) and emit a warning when the viewer is in ALT_SCREEN_VIEWERS
    (unconditionally alt-screen; entr won't restart cleanly).
    """
    bin_name = _viewer_bin(viewer_cmd)
    if bin_name in SELF_WATCHING_VIEWERS:
        return viewer_cmd, f"passthrough ({bin_name} self-watches)"
    if not _entr_available():
        return viewer_cmd, "passthrough (entr not installed — tip: brew install entr)"

    stripped, removed = _strip_tui_flags(viewer_cmd)
    note_parts = [f"synthesized viewer_live (entr -r {bin_name})"]
    if removed:
        note_parts.append(f"stripped TUI flags: {' '.join(removed)}")
    if bin_name in ALT_SCREEN_VIEWERS:
        note_parts.append(
            f"WARN: {bin_name} is always alt-screen; entr restart may not work cleanly"
        )
    return _wrap_with_entr(stripped), "; ".join(note_parts)


def resolve_view(file_path: pathlib.Path, live: bool, config: dict) -> tuple[str, str]:
    ext = file_path.suffix.lstrip(".").lower()
    ext_cfg = config.get("extensions", {}).get(ext, {})

    if live and ext_cfg.get("viewer_live"):
        return ext_cfg["viewer_live"], f"config extensions.{ext}.viewer_live"
    if ext_cfg.get("viewer"):
        base = ext_cfg["viewer"]
        prov = f"config extensions.{ext}.viewer"
        if live:
            wrapped, note = _maybe_autowrap_live(base)
            return wrapped, f"{prov} + {note}"
        return base, prov
    default_cmd = config.get("defaults", {}).get("viewer")
    if default_cmd:
        prov = "config defaults.viewer"
        if live:
            wrapped, note = _maybe_autowrap_live(default_cmd)
            return wrapped, f"{prov} + {note}"
        return default_cmd, prov
    for env in ("VIEWER", "ED_DEFAULT_VIEWER"):
        val = os.environ.get(env)
        if val:
            prov = f"${env}"
            if live:
                wrapped, note = _maybe_autowrap_live(val)
                return wrapped, f"{prov} + {note}"
            return val, prov
    return "less", "fallback (less)"


def resolve_viewer_configured(file_path: pathlib.Path, live: bool, config: dict) -> tuple[str, str]:
    """Return a viewer only if explicitly configured for this extension. Otherwise empty."""
    ext = file_path.suffix.lstrip(".").lower()
    ext_cfg = config.get("extensions", {}).get(ext, {})
    if live and ext_cfg.get("viewer_live"):
        return ext_cfg["viewer_live"], f"config extensions.{ext}.viewer_live"
    if ext_cfg.get("viewer"):
        base = ext_cfg["viewer"]
        prov = f"config extensions.{ext}.viewer"
        if live:
            wrapped, note = _maybe_autowrap_live(base)
            return wrapped, f"{prov} + {note}"
        return base, prov
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
    pv.add_argument("--no-autowrap", action="store_true",
                    help="Disable entr auto-wrap when --live is set.")

    pvc = sub.add_parser("viewer-configured")
    pvc.add_argument("path")
    pvc.add_argument("--live", action="store_true")
    pvc.add_argument("--no-autowrap", action="store_true",
                     help="Disable entr auto-wrap when --live is set.")

    pef = sub.add_parser("edit-flag")
    pef.add_argument("editor_cmd")

    prf = sub.add_parser("readonly-flag")
    prf.add_argument("editor_cmd")

    pea = sub.add_parser("entr-available",
                         help="Exit 0 and print 'yes' if entr is on PATH, else print 'no' (still exit 0).")

    for sp in (pe, pv, pvc, pef, prf, pea):
        sp.add_argument("--provenance", action="store_true",
                        help="Print a second line to stderr naming the source.")

    args = p.parse_args()

    if args.role in ("edit", "view", "viewer-configured"):
        file_path = pathlib.Path(args.path).expanduser().resolve()
        config = load_config(file_path)
        if args.role == "edit":
            cmd, prov = resolve_edit(file_path, args.override, config)
        else:
            effective_live = args.live and not getattr(args, "no_autowrap", False)
            # Sub-note: the autowrap path only kicks in when live is True *and* no
            # explicit viewer_live is configured. --no-autowrap forces live=False
            # for the resolver so the regular viewer is returned unwrapped.
            if args.role == "view":
                cmd, prov = resolve_view(file_path, effective_live, config)
            else:
                cmd, prov = resolve_viewer_configured(file_path, effective_live, config)
    elif args.role == "entr-available":
        available = _entr_available()
        cmd = "yes" if available else "no"
        prov = "entr on PATH" if available else "entr not installed (brew install entr)"
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
