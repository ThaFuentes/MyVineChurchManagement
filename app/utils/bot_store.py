"""Database work for Bot Access. Rules live in bot_policy."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from app.models.db import get_db
from app.utils import bot_policy as policy

READ_LIMIT = 40


def _cur():
    return get_db().cursor()


def _cell(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return None
    return value


def _clean(row: dict | None) -> dict:
    return {key: _cell(val) for key, val in (row or {}).items()}


def _key_view(row: dict) -> dict:
    out = _clean(row)
    for secret in ("key_hash", "twofa_hash", "session_hash", "prev_key_hash"):
        out.pop(secret, None)
    out["active"] = bool(row.get("active"))
    out["controls"] = policy.normalize_controls(row.get("controls_json"))
    return out


def list_members() -> list[dict]:
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT id, username, first_name, last_name, role
            FROM users
            ORDER BY first_name ASC, last_name ASC, username ASC
            LIMIT 500
            """
        )
        rows = []
        for row in cur.fetchall() or []:
            item = _clean(row)
            item["label"] = policy.person_label(item)
            rows.append(item)
        return rows
    except Exception as exc:
        print(f"bot list_members: {exc}")
        return []


def ensure_admin_grants() -> None:
    """Owner allow-list. Empty means no admin may use a bot."""
    try:
        cur = _cur()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_admin_grants (
                user_id     INT UNSIGNED NOT NULL PRIMARY KEY,
                granted_by  INT UNSIGNED NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    except Exception as exc:
        print(f"bot admin grants: {exc}")


def admin_grant_ids() -> set[int]:
    try:
        ensure_admin_grants()
        cur = _cur()
        cur.execute("SELECT user_id FROM bot_admin_grants")
        return {int(row["user_id"]) for row in (cur.fetchall() or []) if row.get("user_id")}
    except Exception as exc:
        print(f"bot admin grant ids: {exc}")
        return set()


def save_admin_grants(user_ids: list[int], granted_by: int | None) -> tuple[bool, str]:
    """Replace the allow-list with these admin ids. Anyone left off cannot use a bot."""
    try:
        ensure_admin_grants()
        cur = _cur()
        cur.execute("SELECT id FROM users WHERE role=%s", ("Admin",))
        admins = {int(row["id"]) for row in (cur.fetchall() or [])}
        chosen = []
        for uid in user_ids:
            if int(uid) in admins and int(uid) not in chosen:
                chosen.append(int(uid))
        cur.execute("DELETE FROM bot_admin_grants")
        for uid in chosen:
            cur.execute(
                "INSERT INTO bot_admin_grants (user_id, granted_by) VALUES (%s, %s)",
                (uid, int(granted_by) if granted_by else None),
            )
        return True, ""
    except Exception as exc:
        print(f"bot save admin grants: {exc}")
        return False, "Could not save which admins may use a bot."


def account_facts(user_id: int) -> dict:
    """Role of the account the owner saved, and whether an admin is allowed."""
    out = {"user_id": int(user_id), "role": None, "admin_granted": False}
    try:
        cur = _cur()
        cur.execute("SELECT role FROM users WHERE id=%s", (int(user_id),))
        row = cur.fetchone()
        if not row:
            return out
        role = row.get("role") or ""
        out["role"] = role
        if role == "Owner":
            out["admin_granted"] = True
        elif role == "Admin":
            out["admin_granted"] = int(user_id) in admin_grant_ids()
    except Exception as exc:
        print(f"bot account facts: {exc}")
    return out


def ensure_login_columns() -> None:
    """Add the two-inbox columns on a database created before this sign-in."""
    columns = (
        ("email", "VARCHAR(160) NULL"),
        ("twofa_email", "VARCHAR(160) NULL"),
        ("twofa_hash", "CHAR(64) NULL"),
        ("twofa_expires", "DATETIME NULL"),
        ("twofa_attempts", "INT NOT NULL DEFAULT 0"),
        ("session_hash", "CHAR(64) NULL"),
        ("session_expires", "DATETIME NULL"),
        ("prev_key_hash", "CHAR(64) NULL"),
        ("prev_key_expires", "DATETIME NULL"),
    )
    try:
        cur = _cur()
        for column, definition in columns:
            cur.execute(
                """
                SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'bot_access_keys' AND COLUMN_NAME = %s
                """,
                (column,),
            )
            if cur.fetchone():
                continue
            cur.execute(f"ALTER TABLE bot_access_keys ADD COLUMN {column} {definition}")
        ensure_sessions()
        ensure_twofa_codes()
    except Exception as exc:
        print(f"bot login columns: {type(exc).__name__}")


def ensure_sessions() -> None:
    """Many sessions per bot. A still-live single slot is copied across once."""
    try:
        cur = _cur()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_sessions (
                id            INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
                key_id        INT UNSIGNED NOT NULL,
                session_hash  CHAR(64) NOT NULL,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at    DATETIME NOT NULL,
                last_used_at  DATETIME NULL,
                client_label  VARCHAR(80) NULL,
                UNIQUE KEY uq_bot_session_hash (session_hash),
                KEY idx_bot_session_key (key_id, id),
                FOREIGN KEY (key_id) REFERENCES bot_access_keys(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            SELECT id, session_hash, session_expires
            FROM bot_access_keys
            WHERE session_hash IS NOT NULL AND session_expires > NOW()
            """
        )
        legacy = list(cur.fetchall() or [])
        cur.execute("SELECT session_hash FROM bot_sessions")
        have = {row.get("session_hash") for row in (cur.fetchall() or []) if row.get("session_hash")}
        for row in legacy:
            digest = row.get("session_hash")
            if not digest or digest in have:
                continue
            cur.execute(
                """
                INSERT INTO bot_sessions
                    (key_id, session_hash, expires_at, last_used_at, client_label)
                VALUES (%s, %s, %s, NOW(), 'legacy')
                """,
                (int(row["id"]), digest, row.get("session_expires")),
            )
            have.add(digest)
        cur.execute(
            """
            SELECT id, session_hash FROM bot_access_keys
            WHERE session_hash IS NOT NULL
            """
        )
        for row in cur.fetchall() or []:
            if row.get("session_hash") not in have:
                continue
            cur.execute(
                """
                UPDATE bot_access_keys
                SET session_hash=NULL, session_expires=NULL
                WHERE id=%s
                """,
                (int(row["id"]),),
            )
    except Exception as exc:
        print(f"bot sessions: {type(exc).__name__}")


def set_inboxes(key_id: int, key_email: str, twofa_email: str) -> tuple[bool, str]:
    problem = policy.inbox_problem(key_email, twofa_email)
    if problem:
        return False, problem
    try:
        ensure_login_columns()
        cur = _cur()
        cur.execute(
            "UPDATE bot_access_keys SET email=%s, twofa_email=%s WHERE id=%s",
            (policy.normalize_email(key_email), policy.normalize_email(twofa_email), int(key_id)),
        )
        return True, ""
    except Exception as exc:
        print(f"bot set_inboxes: {exc}")
        return False, "Those inboxes could not be saved."


def insert_bot(name: str, key_email: str, twofa_email: str, created_by: int | None,
               raw: str, digest: str, prefix: str) -> tuple[bool, str]:
    try:
        ensure_login_columns()
        cur = _cur()
        cur.execute(
            """
            INSERT INTO bot_access_keys
                (name, key_hash, key_prefix, active, controls_json, created_by, email, twofa_email)
            VALUES (%s, %s, %s, 1, %s, %s, %s, %s)
            """,
            (
                name,
                digest,
                prefix,
                json.dumps(policy.default_controls()),
                created_by,
                policy.normalize_email(key_email),
                policy.normalize_email(twofa_email),
            ),
        )
        return True, ""
    except Exception as exc:
        print(f"bot insert_bot: {exc}")
        return False, "That bot could not be saved."


def replace_api_key(key_id: int, digest: str, prefix: str) -> tuple[bool, str]:
    """Point the bot at a new key. The previous key keeps working for 15 minutes.

    Open sessions and a pending 2FA key stay valid. A second rotation drops
    the older previous key and keeps only the newest one in that window.
    """
    try:
        ensure_login_columns()
        cur = _cur()
        cur.execute(
            """
            UPDATE bot_access_keys
            SET prev_key_hash=key_hash,
                prev_key_expires=DATE_ADD(NOW(), INTERVAL %s SECOND),
                key_hash=%s, key_prefix=%s
            WHERE id=%s
            """,
            (int(policy.PREV_KEY_GRACE_SECONDS), digest, prefix, int(key_id)),
        )
        if not cur.rowcount:
            return False, "That bot was not found."
        return True, ""
    except Exception as exc:
        print(f"bot replace_api_key: {type(exc).__name__}")
        return False, "That API key could not be saved."


def ensure_twofa_codes() -> None:
    """Newest unused 2FA codes. A later sign-in does not erase the earlier ones."""
    try:
        cur = _cur()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_twofa_codes (
                id         INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
                key_id     INT UNSIGNED NOT NULL,
                code_hash  CHAR(64) NOT NULL,
                expires_at DATETIME NOT NULL,
                used_at    DATETIME NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                KEY idx_bot_twofa_key (key_id, id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    except Exception as exc:
        print(f"bot twofa codes: {type(exc).__name__}")


def _trim_twofa(key_id: int) -> None:
    """Keep the newest three unused codes that have not expired."""
    cur = _cur()
    cur.execute(
        """
        SELECT id FROM bot_twofa_codes
        WHERE key_id=%s AND used_at IS NULL AND expires_at > NOW()
        ORDER BY id DESC
        """,
        (int(key_id),),
    )
    ids = [int(row["id"]) for row in (cur.fetchall() or []) if row.get("id")]
    for old in ids[3:]:
        cur.execute("UPDATE bot_twofa_codes SET used_at=NOW() WHERE id=%s", (int(old),))


def store_twofa(key_id: int, digest: str) -> bool:
    """Store a 2FA key beside any that are still waiting. This does not close a session."""
    try:
        ensure_login_columns()
        ensure_twofa_codes()
        cur = _cur()
        cur.execute(
            """
            INSERT INTO bot_twofa_codes (key_id, code_hash, expires_at)
            VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL %s SECOND))
            """,
            (int(key_id), digest, int(policy.TWOFA_TTL_SECONDS)),
        )
        _trim_twofa(int(key_id))
        cur.execute(
            """
            UPDATE bot_access_keys
            SET twofa_hash=%s,
                twofa_expires=DATE_ADD(NOW(), INTERVAL %s SECOND),
                twofa_attempts=0
            WHERE id=%s
            """,
            (digest, int(policy.TWOFA_TTL_SECONDS), int(key_id)),
        )
        return True
    except Exception as exc:
        print(f"bot store_twofa: {type(exc).__name__}")
        return False


def mark_twofa_used(code_id: int | None) -> None:
    if not code_id:
        return
    try:
        cur = _cur()
        cur.execute("UPDATE bot_twofa_codes SET used_at=NOW() WHERE id=%s", (int(code_id),))
    except Exception as exc:
        print(f"bot mark twofa: {type(exc).__name__}")


def pending_twofa_count(key_id: int) -> int:
    try:
        ensure_twofa_codes()
        cur = _cur()
        cur.execute(
            """
            SELECT COUNT(*) AS n FROM bot_twofa_codes
            WHERE key_id=%s AND used_at IS NULL AND expires_at > NOW()
            """,
            (int(key_id),),
        )
        row = cur.fetchone() or {}
        return int(row.get("n") or 0)
    except Exception as exc:
        print(f"bot pending twofa: {type(exc).__name__}")
        return 0


def open_session(key_id: int, digest: str, client_label: str = "") -> bool:
    """Open one more session. Other sessions for this bot stay open."""
    try:
        ensure_login_columns()
        cur = _cur()
        label = (client_label or "").strip()[:80] or None
        cur.execute(
            """
            INSERT INTO bot_sessions (key_id, session_hash, expires_at, last_used_at, client_label)
            VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL %s SECOND), NOW(), %s)
            """,
            (int(key_id), digest, int(policy.SESSION_TTL_SECONDS), label),
        )
        cur.execute(
            "SELECT id FROM bot_sessions WHERE key_id=%s ORDER BY id DESC",
            (int(key_id),),
        )
        ids = [int(row["id"]) for row in (cur.fetchall() or []) if row.get("id")]
        for old in ids[int(policy.MAX_OPEN_SESSIONS):]:
            cur.execute("DELETE FROM bot_sessions WHERE id=%s", (old,))
        cur.execute(
            """
            UPDATE bot_access_keys
            SET twofa_hash=NULL, twofa_expires=NULL, twofa_attempts=0
            WHERE id=%s
            """,
            (int(key_id),),
        )
        return True
    except Exception as exc:
        print(f"bot open_session: {type(exc).__name__}")
        return False


def note_bad_twofa(key_id: int) -> None:
    try:
        cur = _cur()
        cur.execute(
            """
            UPDATE bot_access_keys
            SET twofa_attempts=twofa_attempts+1,
                twofa_hash=IF(twofa_attempts+1 >= 8, NULL, twofa_hash),
                twofa_expires=IF(twofa_attempts+1 >= 8, NULL, twofa_expires)
            WHERE id=%s
            """,
            (int(key_id),),
        )
    except Exception as exc:
        print(f"bot note_bad_twofa: {exc}")


def clear_twofa(key_id: int, digest: str | None = None) -> None:
    """Drop a 2FA key that was stored but never emailed. Other waiting codes stay."""
    try:
        cur = _cur()
        if digest:
            cur.execute(
                """
                UPDATE bot_twofa_codes
                SET used_at=NOW()
                WHERE key_id=%s AND code_hash=%s AND used_at IS NULL
                """,
                (int(key_id), digest),
            )
            cur.execute(
                """
                SELECT code_hash,
                       TIMESTAMPDIFF(SECOND, NOW(), expires_at) AS seconds_left
                FROM bot_twofa_codes
                WHERE key_id=%s AND used_at IS NULL AND expires_at > NOW()
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(key_id),),
            )
            left = cur.fetchone()
            if left and left.get("code_hash"):
                seconds = int(left.get("seconds_left") or policy.TWOFA_TTL_SECONDS)
                cur.execute(
                    """
                    UPDATE bot_access_keys
                    SET twofa_hash=%s,
                        twofa_expires=DATE_ADD(NOW(), INTERVAL %s SECOND),
                        twofa_attempts=0
                    WHERE id=%s
                    """,
                    (left["code_hash"], max(seconds, 1), int(key_id)),
                )
                return
        cur.execute(
            """
            UPDATE bot_access_keys
            SET twofa_hash=NULL, twofa_expires=NULL, twofa_attempts=0
            WHERE id=%s
            """,
            (int(key_id),),
        )
    except Exception as exc:
        print(f"bot clear_twofa: {exc}")


