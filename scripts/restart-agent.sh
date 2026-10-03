#!/bin/sh
# Reload the operator-owned Foundry configuration; preserve all data.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test -f "$repo_root/.local-agent/foundry.env" || { echo 'Create .local-agent/foundry.env from deployment/foundry.env.example first.' >&2; exit 1; }
docker restart "${NGOPILOT_LOCAL_CONTAINER:-ngopilot-agent-local}"
echo 'NGOPilot restarted. Refresh http://127.0.0.1:8310. Scheduler reads the same configuration on each extraction.'
