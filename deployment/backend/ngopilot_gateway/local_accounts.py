"""Invitation-only staff accounts for the loopback Agent, modelled on CareFlow Atlas.

There is no public registration, SMTP or SSO. An operator creates the first
administrator from the container; administrators then invite staff with
one-hour, single-use password links that they deliver through a trusted channel.
Passwords use Argon2id. Session and link tokens are stored only as SHA-256
digests. Every account owns a separate Agent tenant directory.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import secrets
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

SESSION_IDLE_SECONDS = 6 * 60 * 60
SESSION_ABSOLUTE_SECONDS = 12 * 60 * 60
GRANT_SECONDS = 60 * 60
MAX_SESSIONS = 10
ROLES = {"ADMIN", "MEMBER"}
TOKEN_PATTERN = re.compile(r"[\w-]{43}")
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
# Verifying an unknown email costs the same as a real account.
_UNASSIGNED_HASH = _hasher.hash(secrets.token_urlsafe(32))


class AccountError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def require(condition: object, status: int, message: str) -> None:
    if not condition:
        raise AccountError(status, message)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def email_value(value: object) -> str:
    require(isinstance(value, str) and len(value) <= 254, 400, "請輸入有效電郵。")
    email = str(value).strip().lower()
    require(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email), 400, "請輸入有效電郵。")
    return email


def name_value(value: object) -> str:
    require(isinstance(value, str) and 1 <= len(value.strip()) <= 80, 400, "姓名須為 1–80 個字元。")
    return str(value).strip()


def password_value(value: object) -> str:
    require(
        isinstance(value, str) and 15 <= len(value) <= 128,
        400,
        "密碼須為 15–128 個字元，可使用長句。",
    )
    return str(value)


def hash_password(password: str) -> str:
    return _hasher.hash(password_value(password))


def verify_password(encoded: str | None, password: object) -> bool:
    candidate = password[:128] if isinstance(password, str) else ""
    try:
        return _hasher.verify(encoded or _UNASSIGNED_HASH, candidate) and encoded is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def public_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "disabled": bool(row["disabled"]),
        "pending": row["password_hash"] is None,
        "createdAt": row["created_at"],
    }


@dataclass(frozen=True, slots=True)
class Session:
    hash: str
    id: str
    user_id: UUID
    expires_at: int


class LocalAccounts:
    def __init__(self, path: Path, *, now=time.time):
        self.now = lambda: int(now())
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        if str(path) != ":memory:":
            path.chmod(0o600)
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            self.db.close()
            raise RuntimeError("帳號庫版本高於目前程式，拒絕降級打開。")
        self.db.executescript(
            """
            PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('ADMIN','MEMBER')),
              disabled INTEGER NOT NULL DEFAULT 0, password_hash TEXT,
              version INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
              hash TEXT PRIMARY KEY, id TEXT UNIQUE NOT NULL,
              user_id TEXT NOT NULL REFERENCES users(id), created_at INTEGER NOT NULL,
              seen_at INTEGER NOT NULL, expires_at INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS grants (
              hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
              expires_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS rate_limits (
              key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (
              id INTEGER PRIMARY KEY, time INTEGER NOT NULL, actor TEXT,
              action TEXT NOT NULL, target TEXT);
            PRAGMA user_version=1;
            """
        )

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")

    def _one(self, sql: str, *args) -> sqlite3.Row | None:
        with self.lock:
            return self.db.execute(sql, args).fetchone()

    def _all(self, sql: str, *args) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def _audit(self, db, actor: str | None, action: str, target: str | None = None) -> None:
        db.execute(
            "INSERT INTO audit(time,actor,action,target) VALUES(?,?,?,?)",
            (self.now(), actor, action, target),
        )

    def user(self, user_id: str | UUID) -> sqlite3.Row | None:
        return self._one("SELECT * FROM users WHERE id=?", str(user_id))

    def user_count(self) -> int:
        return self._one("SELECT COUNT(*) AS n FROM users")["n"]

    def clean(self) -> None:
        now = self.now()
        with self.transaction() as db:
            db.execute(
                "DELETE FROM sessions WHERE expires_at<=? OR seen_at<=?",
                (now, now - SESSION_IDLE_SECONDS),
            )
            db.execute("DELETE FROM grants WHERE expires_at<=?", (now,))
            db.execute("DELETE FROM rate_limits WHERE expires_at<=?", (now,))

    def limit(self, key: str, maximum: int, window: int = 15 * 60) -> None:
        hashed, now = digest(key), self.now()
        with self.transaction() as db:
            db.execute(
                """INSERT INTO rate_limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET
                count=CASE WHEN expires_at<=? THEN 1 ELSE count+1 END,
                expires_at=CASE WHEN expires_at<=? THEN excluded.expires_at ELSE expires_at END""",
                (hashed, now + window, now, now),
            )
            count = db.execute("SELECT count FROM rate_limits WHERE key=?", (hashed,)).fetchone()
        require(count["count"] <= maximum, 429, "嘗試過於頻繁，請稍後重試。")

    def _grant(self, db, user_id: str, actor: str | None) -> str:
        token = secrets.token_urlsafe(32)
        db.execute("DELETE FROM grants WHERE user_id=?", (user_id,))
        db.execute(
            "INSERT INTO grants VALUES(?,?,?)", (digest(token), user_id, self.now() + GRANT_SECONDS)
        )
        self._audit(db, actor, "password_link_created", user_id)
        return token

    def create_user(
        self,
        email: object,
        name: object,
        role: object,
        actor: str | None = None,
        user_id: UUID | None = None,
    ) -> tuple[dict, str]:
        email, name = email_value(email), name_value(name)
        require(role in ROLES, 400, "無效角色。")
        with self.transaction() as db:
            exists = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            require(exists is None, 409, "該電郵已存在。")
            ident = str(user_id or uuid4())
            db.execute(
                "INSERT INTO users(id,email,name,role,created_at) VALUES(?,?,?,?,?)",
                (ident, email, name, role, self.now()),
            )
            self._audit(db, actor, "user_created", ident)
            token = self._grant(db, ident, actor)
        return public_user(self.user(ident)), token

    def bootstrap(self, email: object, name: object, user_id: UUID) -> str:
        """Create the first administrator; refuses once any account exists."""
        require(self.user_count() == 0, 409, "帳號庫已有使用者；需要恢復時使用 recover-admin。")
        return self.create_user(email, name, "ADMIN", user_id=user_id)[1]

    def recover_admin(self, email: object) -> str:
        email = email_value(email)
        with self.transaction() as db:
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            require(user is not None and user["role"] == "ADMIN", 404, "管理員不存在。")
            db.execute("UPDATE users SET disabled=0,version=version+1 WHERE id=?", (user["id"],))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            self._audit(db, None, "operator_recovery", user["id"])
            return self._grant(db, user["id"], None)

    def session(self, token: str | None, touch: bool = True) -> Session | None:
        if not token or not TOKEN_PATTERN.fullmatch(token):
            return None
        now = self.now()
        with self.lock:
            row = self.db.execute(
                """SELECT s.* FROM sessions s JOIN users u ON u.id=s.user_id
                WHERE s.hash=? AND u.disabled=0 AND s.expires_at>? AND s.seen_at>?""",
                (digest(token), now, now - SESSION_IDLE_SECONDS),
            ).fetchone()
            if row is None:
                return None
            if touch:
                self.db.execute("UPDATE sessions SET seen_at=? WHERE hash=?", (now, row["hash"]))
        return Session(row["hash"], row["id"], UUID(row["user_id"]), row["expires_at"])

    def active(self, session: Session) -> bool:
        now = self.now()
        return (
            self._one(
                """SELECT 1 FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.hash=?
                AND u.disabled=0 AND s.expires_at>? AND s.seen_at>?""",
                session.hash,
                now,
                now - SESSION_IDLE_SECONDS,
            )
            is not None
        )

    def _new_session(self, db, user_id: str) -> tuple[str, Session]:
        token, now = secrets.token_urlsafe(32), self.now()
        old = db.execute(
            "SELECT hash FROM sessions WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
        for row in old[MAX_SESSIONS - 1 :]:
            db.execute("DELETE FROM sessions WHERE hash=?", (row["hash"],))
        ident, expires = str(uuid4()), now + SESSION_ABSOLUTE_SECONDS
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?)",
            (digest(token), ident, user_id, now, now, expires),
        )
        return token, Session(digest(token), ident, UUID(user_id), expires)

    def login(self, email: object, password: object, source: str) -> tuple[str, Session]:
        self.clean()
        self.limit(f"login-source:{source}", 60)
        email = email_value(email)
        self.limit(f"login-email:{email}", 10)
        user = self._one("SELECT * FROM users WHERE email=?", email)
        valid = verify_password(user["password_hash"] if user else None, password)
        with self.transaction() as db:
            current = (
                user and db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            )
            if (
                not valid
                or not current
                or current["disabled"]
                or not current["password_hash"]
                or current["version"] != user["version"]
            ):
                self._audit(db, None, "login_failed")
                failed = True
            else:
                failed = False
                self._audit(db, user["id"], "login")
                result = self._new_session(db, user["id"])
        # Record the failure even though the request is rejected.
        require(not failed, 401, "電郵或密碼不正確，或帳號不可用。")
        return result

    def redeem(self, token: object, password: object, source: str) -> None:
        self.clean()
        self.limit(f"redeem:{source}", 20)
        require(
            isinstance(token, str) and TOKEN_PATTERN.fullmatch(token), 400, "連結無效或已過期。"
        )
        hashed = hash_password(password)  # type: ignore[arg-type]
        with self.transaction() as db:
            grant = db.execute(
                "SELECT * FROM grants WHERE hash=? AND expires_at>?", (digest(token), self.now())
            ).fetchone()
            user = (
                grant
                and db.execute("SELECT * FROM users WHERE id=?", (grant["user_id"],)).fetchone()
            )
            require(user and not user["disabled"], 400, "連結無效或已過期。")
            db.execute(
                "UPDATE users SET password_hash=?,version=version+1 WHERE id=?",
                (hashed, user["id"]),
            )
            db.execute("DELETE FROM grants WHERE user_id=?", (user["id"],))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            self._audit(db, user["id"], "password_set")

    def change_password(self, session: Session, old: object, password: object) -> None:
        require(self.active(session), 401, "登入已過期，請重新登入。")
        user = self.user(session.user_id)
        self.limit(f"password:{user['id']}", 10)
        require(verify_password(user["password_hash"], old), 400, "目前密碼不正確。")
        hashed = hash_password(password)  # type: ignore[arg-type]
        with self.transaction() as db:
            current = db.execute("SELECT version FROM users WHERE id=?", (user["id"],)).fetchone()
            require(current["version"] == user["version"], 409, "帳號已發生變化，請重新登入。")
            db.execute(
                "UPDATE users SET password_hash=?,version=version+1 WHERE id=?",
                (hashed, user["id"]),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            db.execute("DELETE FROM grants WHERE user_id=?", (user["id"],))
            self._audit(db, user["id"], "password_changed")

    def logout(self, session: Session) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM sessions WHERE hash=?", (session.hash,))
            self._audit(db, str(session.user_id), "logout")

    def sessions(self, session: Session) -> list[dict]:
        now = self.now()
        rows = self._all(
            """SELECT id,created_at,seen_at,expires_at FROM sessions WHERE user_id=?
            AND expires_at>? AND seen_at>? ORDER BY created_at DESC""",
            str(session.user_id),
            now,
            now - SESSION_IDLE_SECONDS,
        )
        return [{**dict(row), "current": row["id"] == session.id} for row in rows]

    def revoke_others(self, session: Session) -> None:
        with self.transaction() as db:
            db.execute(
                "DELETE FROM sessions WHERE user_id=? AND id<>?",
                (str(session.user_id), session.id),
            )
            self._audit(db, str(session.user_id), "other_sessions_revoked")

    def require_admin(self, session: Session) -> sqlite3.Row:
        require(self.active(session), 401, "登入已過期，請重新登入。")
        user = self.user(session.user_id)
        require(user["role"] == "ADMIN", 403, "需要管理員權限。")
        return user

    def users(self) -> list[dict]:
        return [public_user(row) for row in self._all("SELECT * FROM users ORDER BY created_at,id")]

    def audit_events(self) -> list[dict]:
        rows = self._all(
            """SELECT a.id,a.time,a.action,u.email AS actor_email,t.email AS target_email
            FROM audit a LEFT JOIN users u ON u.id=a.actor LEFT JOIN users t ON t.id=a.target
            ORDER BY a.id DESC LIMIT 100"""
        )
        return [dict(row) for row in rows]

    def update_user(self, actor: Session, user_id: str, changes: dict) -> dict:
        role, disabled = changes.get("role"), changes.get("disabled")
        require(role in ROLES and isinstance(disabled, bool), 400, "無效帳號設定。")
        name = name_value(changes.get("name"))
        with self.transaction() as db:
            self.require_admin(actor)
            user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            require(user is not None, 404, "帳號不存在。")
            demoting = role != "ADMIN" or disabled
            if (
                user["role"] == "ADMIN"
                and not user["disabled"]
                and user["password_hash"]
                and demoting
            ):
                admins = db.execute(
                    """SELECT COUNT(*) AS n FROM users WHERE role='ADMIN' AND disabled=0
                    AND password_hash IS NOT NULL"""
                ).fetchone()["n"]
                require(admins > 1, 409, "不能停用或降級最後一位已啟用管理員。")
            db.execute(
                "UPDATE users SET role=?,disabled=?,name=?,version=version+1 WHERE id=?",
                (role, int(disabled), name, user_id),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            if disabled:
                db.execute("DELETE FROM grants WHERE user_id=?", (user_id,))
            self._audit(db, str(actor.user_id), "user_updated", user_id)
        return public_user(self.user(user_id))

    def reset_link(self, actor: Session, user_id: str) -> str:
        with self.transaction() as db:
            admin = self.require_admin(actor)
            user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            require(user and not user["disabled"], 400, "帳號不存在或已停用。")
            return self._grant(db, user_id, admin["id"])


def main() -> None:
    """Operator CLI. Run inside the Agent container as the service user."""
    import os

    from .local import LOCAL_OWNER

    parser = argparse.ArgumentParser(prog="python -m ngopilot_gateway.local_accounts")
    commands = parser.add_subparsers(dest="command", required=True)
    first = commands.add_parser("bootstrap", help="create the first administrator")
    first.add_argument("email")
    first.add_argument("name", nargs="+")
    recover = commands.add_parser("recover-admin", help="issue a new link for an administrator")
    recover.add_argument("email")
    args = parser.parse_args()
    os.umask(0o077)
    data_root = Path(os.environ.get("DATA_ROOT", "/data"))
    origin = os.environ.get("PUBLIC_API_URL", "http://127.0.0.1:8310").rstrip("/")
    accounts = LocalAccounts(data_root / "accounts.sqlite3")
    try:
        if args.command == "bootstrap":
            # The first administrator inherits the pre-account local workspace.
            token = accounts.bootstrap(args.email, " ".join(args.name), LOCAL_OWNER)
        else:
            token = accounts.recover_admin(args.email)
    except AccountError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
    finally:
        accounts.close()
    print(f"一次性設定密碼連結（1 小時有效，請私下交付）：\n{origin}/#set-password={token}")


if __name__ == "__main__":
    main()
