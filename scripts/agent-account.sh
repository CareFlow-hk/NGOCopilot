#!/bin/sh
# Operator account commands for the running local Agent; prints a one-time link.
#   scripts/agent-account.sh bootstrap admin@example.org 管理員姓名
#   scripts/agent-account.sh recover-admin admin@example.org
set -eu
if [ "$#" -lt 2 ]; then
  echo "Usage: scripts/agent-account.sh bootstrap EMAIL NAME | recover-admin EMAIL" >&2
  exit 2
fi
exec docker exec -u ngopilot "${NGOPILOT_LOCAL_CONTAINER:-ngopilot-agent-local}" \
  python -m ngopilot_gateway.local_accounts "$@"