def _flag(value) -> bool:
    if value in (None, False, 0, "0"):
        return False
    return bool(value)


def _session_kind(digest: str) -> str:
    cur = _cur()
    cur.execute(
        """
        SELECT (s.expires_at > NOW()) AS live, k.active
        FROM bot_sessions s
        JOIN bot_access_keys k ON k.id = s.key_id
        WHERE s.session_hash=%s
        LIMIT 1
        """,
        (digest,),
    )
    row = cur.fetchone()
    if not row:
        cur.execute(
            """
            SELECT (session_expires > NOW()) AS live, active
            FROM bot_access_keys
            WHERE session_hash=%s
            LIMIT 1
            """,
            (digest,),
        )
        row = cur.fetchone()
    if not row:
        return "unknown"
    if not _flag(row.get("live")):
        return "expired_session"
    if not _flag(row.get("active")):
        return "key_off"
    return "live_session"


def _api_key_kind(digest: str) -> str:
    cur = _cur()
    cur.execute(
        """
        SELECT active,
               (key_hash=%s) AS current_match,
               (prev_key_hash=%s) AS prev_match,
               (prev_key_expires > NOW()) AS prev_live
        FROM bot_access_keys
        WHERE key_hash=%s OR prev_key_hash=%s
        ORDER BY (key_hash=%s) DESC
        LIMIT 1
        """,
        (digest, digest, digest, digest, digest),
    )
    row = cur.fetchone()
    if not row:
        return "unknown"
    if _flag(row.get("current_match")):
        return "live_key" if _flag(row.get("active")) else "key_off"
    if _flag(row.get("prev_match")) and _flag(row.get("prev_live")):
        return "grace_key" if _flag(row.get("active")) else "key_off"
    if _flag(row.get("prev_match")):
        return "expired_prev"
    return "unknown"


