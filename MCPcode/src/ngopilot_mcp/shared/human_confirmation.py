"""Content-bound approvals written by the authenticated human review surface.

The MCP exposes no approval-granting tool. An Agent can consume an approval for
the exact reviewed payload, but cannot grant one through tool arguments.
"""

import json
import sqlite3
import time
from pathlib import Path

from .errors import ToolError
from .jsonutil import payload_hash


class HumanConfirmations:
    def __init__(self, state_root: Path):
        self.path = state_root / "human-confirmations.sqlite3"
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS confirmations (
                tool TEXT NOT NULL, job_id TEXT NOT NULL, operation TEXT NOT NULL,
                payload_hash TEXT NOT NULL, revision_hash TEXT NOT NULL,
                confirmed_at REAL NOT NULL, reviewer TEXT NOT NULL,
                PRIMARY KEY(tool, job_id, operation))""")
            db.execute("""CREATE TABLE IF NOT EXISTS proposals (
                tool TEXT NOT NULL, job_id TEXT NOT NULL, operation TEXT NOT NULL,
                payload_json TEXT NOT NULL, revision_hash TEXT NOT NULL,
                PRIMARY KEY(tool, job_id, operation))""")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def grant(
        self,
        *,
        tool: str,
        job_id: str,
        operation: str,
        payload: dict,
        revision: dict,
        reviewer: str,
    ):
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO confirmations VALUES (?,?,?,?,?,?,?)",
                (
                    tool,
                    job_id,
                    operation,
                    payload_hash(payload),
                    payload_hash(revision),
                    time.time(),
                    reviewer,
                ),
            )

    def require(
        self, *, tool: str, job_id: str, operation: str, payload: dict, revision: dict
    ):
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_hash, revision_hash, confirmed_at FROM confirmations "
                "WHERE tool=? AND job_id=? AND operation=?",
                (tool, job_id, operation),
            ).fetchone()
        if (
            not row
            or row[0] != payload_hash(payload)
            or row[1] != payload_hash(revision)
            or time.time() - row[2] > 1800
        ):
            with self._connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO proposals VALUES (?,?,?,?,?)",
                    (
                        tool,
                        job_id,
                        operation,
                        json.dumps(payload),
                        payload_hash(revision),
                    ),
                )
            raise ToolError(
                "HUMAN_CONFIRMATION_REQUIRED",
                "The user must confirm these exact values in the task card first. "
                "Do not retry or claim approval on their behalf. If a confirmation was "
                "just provided, copy its exact operation and input without changes.",
            )

    def proposal(self, *, tool: str, job_id: str, operation: str, revision: dict):
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_json, revision_hash FROM proposals WHERE tool=? AND job_id=? AND operation=?",
                (tool, job_id, operation),
            ).fetchone()
        return json.loads(row[0]) if row and row[1] == payload_hash(revision) else None
