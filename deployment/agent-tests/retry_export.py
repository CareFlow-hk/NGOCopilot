"""Resume a failed synthetic acceptance session and verify export recovery."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

from live_acceptance import Agent


async def run(base, path):
    report = json.loads(path.read_text())
    async with httpx.AsyncClient(base_url=base, timeout=120) as client:
        (await client.get("/api/auth/me")).raise_for_status()
        url = (await client.post("/api/ws-tickets")).json()["url"]
        cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
        async with connect(
            url,
            origin=base,
            additional_headers={"Cookie": cookie},
            max_size=64 * 1024 * 1024,
        ) as ws:
            agent = Agent(ws)
            await agent.rpc(
                "initialize", {"protocolVersion": 1, "clientCapabilities": {}}
            )
            await agent.rpc(
                "session/load",
                {"sessionId": report["session_id"], "cwd": "/data", "mcpServers": []},
            )
            await agent.prompt(
                report["session_id"],
                "請重試剛才的 PDF 匯出，沿用已在任務卡核對的內容，不改動資料。管理員已修正匿名檔名相容問題，不需要另加個案編號。",
            )
        job = (await client.get(f"/api/workflows/{report['job_id']}")).json()
        assert job["state"] == "exported" and job["artifacts"], job.get("error")
        report["state"] = job["state"]
        report["result"] = job["result"]
        report["artifacts"] = []
        report["recovery_assistant"] = "".join(agent.messages)
        for item in job["artifacts"]:
            link = (
                await client.get("/api/artifacts/url", params={"path": item["path"]})
            ).json()
            response = await client.get(link["url"])
            response.raise_for_status()
            assert hashlib.sha256(response.content).hexdigest() == item["sha256"]
            output = path.parent / (path.stem + "-" + Path(item["path"]).name)
            output.write_bytes(response.content)
            report["artifacts"].append(
                {
                    "filename": output.name,
                    "sha256": item["sha256"],
                    "bytes": len(response.content),
                }
            )
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {
                    "case": report["case"],
                    "job_id": report["job_id"],
                    "state": job["state"],
                    "artifacts": report["artifacts"],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8310")
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    asyncio.run(run(args.base, args.report))