def bearer_kind(raw: str) -> str:
    """What this bearer is, including expired credentials this church issued."""
    raw = (raw or "").strip()
    if not raw or len(raw) > 200:
        return "unknown"
    digest = policy.hash_key(raw)
    if not digest:
        return "unknown"
    try:
        ensure_login_columns()
        if raw.startswith("mvos_s_"):
            return _session_kind(digest)
        return _api_key_kind(digest)
    except Exception as exc:
        print(f"bot bearer_kind: {type(exc).__name__}")
        return "unknown"


def find_session(raw: str) -> dict | None:
    digest = policy.hash_key(raw or "")
    if not raw or not digest or not str(raw).startswith("mvos_s_"):
        return None
    try:
        ensure_login_columns()
        cur = _cur()
        cur.execute(
            """
            SELECT k.id, k.name, k.key_hash, k.key_prefix, k.active, k.controls_json,
                   k.created_by, k.email, k.twofa_email, k.created_at, k.updated_at,
                   s.id AS session_row_id
            FROM bot_sessions s
            JOIN bot_access_keys k ON k.id = s.key_id
            WHERE s.session_hash=%s AND s.expires_at > NOW()
            LIMIT 1
            """,
            (digest,),
        )
        row = cur.fetchone()
        session_row_id = row.get("session_row_id") if row else None
        if not row:
            cur.execute(
                """
                SELECT id, name, key_hash, key_prefix, active, controls_json, created_by,
                       email, twofa_email, created_at, updated_at
                FROM bot_access_keys
                WHERE session_hash=%s AND session_expires > NOW()
                LIMIT 1
                """,
                (digest,),
            )
            row = cur.fetchone()
        if not row:
            return None
        if session_row_id:
            try:
                cur.execute(
                    "UPDATE bot_sessions SET last_used_at=NOW() WHERE id=%s",
                    (int(session_row_id),),
                )
            except Exception as exc:
                print(f"bot session touch: {type(exc).__name__}")
        view = _key_view(row)
        view["voices"] = voices_for(int(view["id"]))
        return view
    except Exception as exc:
        print(f"bot find_session: {type(exc).__name__}")
        return None


