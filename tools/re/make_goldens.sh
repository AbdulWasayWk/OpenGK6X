#!/usr/bin/env bash
# Regenerate tests/golden/*.json: the packets the official app's own code writes for each tests/fixtures/profiles/*.json.
# Needs node and the unpacked app (vendor-app/asar, see CLAUDE.md).
set -euo pipefail
cd "$(dirname "$0")/../.."
for f in tests/fixtures/profiles/*.json; do
    node tools/re/golden_profile.js vendor-app/asar "$f" "tests/golden/$(basename "$f")" tests/fixtures 2>&1 \
        | grep -E 'packets ->|error' || true
done
