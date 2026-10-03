#!/bin/sh
# Original Chatbot + original Agent + NGO MCP tools, published on loopback only.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$#" -ne 2 ] || [ "$1" != "--env-file" ]; then
  echo "Usage: scripts/start-agent.sh --env-file /absolute/operator/provider.env" >&2
  exit 2
fi
provider_file=$2
case "$provider_file" in /*) ;; *) echo "Use an absolute provider file path" >&2; exit 2 ;; esac
test -f "$provider_file"
test -f "$repo_root/deployment/frontend/dist/index.html" || {
  echo "Build deployment/frontend with Node 24 and npm run build first." >&2; exit 1;
}
agent_port=${NGOPILOT_LOCAL_PORT:-8310}
agent_image=${NGOPILOT_LOCAL_IMAGE:-ngopilot-agent:luna}
agent_name=${NGOPILOT_LOCAL_CONTAINER:-ngopilot-agent-local}
agent_data=${NGOPILOT_LOCAL_DATA_DIR:-$repo_root/.local-agent}
mkdir -p "$agent_data"
chmod 700 "$agent_data"
docker image inspect "$agent_image" >/dev/null
if docker container inspect "$agent_name" >/dev/null 2>&1; then
  echo "Container $agent_name already exists. Use docker start $agent_name, or stop and remove that container before recreating it. Data remains in .local-agent/." >&2
  exit 1
fi
docker run -d --name "$agent_name" --restart unless-stopped \
  -p "127.0.0.1:$agent_port:$agent_port" \
  --mount "type=bind,src=$agent_data,dst=/data" \
  --mount "type=bind,src=$provider_file,dst=/run/ngopilot-provider.env,readonly" \
  -e "PORT=$agent_port" -e "PUBLIC_API_URL=http://127.0.0.1:$agent_port" \
  -e MAX_UPLOAD_BYTES=104857600 \
  -e "NGOPILOT_ROSTER_SAMPLE=${NGOPILOT_ROSTER_SAMPLE:-false}" \
  -e "NGOPILOT_SCHEDULER_URL=${NGOPILOT_SCHEDULER_URL:-}" \
  -e "NGOPILOT_SCHEDULER_BROWSER_URL=${NGOPILOT_SCHEDULER_BROWSER_URL:-http://127.0.0.1:8311}" \
  "$agent_image"
echo "NGOPilot Agent: http://127.0.0.1:$agent_port"