def _legacy_twofa(key_id: int, digest: str) -> str:
    cur = _cur()
    cur.execute(
        """
        SELECT twofa_hash, twofa_expires > NOW() AS live
        FROM bot_access_keys WHERE id=%s
        """,
        (int(key_id),),
    )
    current = cur.fetchone() or {}
    if not current.get("twofa_hash"):
        return "missing"
    if current.get("twofa_hash") != digest:
        return "bad"
    if not current.get("live"):
        return "expired"
    return "ok"


def twofa_matches(row: dict, raw: str) -> str:
    """ok, missing, expired, or bad. Any of the newest unused codes can match."""
    digest = policy.hash_key(raw or "")
    if not row or not row.get("id") or not digest or not str(raw or "").startswith("mvos_2fa_"):
        return "missing" if not (raw or "").strip() else "bad"
    key_id = int(row["id"])
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT id, code_hash, (expires_at > NOW()) AS live
            FROM bot_twofa_codes
            WHERE key_id=%s AND used_at IS NULL
            ORDER BY id DESC
            LIMIT 3
            """,
            (key_id,),
        )
        codes = list(cur.fetchall() or [])
    except Exception as exc:
        print(f"bot twofa codes read: {type(exc).__name__}")
        codes = []
    saw = False
    for code in codes:
        if code.get("code_hash") != digest:
            continue
        saw = True
        if code.get("live"):
            row["_twofa_id"] = int(code["id"])
            return "ok"
        return "expired"
    try:
        legacy = _legacy_twofa(key_id, digest)
    except Exception as exc:
        print(f"bot twofa_matches: {exc}")
        return "bad"
    if legacy == "ok":
        return "ok"
    if saw:
        return "expired"
    if codes and legacy in ("bad", "missing"):
        return "bad"
    return legacy


def list_usage(limit: int = 80) -> list[dict]:
    try:
        cap = max(1, min(int(limit or 80), 200))
        cur = _cur()
        cur.execute(
            """
            SELECT l.id, l.key_id, k.name AS bot_name, k.key_prefix, l.action, l.target_type,
                   l.target_id, l.ok, l.detail, l.snapshot_json, l.reversed_at, l.reversed_by,
                   l.created_at
            FROM bot_access_log l
            JOIN bot_access_keys k ON k.id = l.key_id
            ORDER BY l.id DESC
            LIMIT %s
            """,
            (cap,),
        )
        rows = []
        for row in cur.fetchall() or []:
            item = _log_view(row)
            item["bot_name"] = row.get("bot_name")
            item["key_prefix"] = row.get("key_prefix")
            rows.append(item)
        return rows
    except Exception as exc:
        print(f"bot list_usage: {exc}")
        return []


def issue_key(name: str, created_by: int | None) -> tuple[dict | None, str | None, str | None]:
    name = (name or "").strip()[:120]
    if not name:
        return None, None, "Give the bot a name."
    raw, digest, prefix = policy.new_key_material()
    try:
        cur = _cur()
        cur.execute(
            """
            INSERT INTO bot_access_keys (name, key_hash, key_prefix, active, controls_json, created_by)
            VALUES (%s, %s, %s, 1, %s, %s)
            """,
            (name, digest, prefix, json.dumps(policy.default_controls()), created_by),
        )
        cur.execute("SELECT * FROM bot_access_keys WHERE id=%s", (cur.lastrowid,))
        return _key_view(cur.fetchone() or {}), raw, None
    except Exception as exc:
        print(f"bot issue_key: {exc}")
        return None, None, "Could not issue that key."


def find_key(raw: str) -> dict | None:
    """The current API key, or the previous key while its 15 minutes are left."""
    digest = policy.hash_key(raw or "")
    if not raw or not digest:
        return None
    try:
        ensure_login_columns()
        cur = _cur()
        cur.execute(
            """
            SELECT * FROM bot_access_keys
            WHERE key_hash=%s OR (prev_key_hash=%s AND prev_key_expires > NOW())
            ORDER BY (key_hash=%s) DESC
            LIMIT 1
            """,
            (digest, digest, digest),
        )
        row = cur.fetchone()
        if not row:
            return None
        view = _key_view(row)
        view["voices"] = voices_for(int(view["id"]))
        return view
    except Exception as exc:
        print(f"bot find_key: {type(exc).__name__}")
        return None


def recent_action_count(key_id: int, action: str, window: int | None = None, limit_on_error: int = 30) -> int:
    """How many successful log rows of this action this bot wrote in the window."""
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT COUNT(*) AS n
            FROM bot_access_log
            WHERE key_id=%s AND action=%s AND ok=1
              AND created_at > DATE_SUB(NOW(), INTERVAL %s SECOND)
            """,
            (int(key_id), action, int(window or policy.RESET_WINDOW_SECONDS)),
        )
        row = cur.fetchone() or {}
        return int(row.get("n") or 0)
    except Exception as exc:
        print(f"bot recent action: {type(exc).__name__}")
        return int(limit_on_error)


