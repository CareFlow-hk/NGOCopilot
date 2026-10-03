"""Opt-in live acceptance of the REAL Agent through its ACP transport.

Only authored synthetic fixtures are uploaded. The harness acts as a test human
at the same review endpoint used by the UI; it does not grant the Agent a new
approval tool or modify workflow state. No secrets or raw model reasoning are
printed. Run only against the loopback local launcher.
"""

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[2]
TOOLS = {
    "paper": "careflow_paper_forms_to_excel",
    "meeting": "careflow_meeting_notes",
    "government": "careflow_government_forms",
    "roster": "roster_copilot",
    "scheduler": "activity_scheduler",
}
PROMPTS = {
    "paper": "把這張合成義工探訪表格整理成 Excel，先讓我在任務卡核對。",
    "meeting": "請把這份合成的內部會議轉寫稿按附上的 Word 範本整理成會議記錄，先給我核對。",
    "government": "請用以下合成測試資料填樂悠咭申請表，先讓我核對後才產生 PDF：英文姓氏 TEST，名字 PERSON，中文姓名測試人士，出生日期1950年1月2日，住宅電話00000000。未提供的欄位留空，不要推測。",
    "roster": "這是合成示範團隊的 HC 時間表和護送總表。請安排2026年10月5日開始的一週人手，先顯示核對結果，再匯出排班草稿。不發佈。",
    "scheduler": "請把附上的合成社區活動小冊子整理成活動日曆，年份是2026年。先讓我核對活動日期與時間，再匯出 ICS 和活動清單。",
}
FILES = {
    "paper": [ROOT / "deployment/workbench/samples/form-synthetic.png"],
    "meeting": [
        ROOT / "deployment/agent-samples/transcript-synthetic.txt",
        ROOT / "deployment/workbench/samples/meeting-template.docx",
    ],
    "government": [],
    "scheduler": [ROOT / "deployment/agent-samples/activity-brochure-synthetic.pdf"],
    "roster": [
        ROOT / "deployment/agent-samples/HC-synthetic.xlsx",
        ROOT / "deployment/agent-samples/Escort-synthetic.xlsx",
    ],
}


def envelopes(value):
    if isinstance(value, dict):
        if value.get("job_id") and value.get("tool") in TOOLS.values():
            yield value
        for child in value.values():
            yield from envelopes(child)
    elif isinstance(value, list):
        for child in value:
            yield from envelopes(child)
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            yield from envelopes(json.loads(value))
        except (ValueError, RecursionError):
            pass


