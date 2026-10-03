"""Additional live phrasings plus an ambiguous request (synthetic data only)."""

import asyncio
import json
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

from live_acceptance import Agent, run

CASES = [
    ("paper", "幫我把義工手寫探訪單輸入試算表。附件是合成例子，先給我核對辨識內容。"),
    ("paper", "這是測試探訪記錄照片，想轉成可以在 Excel 打開的表格，請先辨識並整理。"),
    (
        "meeting",
        "這份 Word 是格式，WAV 是合成內部例會錄音。幫我按範本寫會議紀錄，保留未確定事項。",
    ),
    (
        "meeting",
        "請把附件的合成內部會議聲音轉寫並總結，再依照附帶 DOCX 排版，讓我先看草稿。",
    ),
    (
        "government",
        "替測試人士準備樂悠咭申請。合成資料：英文姓 TEST，名字 PERSON，1950年1月2日出生。沒有提供的資料留白，先顯示填表預覽。",
    ),
    (
        "government",
        "我需要一份填好的樂悠咭 PDF。先用這些合成資料建立待核對內容：TEST PERSON，1950-01-02出生，電話00000000；未提供的欄位保持空白。",
    ),
    (
        "roster",
        "請依合成 HC-synthetic.xlsx 家居照顧時段和 Escort-synthetic.xlsx 護送總表編2026-10-05這週的人手，使用合成示範團隊資料，先給我排班草稿，不發佈。",
    ),
    (
        "roster",
        "把附件兩份合成工作表安排到員工工作分工表，目標週由2026年10月5日開始。HC 是家居照顧，Escort 是護送；只用合成示範人員，先核對。",
    ),
]


async def main():
    base = "http://127.0.0.1:8310"
    root = Path("/private/tmp/ngopilot-agent-20261003/acceptance/routing")
    root.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(2)

    async def route(index, case, prompt):
        async with semaphore:
            await run(base, case, root / f"{index}-{case}.json", prompt, True)

    results = await asyncio.gather(
        *(route(i, case, prompt) for i, (case, prompt) in enumerate(CASES)),
        return_exceptions=True,
    )
    for index, value in enumerate(results):
        if isinstance(value, Exception):
            print(
                json.dumps({"routing_failure": index, "error": str(value)}), flush=True
            )
    async with httpx.AsyncClient(base_url=base) as client:
        (await client.get("/api/auth/me")).raise_for_status()
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
                "initialize", {"protocolVersion": 1, "clientCapabilities": {}}
            )
            session = await agent.rpc("session/new", {"cwd": "/data", "mcpServers": []})
            await agent.prompt(session["sessionId"], "幫我安排一下下星期。")
            text = "".join(agent.messages)
            report = {
                "session_id": session["sessionId"],
                "assistant": text,
                "jobs": agent.jobs,
                "calls": agent.calls,
            }
            (root / "ambiguous.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2)
            )
            assert not agent.jobs and ("?" in text or "？" in text), report
            print(
                json.dumps(
                    {"ambiguous": "clarified_without_starting", "assistant": text},
                    ensure_ascii=False,
                ),
                flush=True,
            )
    if any(isinstance(value, Exception) for value in results):
        raise RuntimeError("Some routing cases failed; inspect evidence.")


if __name__ == "__main__":
    asyncio.run(main())