def recent_reset_count(key_id: int) -> int:
    """Successful self-service resets for this bot in the last hour.

    A lookup failure counts as the limit, so a broken log cannot mail forever.
    """
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT COUNT(*) AS n
            FROM bot_access_log
            WHERE key_id=%s AND action=%s AND ok=1
              AND created_at > DATE_SUB(NOW(), INTERVAL %s SECOND)
            """,
            (int(key_id), "key_reset", int(policy.RESET_WINDOW_SECONDS)),
        )
        row = cur.fetchone() or {}
        return int(row.get("n") or 0)
    except Exception as exc:
        print(f"bot recent_reset_count: {type(exc).__name__}")
        return int(policy.RESET_LIMIT_PER_HOUR)


def session_seconds_left(session_row_id: int | None) -> int | None:
    if not session_row_id:
        return None
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT TIMESTAMPDIFF(SECOND, NOW(), expires_at) AS seconds_left
            FROM bot_sessions WHERE id=%s
            """,
            (int(session_row_id),),
        )
        row = cur.fetchone() or {}
        if row.get("seconds_left") is None:
            return None
        return max(0, int(row.get("seconds_left") or 0))
    except Exception as exc:
        print(f"bot session left: {type(exc).__name__}")
        return None


def grace_key_active(key_id: int) -> bool:
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT (prev_key_expires > NOW()) AS grace_live
            FROM bot_access_keys WHERE id=%s
            """,
            (int(key_id),),
        )
        row = cur.fetchone() or {}
        return bool(row.get("grace_live"))
    except Exception as exc:
        print(f"bot grace key: {type(exc).__name__}")
        return False


def key_ids_for_inbox(email: str) -> list[int]:
    """Active bots whose API-key inbox is this address. The 2FA inbox does not match."""
    email = policy.normalize_email(email)
    if not email:
        return []
    try:
        ensure_login_columns()
        cur = _cur()
        cur.execute(
            "SELECT id FROM bot_access_keys WHERE email=%s AND active=1",
            (email,),
        )
        return [int(row["id"]) for row in (cur.fetchall() or []) if row.get("id")]
    except Exception as exc:
        print(f"bot key_ids_for_inbox: {type(exc).__name__}")
        return []


def get_key(key_id: int) -> dict | None:
    try:
        cur = _cur()
        cur.execute("SELECT * FROM bot_access_keys WHERE id=%s", (int(key_id),))
        row = cur.fetchone()
        if not row:
            return None
        view = _key_view(row)
        view["voices"] = voices_for(int(view["id"]))
        return view
    except Exception as exc:
        print(f"bot get_key: {exc}")
        return None


def voices_for(key_id: int) -> list[dict]:
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT v.id, v.key_id, v.voice_type, v.user_id, v.label,
                   u.username, u.first_name, u.last_name
            FROM bot_access_voices v
            LEFT JOIN users u ON u.id = v.user_id
            WHERE v.key_id=%s
            ORDER BY v.voice_type ASC, v.id ASC
            """,
            (int(key_id),),
        )
        rows = []
        for row in cur.fetchall() or []:
            item = _clean(row)
            if item.get("voice_type") == "user":
                item["label"] = item.get("label") or policy.person_label(item)
            elif item.get("voice_type") == "church":
                author = policy.person_label(item) if item.get("user_id") else ""
                item["label"] = "Church" + (f" — authored by {author}" if author else "")
            rows.append(item)
        return rows
    except Exception as exc:
        print(f"bot voices_for: {exc}")
        return []


