#!/usr/bin/env python3
"""Guess split orientation ('horizontal' or 'vertical') from attached displays.

Prints one of: 'horizontal' or 'vertical' on stdout.

Heuristic: if at least one non-internal (external) display is attached, the
user is probably docked at a desk and wants the viewer pane stacked BELOW
the editor/Claude pane (vertical). Otherwise — laptop only — split to the
right (horizontal).

Known limitation: macOS lists every connected display but doesn't expose
which one cmux is on. A user who docks but keeps the laptop's built-in
screen as primary (and puts cmux there) will still get 'vertical'.
They can override with ED_MONITOR=horizontal.

Fails open to 'horizontal' on any error (non-Darwin, missing
system_profiler, malformed JSON, timeout).
"""

import json
import subprocess
import sys


def detect() -> str:
    try:
        out = subprocess.run(
            ["system_profiler", "-json", "SPDisplaysDataType"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "horizontal"
    if out.returncode != 0:
        return "horizontal"
    try:
        data = json.loads(out.stdout)
    except ValueError:
        return "horizontal"

    externals = 0
    for gpu in data.get("SPDisplaysDataType", []):
        for dev in gpu.get("spdisplays_ndrvs", []):
            # External displays typically have no `spdisplays_connection_type`
            # field at all; the built-in panel is the only entry tagged
            # `spdisplays_internal`. Anything else counts as external.
            if dev.get("spdisplays_connection_type") != "spdisplays_internal":
                externals += 1

    return "vertical" if externals >= 1 else "horizontal"


if __name__ == "__main__":
    print(detect())
    sys.exit(0)
