#!/usr/bin/env bash
# Find a Python3 that has requests_oauthlib installed.
# Usage: eval "$(bash scripts/find-python.sh)"
#   Sets CURAITOR_PYTHON to the correct python3 path.

for py in /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$py" >/dev/null 2>&1; then
        if "$py" -c "import requests_oauthlib, yaml" 2>/dev/null; then
            echo "export CURAITOR_PYTHON=$py"
            exit 0
        fi
    fi
done

echo "echo 'ERROR: No python3 with requests_oauthlib and pyyaml found. Run: pip3 install requests-oauthlib pyyaml' >&2; exit 1"