class Agent:
    def __init__(self, websocket):
        self.ws = websocket
        self.ident = 0
        self.jobs = {}
        self.messages = []
        self.calls = []

    async def rpc(self, method, params, timeout=300):
        self.ident += 1
        ident = self.ident
        await self.ws.send(
            json.dumps(
                {"jsonrpc": "2.0", "id": ident, "method": method, "params": params}
            )
        )
        async with asyncio.timeout(timeout):
            while True:
                item = json.loads(await self.ws.recv())
                for envelope in envelopes(item):
                    self.jobs[envelope["job_id"]] = envelope
                update = item.get("params", {}).get("update", {})
                kind = update.get("sessionUpdate")
                if kind == "agent_message_chunk" and update.get("content", {}).get(
                    "text"
                ):
                    self.messages.append(update["content"]["text"])
                if kind == "tool_call":
                    self.calls.append(update.get("title") or update.get("rawInput"))
                if item.get("id") == ident and "method" not in item:
                    if "error" in item:
                        raise RuntimeError(f"ACP {method}: {item['error']}")
                    return item.get("result", {})
                if "id" in item and "method" in item:
                    await self.ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": item["id"],
                                "error": {
                                    "code": -32601,
                                    "message": "Test client does not implement client-side tools",
                                },
                            }
                        )
                    )

    async def prompt(self, session_id, text):
        return await self.rpc(
            "session/prompt",
            {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
        )


async def run(base, case, output, prompt=None, route_only=False):
    if urlsplit(base).hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("loopback only")
    async with httpx.AsyncClient(base_url=base, timeout=120) as client:
        response = await client.get("/api/auth/me")
        response.raise_for_status()
        placeholders = []
        for path in FILES[case]:
            ident = str(uuid4())
            placeholder = f"ngopilot-upload://{ident}/{quote(path.name)}"
            with path.open("rb") as stream:
                response = await client.post(
                    "/api/uploads",
                    data={"upload_id": ident, "placeholder": placeholder},
                    files={"file": (path.name, stream)},
                )
            response.raise_for_status()
            placeholders.append(placeholder)
        url = (await client.post("/api/ws-tickets")).json()["url"]
        cookie = "; ".join(f"{key}={value}" for key, value in client.cookies.items())
        async with connect(
            url,
            origin=base,
            additional_headers={"Cookie": cookie},
            max_size=64 * 1024 * 1024,
        ) as ws:
            agent = Agent(ws)
            await agent.rpc(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {},
                    "clientInfo": {"name": "synthetic-acceptance", "version": "1"},
                },
            )
            session = await agent.rpc(
                "session/new",
                {
                    "cwd": "/data",
                    "mcpServers": [],
                    "_meta": {"client": "ngopilot-desktop"},
                },
            )
            session_id = session["sessionId"]
            started = time.monotonic()
            print(
                json.dumps(
                    {"case": case, "session_id": session_id, "stage": "prompt"},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            await agent.prompt(
                session_id,
                (prompt or PROMPTS[case])
                + (
                    "\nAttachments: " + json.dumps(placeholders) if placeholders else ""
                ),
            )
            selected = [
                job for job in agent.jobs.values() if job.get("tool") == TOOLS[case]
            ]
            if not selected:
                output.write_text(
                    json.dumps(
                        {
                            "case": case,
                            "session_id": session_id,
                            "calls": agent.calls,
                            "assistant": "".join(agent.messages),
                            "jobs": agent.jobs,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                raise RuntimeError(
                    "Agent did not start the requested workflow; inspect acceptance output"
                )
            job_id = selected[-1]["job_id"]
            job = (await client.get(f"/api/workflows/{job_id}")).json()
            if route_only:
                assert all(
                    item.get("tool") == TOOLS[case] for item in agent.jobs.values()
                ), agent.jobs
                output.write_text(
                    json.dumps(
                        {
                            "case": case,
                            "session_id": session_id,
                            "job_id": job_id,
                            "state": job["state"],
                            "tool": job["tool"],
                            "calls": agent.calls,
                            "assistant": "".join(agent.messages),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                print(
                    json.dumps(
                        {
                            "case": case,
                            "stage": "routing_pass",
                            "tool": job["tool"],
                            "state": job["state"],
                        }
                    ),
                    flush=True,
                )
                return
            print(
                json.dumps(
                    {
                        "case": case,
                        "job_id": job_id,
                        "state": job["state"],
                        "stage": "review",
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if job.get("error"):
                raise RuntimeError(str(job["error"]))
            # Inspect real native results before acting as the synthetic test reviewer.
            result = job["result"]
            reviewer = "Synthetic acceptance reviewer"
            if case == "paper":
                first = result["records"][0]
                # The reviewer may flag the deliberately synthetic name as a
                # placeholder. Verify the original extraction, then act as the
                # test human comparing it against the authored fixture.
                assert (
                    first["final_fields"].get("elder_name")
                    or first.get("qwen_original", {}).get("elder_name")
                ) == "Test Person"
                first["final_fields"]["elder_name"] = "Test Person"
                review = {
                    "reviews": [
                        {
                            "record_id": r["id"],
                            "final_fields": r["final_fields"],
                            "reviewer": reviewer,
                        }
                        for r in result["records"]
                    ]
                }
            elif case == "meeting":
                assert result.get("slot_content")
                review = {
                    "slot_content_final": result["slot_content"],
                    "reviewer": reviewer,
                }
            elif case == "government":
                review = {
                    "field_values": {
                        field["key"]: str(field.get("value") or "")
                        for field in result["preview"]["mappings"]
                    },
                    "reviewer": reviewer,
                }
                # This test fixture supplies separate surname and given name explicitly.
                review["field_values"]["family_name_en"] = "TEST"
                review["field_values"]["given_name_en"] = "PERSON"
                assert result["elder_profile"]["date_of_birth"]["iso"] == "1950-01-02"
                assert review["field_values"]["signature_date_year"] == ""
                assert review["field_values"]["signature_date_month"] == ""
                assert review["field_values"]["signature_date_day"] == ""
                assert review["field_values"]["home_number"] == "00000000"
            elif case == "scheduler":
                records = result["activities"]
                assert len(records) == 2, records
                assert {
                    date for record in records for date in record["expanded_dates"]
                } == {"2026-10-12", "2026-10-14"}
                assert all(not record["issues"] for record in records)
                review = {
                    "reviews": [
                        {
                            "id": r["id"],
                            "revision": r["revision"],
                            "data": r["data"],
                            "status": "confirmed",
                            "note": "Compared with authored synthetic source.",
                        }
                        for r in records
                    ],
                    "reviewer": reviewer,
                }
            else:
                assert result.get("base_data_label"), (
                    "Roster must explicitly use a synthetic base"
                )
                pending = [
                    audit
                    for audit in result.get("audit_items", [])
                    if audit["status"] == "pending"
                ]
                if pending:
                    output.write_text(
                        json.dumps(
                            {
                                "case": case,
                                "session_id": session_id,
                                "job": job,
                                "assistant": "".join(agent.messages),
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    raise RuntimeError(
                        "Roster has pending audits; review them explicitly before continuing"
                    )
                review = {}
            operation = "export" if case == "roster" else "review"
            response = await client.post(
                f"/api/workflows/{job_id}/confirm",
                json={
                    "operation": operation,
                    "input": review,
                    "reviewer": reviewer,
                    "revision": job["revision"],
                },
            )
            response.raise_for_status()
            confirmation = response.json()
            await agent.prompt(
                session_id,
                "我已在任務卡核對並按下確認。請用以下已授權的原樣參數調用工具，再完成文件匯出。\n"
                + json.dumps(confirmation, ensure_ascii=False),
            )
            job = (await client.get(f"/api/workflows/{job_id}")).json()
            artifacts = []
            for item in job["artifacts"]:
                link = (
                    await client.get(
                        "/api/artifacts/url", params={"path": item["path"]}
                    )
                ).json()
                response = await client.get(link["url"])
                response.raise_for_status()
                assert hashlib.sha256(response.content).hexdigest() == item["sha256"]
                destination = output.parent / (case + "-" + Path(item["path"]).name)
                destination.write_bytes(response.content)
                artifacts.append(
                    {
                        "filename": destination.name,
                        "sha256": item["sha256"],
                        "bytes": len(response.content),
                    }
                )
            report = {
                "case": case,
                "session_id": session_id,
                "job_id": job_id,
                "state": job["state"],
                "artifacts": artifacts,
                "elapsed_seconds": round(time.monotonic() - started, 1),
                "calls": agent.calls,
                "assistant": "".join(agent.messages),
                "result": job["result"],
            }
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            if not artifacts:
                raise RuntimeError("Agent did not produce a verified artifact")
            print(
                json.dumps(
                    {
                        k: report[k]
                        for k in (
                            "case",
                            "session_id",
                            "job_id",
                            "state",
                            "artifacts",
                            "elapsed_seconds",
                        )
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8310")
    p.add_argument("--case", choices=list(TOOLS), required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--prompt")
    p.add_argument("--route-only", action="store_true")
    args = p.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(args.base, args.case, args.output, args.prompt, args.route_only))
