#!/bin/sh
# Consistent backup of this service only. Does not remove previous backups.
set -eu
umask 077
cd /opt/ngopilot
backup_dir=/opt/ngopilot-backups
mkdir -p "$backup_dir"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
file="$backup_dir/ngopilot-$stamp.tar.gz"
docker compose stop pilot
trap 'docker compose start pilot' EXIT HUP INT TERM
tar -czf "$file" -C /opt ngopilot/data ngopilot/compose.yaml ngopilot/.env ngopilot-secrets/foundry.env
sha256sum "$file" > "$file.sha256"
