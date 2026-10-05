# NGOPilot VPS deployment

Status (2026-10-05): deployed on the VPS at loopback port 8310 and published, following explicit user confirmation, at https://pilot-careflow.jiahangxu.com through the existing Cloudflare Tunnel. Cloudflare confirmed both route and DNS creation. Public DNS resolvers 1.1.1.1 and 8.8.8.8 resolve the hostname. HTTPS health returned 200 and anonymous API access returned 401 using the resolved public address with full certificate verification. The local resolver still returned NXDOMAIN during final checks, so Safari and interactive account login remain pending local DNS propagation.

Verified image: `ngopilot-agent:vps-20261004`, amd64, image ID `f2badca86c1641b92e3caa13199ccccf53a891e8301db7c98c37850c6d2ba0aa`. Archive SHA-256: `0391cb8a69caefb01a1ae068c469806814a6d18ae24b2c8afb026b43684efb31` (matched after user upload).

The container is healthy; anonymous `/api/auth/me` returned 401; idle memory was about 78 MiB. A real Foundry Responses request completed using `gpt-6-luna` from this VPS. The first administrator was initialized using the user-supplied email; password setup remains for the user. One consistent private backup was created; automatic backup scheduling is not configured. Existing CareFlow and Atlas containers remained running. Temporary SSH access was revoked after setup.

This deployment retains the invitation-only account UI and the original Agent. The user explicitly chose VPS persistent storage instead of GCS on 2026-10-04. No new cloud storage provider is introduced.

## Build

Build from the repository root, with the frontend already built:

```sh
docker build --platform linux/amd64 -f deployment/backend/Dockerfile -t ngopilot-base:vps-5583c94 .
docker build --platform linux/amd64 --build-arg AGENT_BASE=ngopilot-base:vps-5583c94 -f deployment/backend/Local.Dockerfile -t ngopilot-agent:vps-20261004 .
```

The base includes the original Rust Agent and independent algorithm environments. `algo-dependencies/` is not modified. Do not copy an ARM64 image to the x86_64 VPS.

## Private configuration

Place `compose.yaml` in `/opt/ngopilot`. Create an operator-owned `.env` there containing only the image tag and HTTPS origin. Keep the Foundry key in `/opt/ngopilot-secrets/foundry.env`, readable by service UID 10001, outside all source packages. Its variables are `FOUNDRY_ENDPOINT`, `FOUNDRY_DEPLOYMENT=gpt-6-luna`, and `FOUNDRY_API_KEY`. Never print the file or include it in Git or the image.

The gateway retains `APP_ENV=local` to select the invitation-account implementation; `NGOPILOT_HTTPS_DEPLOYMENT=true` is its explicit VPS boundary. It requires an HTTPS origin and secure cookies, enforces exact Host/Origin, and produces WSS tickets. Only 127.0.0.1:8310 is published. Route a dedicated HTTPS Tunnel hostname to that port while preserving the public Host header.

The existing shared Scheduler is deliberately rejected in this mode; it requires account isolation before connection. Do not publish port 8311 as a workaround.

## Verification and recovery

1. Validate `docker compose config --quiet`.
2. Keep old image references and run `backup.sh` before future upgrades.
3. Start only this Compose project: `docker compose up -d` (never remove orphans or volumes).
4. Verify container health, anonymous API 401, login, admin/member separation, ACP connection, a Luna response and a generated document download.
5. Verify the same flow through the public HTTPS hostname; no localhost link may be returned to a remote user.
6. Bootstrap the administrator with `docker exec -u ngopilot ngopilot-vps python -m ngopilot_gateway.local_accounts bootstrap EMAIL NAME`. Deliver the resulting one-time link privately; the user chooses their own password.
7. `backup.sh` takes a consistent snapshot by stopping only Pilot briefly, and restarts it with a shell trap. Backups contain secrets and must remain mode 0600 in a private directory. The script never deletes older backups. Scheduling and off-host backup must be explicitly recorded once configured.

For rollback, select the retained previous image in `.env` and recreate only `pilot`. Never overwrite or remove the data directory during rollback; schema compatibility must be checked first.