def save_key(key_id: int, active: bool, controls: dict, church_user_id: int | None,
             act_as_user_id: int | None, church_requested: bool, *,
             act_role: str | None = None, admin_granted: bool = False) -> tuple[bool, str | None]:
    """Save switches and the one account this bot acts as.

    The message is a warning when the save still worked. An admin who is not
    allowed is refused, and the previous voices stay.
    """
    note = None
    if not act_as_user_id:
        return False, "Choose the one account this bot acts as."
    if act_role == "Admin" and not admin_granted:
        return False, "That admin cannot use a bot until you allow them above."
    if act_role != "Owner":
        if church_requested:
            note = "This bot acts only as that account, so the church wall was left off."
        church_requested = False
        church_user_id = None
    try:
        cur = _cur()
        cur.execute("SELECT id FROM bot_access_keys WHERE id=%s", (int(key_id),))
        if not cur.fetchone():
            return False, "That bot key is gone."
        cur.execute(
            """
            UPDATE bot_access_keys
            SET active=%s, controls_json=%s
            WHERE id=%s
            """,
            (1 if active else 0, json.dumps(policy.normalize_controls(controls)), int(key_id)),
        )
        existing = voices_for(int(key_id))
        prior_church = next((v.get("user_id") for v in existing if v.get("voice_type") == "church"), None)
        if church_requested and not church_user_id:
            if prior_church:
                note = "Church posts need an author. The previous church author was kept."
                church_user_id = int(prior_church)
            else:
                note = "Church posts need an author, so the church voice was not added."
                church_requested = False
        elif not church_requested:
            church_user_id = None
        cur.execute("DELETE FROM bot_access_voices WHERE key_id=%s", (int(key_id),))
        if church_requested and church_user_id:
            cur.execute(
                """
                INSERT INTO bot_access_voices (key_id, voice_type, user_id, label)
                VALUES (%s, 'church', %s, 'Church')
                """,
                (int(key_id), int(church_user_id)),
            )
        cur.execute(
            """
            INSERT INTO bot_access_voices (key_id, voice_type, user_id, label)
            VALUES (%s, 'user', %s, NULL)
            """,
            (int(key_id), int(act_as_user_id)),
        )
        return True, note
    except Exception as exc:
        print(f"bot save_key: {exc}")
        return False, "Could not save that bot."


