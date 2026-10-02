"""Run from repository root: python -m deployment.workbench.run [--env-file /path/.env]."""

import argparse
import os
from pathlib import Path
from dotenv import load_dotenv
import uvicorn

parser = argparse.ArgumentParser()
parser.add_argument("--env-file", type=Path)
parser.add_argument("--port", type=int, default=8310)
args = parser.parse_args()
if args.env_file:
    load_dotenv(args.env_file, override=False)
# Native CareFlow uses the dated Azure route. Model release dates are NOT API versions.
# Local override only; never edit the dependency or the user's original provider file.
os.environ["AZURE_OPENAI_API_VERSION"] = os.getenv(
    "NGOPILOT_AZURE_API_VERSION", "2025-04-01-preview"
)
uvicorn.run(
    "deployment.workbench.server:create_app",
    factory=True,
    host="127.0.0.1",
    port=args.port,
    access_log=False,
)
