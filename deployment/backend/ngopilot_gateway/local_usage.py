"""Weekly per-account usage of the loopback Agent, with a generous member cap.

A message is one ``session/prompt`` sent by the account. An image is one image
or PDF attachment (distinct upload placeholder) sent in a prompt. Weeks start on
Monday 00:00 Hong Kong time. Administrators are counted but never capped; they
may override the default caps for an individual member. The
message that continues a task after a task-card confirmation is never blocked
and does not count, so a confirmed task can always finish.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from .local_accounts import LocalAccounts, Session, require
from .storage import PLACEHOLDER_PATTERN, parse_placeholder

HONG_KONG = timezone(timedelta(hours=8))
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".pdf")
REPORT_WEEKS = 4
MAX_LIMIT = 100_000


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
            # NULL keeps the default; 0 removes that member's cap.
            db.execute(
                """CREATE TABLE IF NOT EXISTS usage_limits (
                user_id TEXT PRIMARY KEY REFERENCES users(id), messages INTEGER, images INTEGER)"""
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

    def _effective(self, db, user_id: str) -> tuple[int, int]:
        """The member's caps after any override; zero means uncapped."""
        row = db.execute(
            "SELECT messages, images FROM usage_limits WHERE user_id=?", (user_id,)
        ).fetchone()
        messages = row["messages"] if row and row["messages"] is not None else None
        images = row["images"] if row and row["images"] is not None else None
        return (
            self.message_limit if messages is None else messages,
            self.image_limit if images is None else images,
        )

    def set_limits(self, actor: Session, user_id: str, messages: object, images: object) -> dict:
        for value in (messages, images):
            require(
                value is None
                or (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and 0 <= value <= MAX_LIMIT
                ),
                400,
                f"上限須為 0–{MAX_LIMIT} 的整數；留空使用預設，0 表示不限。",
            )
        with self.accounts.transaction() as db:
            admin = self.accounts.require_admin(actor)
            user = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
            require(user is not None, 404, "帳號不存在。")
            if messages is None and images is None:
                db.execute("DELETE FROM usage_limits WHERE user_id=?", (user_id,))
            else:
                db.execute(
                    """INSERT INTO usage_limits VALUES(?,?,?) ON CONFLICT(user_id)
                    DO UPDATE SET messages=excluded.messages, images=excluded.images""",
                    (user_id, messages, images),
                )
            self.accounts._audit(db, admin["id"], "usage_limits_updated", user_id)
        return {"messages": messages, "images": images}

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
                message_limit, image_limit = self._effective(db, user_id)
                monday = self._week() + timedelta(days=7)
                reset = f"{monday.month} 月 {monday.day} 日（星期一）"
                if message_limit and used["messages"] + 1 > message_limit:
                    raise UsageLimitReached(
                        f"本週對話次數已用完（上限 {message_limit} 次），{reset}重置。"
                        "已開始的任務仍可在任務卡核對後完成；如需增加額度，請聯絡管理員。"
                    )
                if image_limit and used["images"] + images > image_limit:
                    left = max(0, image_limit - used["images"])
                    raise UsageLimitReached(
                        f"本週圖片／PDF 處理次數不足（上限 {image_limit}，"
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
        limits = self.limits()
        if user["role"] == "ADMIN":
            limits.update(messages=None, images=None)
        else:
            with self.accounts.lock:
                messages, images = self._effective(self.accounts.db, user["id"])
            limits.update(messages=messages or None, images=images or None)
        return {
            "week": week,
            "messages": row["messages"] if row else 0,
            "images": row["images"] if row else 0,
            "limits": limits,
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
        overrides = {
            row["user_id"]: {"messages": row["messages"], "images": row["images"]}
            for row in self.accounts._all("SELECT * FROM usage_limits")
        }
        return {"weeks": weeks, "limits": self.limits(), "usage": usage, "overrides": overrides}