def list_keys() -> list[dict]:
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT id, name, key_prefix, active, controls_json, created_by, email, twofa_email,
                   created_at, updated_at
            FROM bot_access_keys
            ORDER BY id DESC
            """
        )
        keys = [_key_view(row) for row in (cur.fetchall() or [])]
    except Exception as exc:
        print(f"bot list_keys: {exc}")
        return []
    if not keys:
        return []
    ids = [int(row["id"]) for row in keys]
    voice_map = {key_id: [] for key_id in ids}
    log_map = {key_id: [] for key_id in ids}
    try:
        marks = ",".join(["%s"] * len(ids))
        cur = _cur()
        cur.execute(
            f"""
            SELECT v.id, v.key_id, v.voice_type, v.user_id, v.label,
                   u.username, u.first_name, u.last_name
            FROM bot_access_voices v
            LEFT JOIN users u ON u.id = v.user_id
            WHERE v.key_id IN ({marks})
            ORDER BY v.id ASC
            """,
            ids,
        )
        for row in cur.fetchall() or []:
            item = _clean(row)
            voice_map.setdefault(int(item["key_id"]), []).append(item)
        cur.execute(
            f"""
            SELECT id, key_id, action, target_type, target_id, ok, detail,
                   snapshot_json, reversed_at, reversed_by, created_at
            FROM bot_access_log
            WHERE key_id IN ({marks})
            ORDER BY id DESC
            LIMIT 200
            """,
            ids,
        )
        for row in cur.fetchall() or []:
            item = _log_view(row)
            bucket = log_map.setdefault(int(item["key_id"]), [])
            if len(bucket) < 20:
                bucket.append(item)
    except Exception as exc:
        print(f"bot list_keys extras: {exc}")
    for row in keys:
        row["voices"] = voice_map.get(int(row["id"]), [])
        row["logs"] = log_map.get(int(row["id"]), [])
        row["church_user_id"] = next(
            (v.get("user_id") for v in row["voices"] if v.get("voice_type") == "church"),
            None,
        )
        row["user_voice_ids"] = [
            int(v["user_id"]) for v in row["voices"]
            if v.get("voice_type") == "user" and v.get("user_id")
        ]
        row["act_as_user_id"] = row["user_voice_ids"][0] if len(row["user_voice_ids"]) == 1 else None
    return keys


def _log_view(row: dict) -> dict:
    item = _clean(row)
    item["ok"] = bool(row.get("ok"))
    item["reversed"] = bool(row.get("reversed_at"))
    snap = row.get("snapshot_json")
    if isinstance(snap, str) and snap:
        try:
            item["snapshot"] = json.loads(snap)
        except ValueError:
            item["snapshot"] = None
    else:
        item["snapshot"] = None
    item.pop("snapshot_json", None)
    item["can_reverse"] = policy.undo_plan(item.get("action") or "", item["reversed"]) is not None and item["ok"]
    item["undo_label"] = policy.undo_label(item.get("action") or "", item["reversed"]) if item["can_reverse"] else None
    return item


def write_log(key_id: int, action: str, *, ok: bool, detail: str = "",
              target_type: str | None = None, target_id: int | None = None,
              snapshot: dict | None = None) -> int | None:
    try:
        cur = _cur()
        cur.execute(
            """
            INSERT INTO bot_access_log
                (key_id, action, target_type, target_id, ok, detail, snapshot_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                int(key_id),
                (action or "")[:40],
                (target_type or None),
                int(target_id) if target_id else None,
                1 if ok else 0,
                (detail or "")[:500],
                json.dumps(snapshot, default=str) if snapshot else None,
            ),
        )
        return int(cur.lastrowid)
    except Exception as exc:
        print(f"bot write_log: {exc}")
        return None


