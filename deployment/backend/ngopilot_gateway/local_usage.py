"""Weekly per-account usage of the loopback Agent, with a generous member cap.

A message is one ``session/prompt`` sent by the account. An image is one image
or PDF attachment (distinct upload placeholder) sent in a prompt. Weeks start on
Monday 00:00 Hong Kong time. Administrators are counted but never capped. The
message that continues a task after a task-card confirmation is never blocked
and does not count, so a confirmed task can always finish.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from .local_accounts import LocalAccounts, Session
from .storage import PLACEHOLDER_PATTERN, parse_placeholder

HONG_KONG = timezone(timedelta(hours=8))
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".pdf")
REPORT_WEEKS = 4


def week_start(at: datetime) -> datetime:
    local = at.astimezone(HONG_KONG)
    monday = local - timedelta(days=local.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def prompt_images(message: dict[str, Any]) -> int:
    """Count distinct image/PDF attachments referenced by a prompt."""
    found = set()
    for placeholder in PLACEHOLDER_PATTERN.findall(json.dumps(message.get("params", {}))):
        try:
            _, filename = parse_placeholder(placeholder)
        except ValueError:
            continue
        if filename.lower().endswith(IMAGE_SUFFIXES):
            found.add(placeholder)
    return len(found)


class UsageLimitReached(Exception):
    pass


class LocalUsage:
    def __init__(self, accounts: LocalAccounts, *, message_limit: int, image_limit: int):
        self.accounts = accounts
        # Zero disables a cap.
        self.message_limit = message_limit
        self.image_limit = image_limit
        with accounts.transaction() as db:
            # Additive tables: older builds ignore them, so the schema version is unchanged.
            db.execute(
                """CREATE TABLE IF NOT EXISTS usage (
                user_id TEXT NOT NULL REFERENCES users(id), week TEXT NOT NULL,
                messages INTEGER NOT NULL DEFAULT 0, images INTEGER NOT NULL DEFAULT 0,
                continuations INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id, week))"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS continuation_credits (
                user_id TEXT PRIMARY KEY REFERENCES users(id), count INTEGER NOT NULL)"""
            )

    def _week(self) -> datetime:
        return week_start(datetime.fromtimestamp(self.accounts.now(), timezone.utc))

    def limits(self) -> dict:
        reset = self._week() + timedelta(days=7)
        return {
            "messages": self.message_limit or None,
            "images": self.image_limit or None,
            "resetsAt": int(reset.timestamp()),
        }

    def grant_continuation(self, user_id: UUID) -> None:
        with self.accounts.transaction() as db:
            db.execute(
                """INSERT INTO continuation_credits VALUES(?,1) ON CONFLICT(user_id)
                DO UPDATE SET count=MIN(count+1, 5)""",
                (str(user_id),),
            )

    def record_prompt(self, session: Session, message: dict[str, Any]) -> None:
        """Count one prompt, or raise UsageLimitReached for a capped member."""
        user_id, week = str(session.user_id), self._week().date().isoformat()
        images = prompt_images(message)
        with self.accounts.transaction() as db:
            role = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()["role"]
            db.execute(
                "INSERT INTO usage(user_id, week) VALUES(?,?) ON CONFLICT DO NOTHING",
                (user_id, week),
            )
            credit = db.execute(
                "SELECT count FROM continuation_credits WHERE user_id=?", (user_id,)
            ).fetchone()
            if credit and credit["count"] > 0 and images == 0:
                db.execute(
                    "UPDATE continuation_credits SET count=count-1 WHERE user_id=?", (user_id,)
                )
                db.execute(
                    "UPDATE usage SET continuations=continuations+1 WHERE user_id=? AND week=?",
                    (user_id, week),
                )
                return
            used = db.execute(
                "SELECT messages, images FROM usage WHERE user_id=? AND week=?", (user_id, week)
            ).fetchone()
            if role != "ADMIN":
                monday = self._week() + timedelta(days=7)
                reset = f"{monday.month} 月 {monday.day} 日（星期一）"
                if self.message_limit and used["messages"] + 1 > self.message_limit:
                    raise UsageLimitReached(
                        f"本週對話次數已用完（上限 {self.message_limit} 次），{reset}重置。"
                        "已開始的任務仍可在任務卡核對後完成；如需增加額度，請聯絡管理員。"
                    )
                if self.image_limit and used["images"] + images > self.image_limit:
                    left = max(0, self.image_limit - used["images"])
                    raise UsageLimitReached(
                        f"本週圖片／PDF 處理次數不足（上限 {self.image_limit}，"
                        f"尚餘 {left}，這次附上 {images} 個），{reset}重置。"
                        "如需增加額度，請聯絡管理員。"
                    )
            db.execute(
                "UPDATE usage SET messages=messages+1, images=images+? WHERE user_id=? AND week=?",
                (images, user_id, week),
            )

    def own(self, session: Session) -> dict:
        week = self._week().date().isoformat()
        row = self.accounts._one(
            "SELECT messages, images FROM usage WHERE user_id=? AND week=?",
            str(session.user_id),
            week,
        )
        user = self.accounts.user(session.user_id)
        limited = user["role"] != "ADMIN"
        return {
            "week": week,
            "messages": row["messages"] if row else 0,
            "images": row["images"] if row else 0,
            "limits": self.limits()
            if limited
            else {**self.limits(), "messages": None, "images": None},
        }

    def report(self) -> dict:
        start = self._week()
        weeks = [(start - timedelta(days=7 * n)).date().isoformat() for n in range(REPORT_WEEKS)]
        rows = self.accounts._all(
            f"""SELECT user_id, week, messages, images, continuations FROM usage
            WHERE week IN ({",".join("?" * len(weeks))})""",
            *weeks,
        )
        usage: dict[str, dict] = {}
        for row in rows:
            usage.setdefault(row["user_id"], {})[row["week"]] = {
                "messages": row["messages"],
                "images": row["images"],
                "continuations": row["continuations"],
            }
        return {"weeks": weeks, "limits": self.limits(), "usage": usage}
