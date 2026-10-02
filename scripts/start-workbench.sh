#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python_bin="${NGOPILOT_PYTHON:-python3}"
if [[ ! -x .venv-workbench/bin/python ]]; then
  "$python_bin" -m venv .venv-workbench
  .venv-workbench/bin/pip install -e './MCPcode' -r deployment/workbench/requirements.txt
fi
export NGOPILOT_MCP_STATE_DIR="${NGOPILOT_MCP_STATE_DIR:-$PWD/.local-workbench}"
.venv-workbench/bin/ngopilot-mcp bootstrap
exec .venv-workbench/bin/python -m deployment.workbench.run "$@"
