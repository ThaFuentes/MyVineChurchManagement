"""Shared safety checks for church bot writes.

Reads drop secret fields. Deletes are soft unless the owner turned on
hard delete and the body repeats the id. Nothing here starts a timer.
"""

from __future__ import annotations

MEMBER_PUBLIC = (
    "id",
    "username",
    "first_name",
    "last_name",
    "email",
    "phone",
    "address",
    "role",
    "needs_approval",
    "accepts_emails",
    "birthday",
    "show_birthday",
    "created_at",
    "email_verified",
)

_SECRET_PARTS = (
    "password",
    "passwd",
    "hash",
    "token",
    "secret",
    "pin",
    "csrf",
    "smtp",
    "stripe",
    "api_key",
    "twofa",
    "session",
)

_OWNER_FIELDS = ("role", "email", "password", "username")
_MEMBER_ROLES = ("Member", "Staff", "Admin")


def redact(row: dict | None) -> dict:
    """Drop secret-looking keys. Nested dicts are cleaned the same way."""
    clean = {}
    for key, val in (row or {}).items():
        low = str(key).lower()
        if any(part in low for part in _SECRET_PARTS):
            continue
        if isinstance(val, dict):
            clean[key] = redact(val)
        else:
            clean[key] = val
    return clean


def public_member(row: dict | None) -> dict:
    """Directory fields only. Password hashes and pins never leave this list."""
    source = row or {}
    return {key: source.get(key) for key in MEMBER_PUBLIC if key in source}


def confirm_delete(body: dict | None, row_id: int) -> tuple[bool, str | None]:
    """(wants a hard delete, error when the confirm phrase is wrong)."""
    body = body or {}
    confirm = str(body.get("confirm") or "").strip()
    flagged = body.get("hard") in (True, 1, "1", "true", "True", "yes")
    if not confirm and not flagged:
        return False, None
    expected = f"DELETE {int(row_id)}"
    if confirm != expected:
        return True, f'Send confirm as "{expected}".'
    return True, None


def _disabling(changes: dict) -> bool:
    if changes.get("disabled") in (True, 1, "1", "true"):
        return True
    if "is_shadow_banned" in changes and changes.get("is_shadow_banned") in (True, 1, "1", "true"):
        return True
    if changes.get("login_locked") in (True, 1, "1", "true"):
        return True
    return False


def member_write_block(current: dict | None, changes: dict | None, acting_id,
                       *, deleting: bool = False, access: bool = False) -> tuple[str, str] | None:
    """Owner accounts and the bot's own role or access stay put."""
    current = current or {}
    changes = changes or {}
    role = current.get("role") or ""
    try:
        uid = int(current.get("id") or 0)
    except (TypeError, ValueError):
        uid = 0
    try:
        actor = int(acting_id or 0)
    except (TypeError, ValueError):
        actor = 0
    owner_touch = deleting or access or _disabling(changes) or any(key in changes for key in _OWNER_FIELDS)
    if role == "Owner" and owner_touch:
        return "owner_protected", "The owner account stays as it is."
    if actor and uid and actor == uid and (deleting or access or "role" in changes):
        return "self_edit", "This bot cannot change its own role, access, or account."
    if changes.get("role") == "Owner":
        return "owner_protected", "This bot cannot make an owner account."
    if "role" in changes and changes.get("role") not in _MEMBER_ROLES:
        return "role", "role must be Member, Staff, or Admin."
    return None


def event_range_problem(start_date, start_time, end_date, end_time) -> str | None:
    """An end, when one is sent, has to be the same moment as the start or later."""
    if not end_date:
        return None
    start = (str(start_date or ""), str(start_time or "00:00"))
    end = (str(end_date), str(end_time or "23:59"))
    if end < start:
        return "The end must be the same as the start, or later."
    return None


def over_comment_rate(count: int, limit: int) -> bool:
    try:
        return int(count or 0) >= int(limit)
    except (TypeError, ValueError):
        return True
