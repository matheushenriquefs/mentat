#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT="${1:-/tmp/agents-md-current.json}"
CONFIG="${2:-}"

if [[ -z "$CONFIG" ]]; then
  # Substitute $HOME into system path so promptfoo resolves it correctly
  EPHEMERAL_CONFIG="/tmp/agents-md-config-$$.yaml"
  python3 - <<PYEOF
import yaml, sys, os
c = yaml.safe_load(open('${SCRIPT_DIR}/promptfooconfig.yaml'))
for p in c.get('providers', []):
    if isinstance(p, dict) and 'config' in p and 'system' in p['config']:
        p['config']['system'] = p['config']['system'].replace(
            'file://../../../../.agents/AGENTS.md',
            'file://' + os.path.expanduser('~/.agents/AGENTS.md')
        )
yaml.dump(c, open('${EPHEMERAL_CONFIG}', 'w'), default_flow_style=False)
PYEOF
  CONFIG="$EPHEMERAL_CONFIG"
  trap 'rm -f "$EPHEMERAL_CONFIG"' EXIT
fi

npx promptfoo eval -c "$CONFIG" --output "$OUTPUT" --no-progress-bar