def list_log(key_id: int, limit: int = 50) -> list[dict]:
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT id, key_id, action, target_type, target_id, ok, detail,
                   snapshot_json, reversed_at, reversed_by, created_at
            FROM bot_access_log
            WHERE key_id=%s
            ORDER BY id DESC
            LIMIT %s
            """,
            (int(key_id), int(limit)),
        )
        return [_log_view(row) for row in (cur.fetchall() or [])]
    except Exception as exc:
        print(f"bot list_log: {exc}")
        return []


def get_log(log_id: int) -> dict | None:
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT id, key_id, action, target_type, target_id, ok, detail,
                   snapshot_json, reversed_at, reversed_by, created_at
            FROM bot_access_log WHERE id=%s
            """,
            (int(log_id),),
        )
        row = cur.fetchone()
        return _log_view(row) if row else None
    except Exception as exc:
        print(f"bot get_log: {exc}")
        return None


def set_post_removed(post_id: int, removed: bool) -> tuple[bool, str]:
    try:
        cur = _cur()
        cur.execute("SELECT id, removed_at FROM community_posts WHERE id=%s", (int(post_id),))
        row = cur.fetchone()
        if not row:
            return False, "That post is already gone."
        if removed:
            cur.execute("UPDATE community_posts SET removed_at=NOW() WHERE id=%s", (int(post_id),))
            return True, "Hid that post. The words are still saved."
        cur.execute("UPDATE community_posts SET removed_at=NULL WHERE id=%s", (int(post_id),))
        return True, "Put that post back on the wall."
    except Exception as exc:
        print(f"bot set_post_removed: {exc}")
        return False, "Could not change that post."


def mark_reversed(log_id: int, actor: str, clear: bool) -> None:
    cur = _cur()
    if clear:
        cur.execute(
            "UPDATE bot_access_log SET reversed_at=NULL, reversed_by=NULL WHERE id=%s",
            (int(log_id),),
        )
        return
    cur.execute(
        "UPDATE bot_access_log SET reversed_at=NOW(), reversed_by=%s WHERE id=%s",
        ((actor or "")[:80], int(log_id)),
    )


def read_area(area: str, limit: int = READ_LIMIT) -> tuple[list[dict], bool, str]:
    sql = policy.READS.get(area)
    if not sql:
        return [], False, "That read is not on the bot."
    try:
        cap = max(1, min(int(limit or READ_LIMIT), 100))
        cur = _cur()
        cur.execute(sql, (cap,))
        return [_clean(row) for row in (cur.fetchall() or [])], True, ""
    except Exception as exc:
        print(f"bot read_area {area}: {exc}")
        return [], False, "That table could not be read."


def publish_post(voice: dict, post: dict) -> tuple[int | None, str | None]:
    try:
        from app.models.church_community import record_posting
        from app.models.social import create_post
        post_id = create_post(
            int(voice["user_id"]),
            post["kind"],
            post["title"],
            post["body"],
            "",
            post["visibility"],
        )
    except Exception as exc:
        print(f"bot publish_post: {exc}")
        return None, "Could not save that post."
    if not post_id:
        return None, "Could not save that post. A blocked word or an empty body will do that."
    try:
        record_posting(post["kind"], int(post_id), voice["posted_as"], 0, int(voice["user_id"]))
    except Exception as exc:
        print(f"bot publish stamp: {exc}")
        return int(post_id), "The post was saved, but it was not stamped on that wall."
    return int(post_id), None


def list_voice_posts(voice: dict, limit: int = 20) -> list[dict]:
    cap = max(1, min(int(limit or 20), 50))
    if voice.get("posted_as") == "church":
        try:
            from app.models.social import list_posts_by_voice
            rows = list_posts_by_voice("church", 0, cap, None) or []
        except Exception as exc:
            print(f"bot list church posts: {exc}")
            return []
        out = []
        for row in rows:
            out.append({
                "id": _cell(row.get("id")),
                "kind": row.get("kind"),
                "title": row.get("title"),
                "body": (row.get("body") or "")[:500],
                "visibility": row.get("visibility"),
                "created_at": _cell(row.get("created_at")),
                "as": "church",
            })
        return out
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT p.id, p.kind, p.title, p.body, p.visibility, p.created_at
            FROM community_posts p
            LEFT JOIN content_posting cp
              ON cp.content_id = p.id AND cp.content_type = p.kind
            WHERE p.user_id=%s AND p.removed_at IS NULL
              AND (cp.posted_as IS NULL OR cp.posted_as = 'member')
            ORDER BY p.id DESC
            LIMIT %s
            """,
            (int(voice["user_id"]), cap),
        )
        out = []
        for row in cur.fetchall() or []:
            item = _clean(row)
            item["body"] = (item.get("body") or "")[:500]
            item["as"] = voice.get("as")
            out.append(item)
        return out
    except Exception as exc:
        print(f"bot list_voice_posts: {exc}")
        return []
