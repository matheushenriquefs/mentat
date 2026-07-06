#!/usr/bin/env bash
set -euo pipefail

# ROI test-reviewer eval (CS1): the reviewer flags padding, passes a lean behavior
# suite, and rejects a 100%-coverage assertion-free suite. Needs ANTHROPIC_API_KEY.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT="${1:-/tmp/test-roi-current.json}"

npx promptfoo eval -c "${SCRIPT_DIR}/promptfooconfig.yaml" --output "$OUTPUT" --no-progress-bar
