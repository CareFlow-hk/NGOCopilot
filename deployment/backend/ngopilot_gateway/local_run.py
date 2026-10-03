"""Load operator-owned model settings without copying secrets into the project."""

import argparse
import os
from pathlib import Path

import uvicorn
from dotenv import dotenv_values

from .config import Settings
from .local import create_local_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    # Only the dedicated Foundry configuration is loaded. Old provider keys
    # are intentionally never inherited by the Agent or tool subprocesses.
    for key in list(os.environ):
        if key.startswith(
            ("DEEPSEEK_", "DASHSCOPE_", "BAILIAN_", "OPENROUTER_", "AZURE_OPENAI_", "OPENAI_")
        ):
            os.environ.pop(key)
    if args.env_file:
        for key, value in dotenv_values(args.env_file).items():
            if value and key.startswith(("FOUNDRY_", "NGOPILOT_ROSTER_")):
                os.environ.setdefault(key, value)
    from ngopilot_mcp.shared.foundry import configuration

    endpoint, model, api_key = configuration()
    os.environ.update(
        {
            "NGOPILOT_AI_PROVIDER": "foundry",
            "GOOSE_PROVIDER": "openai",
            "GOOSE_MODEL": model,
            "OPENAI_BASE_URL": endpoint,
            "OPENAI_BASE_PATH": "v1/responses",
            # Keeps the original Agent available for history browsing. The gateway
            # blocks prompts until a real key exists; this value is never sent.
            "OPENAI_API_KEY": api_key or "unconfigured",
        }
    )
    os.environ["APP_ENV"] = "local"
    if os.getenv("NGOPILOT_ROSTER_SAMPLE") == "true":
        os.environ["NGOPILOT_ROSTER_DIVISION_TEMPLATE"] = (
            "/opt/ngopilot/agent-samples/roster-division-synthetic.xlsx"
        )
        os.environ["NGOPILOT_ROSTER_MASTER_DATA"] = (
            "/opt/ngopilot/agent-samples/roster-master-synthetic.json"
        )
        os.environ["NGOPILOT_ROSTER_DATA_LABEL"] = (
            "合成示範團隊；所有人員、技能和個案均為測試資料。"
        )
    settings = Settings()
    # Uvicorn logs WebSocket URLs at INFO, including one-use connection tickets.
    uvicorn.run(
        create_local_app(settings),
        host="0.0.0.0",
        port=settings.port,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
