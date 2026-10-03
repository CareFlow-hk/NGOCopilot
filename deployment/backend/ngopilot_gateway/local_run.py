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
    if args.env_file:
        for key, value in dotenv_values(args.env_file).items():
            if value and key.startswith(
                (
                    "DEEPSEEK_",
                    "AZURE_OPENAI_",
                    "DASHSCOPE_",
                    "BAILIAN_",
                    "OPENROUTER_",
                    "NGOPILOT_ROSTER_",
                )
            ):
                os.environ.setdefault(key, value)
    # The Agent and the tools may use different providers. Neither is configured
    # by frontline users and no model keys are sent to the browser.
    if os.getenv("NGOPILOT_AGENT_BACKEND") == "azure":
        # Azure's v1 endpoint is OpenAI-compatible; the legacy Azure provider
        # appends a deployments path and api-version query which v1 rejects.
        os.environ["GOOSE_PROVIDER"] = "openai"
        os.environ["GOOSE_MODEL"] = os.environ["AZURE_OPENAI_DEPLOYMENT"]
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
        os.environ["OPENAI_BASE_URL"] = (
            endpoint if endpoint.endswith("/openai/v1") else endpoint + "/openai/v1"
        )
        os.environ["OPENAI_API_KEY"] = os.environ["AZURE_OPENAI_API_KEY"]
    elif not os.getenv("GOOSE_PROVIDER"):
        if os.getenv("OPENROUTER_API_KEY"):
            os.environ["GOOSE_PROVIDER"] = "openrouter"
            os.environ.setdefault("GOOSE_MODEL", "moonshotai/kimi-k2.6")
        elif os.getenv("DEEPSEEK_API_KEY"):
            os.environ["GOOSE_PROVIDER"] = "openai"
            os.environ["GOOSE_MODEL"] = os.getenv("DEEPSEEK_TEXT_MODEL", "deepseek-v4-flash")
            os.environ["OPENAI_BASE_URL"] = os.getenv(
                "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
            )
            os.environ["OPENAI_API_KEY"] = os.environ["DEEPSEEK_API_KEY"]
        else:
            raise SystemExit("Operator setup required: provide an Agent provider before launching.")
    os.environ["AZURE_OPENAI_API_VERSION"] = os.getenv(
        "NGOPILOT_AZURE_API_VERSION", "2025-04-01-preview"
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
