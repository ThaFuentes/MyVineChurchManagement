"""Event and calendar writes for the church bot.

A delete hides the event. Mail goes out only when the comms_send switch
is on. The end, when one is sent, cannot be earlier than the start.
"""

from __future__ import annotations

from app.utils import bot_guard as guard
from app.utils.bot_sermon_common import _clip, _fail, _ok

_ready = False
_FIELDS = (
    "event_name",
    "event_date",
    "event_time",
    "end_date",
    "end_time",
    "location",
    "description",
    "visibility",
    "speaker_host",
    "theme",
    "campus_id",
    "capacity",
    "registration_open",
    "potluck_enabled",
)
_PUBLIC = (
    "id", "event_name", "event_date", "event_time", "end_date", "end_time",
    "location", "description", "visibility", "speaker_host", "theme",
    "campus_id", "capacity", "registration_open", "potluck_enabled",
    "created_by", "created_at",
)


def _cur():
    from app.models.db import get_db
    return get_db().cursor()


def ensure_event_columns() -> None:
    global _ready
    if _ready:
        return
    try:
        cur = _cur()
        for column, definition in (
            ("end_date", "VARCHAR(10) NULL"),
            ("end_time", "VARCHAR(8) NULL"),
            ("deleted_at", "DATETIME NULL"),
            ("campus_id", "INT UNSIGNED NULL"),
        ):
            cur.execute(
                """
                SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'events' AND COLUMN_NAME = %s
                """,
                (column,),
            )
            if not cur.fetchone():
                cur.execute(f"ALTER TABLE events ADD COLUMN {column} {definition}")
        cur.execute(
            """
            SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'potluck_signups' AND COLUMN_NAME = 'removed_at'
            """
        )
        if not cur.fetchone():
            cur.execute("ALTER TABLE potluck_signups ADD COLUMN removed_at DATETIME NULL")
        _ready = True
    except Exception as exc:
        print(f"bot event columns: {type(exc).__name__}")


def _row(row: dict | None) -> dict:
    return {key: (row or {}).get(key) for key in _PUBLIC if key in (row or {})}


def _load(event_id: int) -> dict | None:
    ensure_event_columns()
    cur = _cur()
    cur.execute("SELECT * FROM events WHERE id=%s", (int(event_id),))
    return cur.fetchone()


def _changes(body: dict) -> dict:
    changes = {}
    for key in _FIELDS:
        if key not in (body or {}):
            continue
        if key in ("campus_id", "capacity"):
            raw = body.get(key)
            if raw in (None, ""):
                changes[key] = None
            else:
                changes[key] = int(raw)
            continue
        if key in ("registration_open", "potluck_enabled"):
            changes[key] = 1 if body.get(key) in (True, 1, "1", "true", "yes") else 0
            continue
        if key == "visibility":
            visibility = _clip(body.get(key) or "private", 20).lower()
            changes[key] = visibility if visibility in ("public", "private") else "private"
            continue
        limit = 10 if key in ("event_date", "end_date") else 8 if key in ("event_time", "end_time") else 4000
        if key == "event_name":
            limit = 255
        changes[key] = _clip(body.get(key), limit)
    return changes


def _audit(actor_id, action: str, item_id, detail: str) -> None:
    if not actor_id:
        return
    try:
        from app.models.log import log_change
        log_change(int(actor_id), action[:80], item_id=int(item_id) if item_id else None, details=(detail or "")[:500])
    except Exception as exc:
        print(f"bot event audit: {type(exc).__name__}")


def list_events(start: str = "", end: str = "", campus_id=None) -> dict:
    try:
        ensure_event_columns()
        sql = (
            "SELECT id, event_name, event_date, event_time, end_date, end_time, location, "
            "visibility, description, speaker_host, theme, campus_id, capacity, "
            "registration_open, potluck_enabled, created_by, created_at "
            "FROM events WHERE deleted_at IS NULL"
        )
        params: list = []
        if (start or "").strip():
            sql += " AND event_date >= %s"
            params.append(_clip(start, 10))
        if (end or "").strip():
            sql += " AND event_date <= %s"
            params.append(_clip(end, 10))
        if campus_id not in (None, ""):
            sql += " AND (campus_id=%s OR campus_id IS NULL)"
            params.append(int(campus_id))
        sql += " ORDER BY event_date, id LIMIT 100"
        cur = _cur()
        cur.execute(sql, tuple(params))
        rows = [_row(row) for row in (cur.fetchall() or [])]
        return _ok({"events": rows, "count": len(rows)})
    except Exception as exc:
        print(f"bot events list: {type(exc).__name__}")
        return _fail("Events could not be read.", 500, "bot_event_list")


def event_detail(event_id: int) -> dict:
    try:
        row = _load(event_id)
        if not row or row.get("deleted_at"):
            return _fail("That event was not found.", 404, "bot_event_update")
        return _ok({"event": _row(row)})
    except Exception as exc:
        print(f"bot event detail: {type(exc).__name__}")
        return _fail("That event could not be read.", 500, "bot_event_update")


def create_event(actor_id: int, body: dict) -> dict:
    body = body or {}
    changes = _changes(body)
    name = changes.get("event_name") or ""
    day = changes.get("event_date") or ""
    if not name or not day:
        return _fail("Give an event name and a date.", 400, "bot_event_create")
    problem = guard.event_range_problem(day, changes.get("event_time"), changes.get("end_date"), changes.get("end_time"))
    if problem:
        return _fail(problem, 400, "bot_event_create")
    if "visibility" not in changes:
        changes["visibility"] = "private"
    try:
        ensure_event_columns()
        columns = list(changes) + ["created_by"]
        values = [changes[key] for key in changes] + [int(actor_id) if actor_id else None]
        cur = _cur()
        marks = ", ".join(["%s"] * len(columns))
        cur.execute(
            f"INSERT INTO events ({', '.join(columns)}) VALUES ({marks})",
            tuple(values),
        )
        new_id = int(cur.lastrowid or 0)
        _audit(actor_id, "bot_event_create", new_id, name)
        return _ok(
            {"event_id": new_id, "event_name": name},
            {
                "action": "bot_event_create",
                "target_type": "event",
                "target_id": new_id,
                "detail": name[:180],
                "snapshot": {"event_id": new_id},
            },
        )
    except Exception as exc:
        print(f"bot event create: {type(exc).__name__}")
        return _fail("That event could not be saved.", 500, "bot_event_create")


def update_event(actor_id: int, event_id: int, body: dict) -> dict:
    try:
        current = _load(event_id)
        if not current or current.get("deleted_at"):
            return _fail("That event was not found.", 404, "bot_event_update")
        changes = _changes(body or {})
        if not changes:
            return _fail("Send the fields to change.", 400, "bot_event_update")
        start = changes.get("event_date", current.get("event_date"))
        start_time = changes.get("event_time", current.get("event_time"))
        end = changes.get("end_date", current.get("end_date"))
        end_time = changes.get("end_time", current.get("end_time"))
        problem = guard.event_range_problem(start, start_time, end, end_time)
        if problem:
            return _fail(problem, 400, "bot_event_update")
        before = {key: current.get(key) for key in changes}
        sets = ", ".join(f"{key}=%s" for key in changes)
        cur = _cur()
        cur.execute(
            f"UPDATE events SET {sets}, updated_by=%s WHERE id=%s",
            tuple(changes[key] for key in changes) + (int(actor_id) if actor_id else None, int(event_id)),
        )
        _audit(actor_id, "bot_event_update", event_id, current.get("event_name") or "")
        return _ok(
            {"event_id": int(event_id), **{key: changes[key] for key in changes}},
            {
                "action": "bot_event_update",
                "target_type": "event",
                "target_id": int(event_id),
                "detail": str(current.get("event_name") or event_id)[:180],
                "snapshot": {"event_id": int(event_id), "before": before, "after": changes},
            },
        )
    except Exception as exc:
        print(f"bot event update: {type(exc).__name__}")
        return _fail("That event could not be saved.", 500, "bot_event_update")


def delete_event(actor_id: int, event_id: int, body: dict, hard_on: bool) -> dict:
    try:
        current = _load(event_id)
        if not current or current.get("deleted_at"):
            return _fail("That event was not found.", 404, "bot_event_delete")
        wants_hard, confirm_err = guard.confirm_delete(body, event_id)
        if wants_hard and not hard_on:
            out = _fail("Hard delete is turned off for this key.", 403, "bot_event_delete")
            out["code"] = "hard_delete"
            out["missing"] = ["hard_delete"]
            return out
        if confirm_err:
            return _fail(confirm_err, 400, "bot_event_delete")
        cur = _cur()
        if wants_hard:
            cur.execute("DELETE FROM events WHERE id=%s", (int(event_id),))
        else:
            cur.execute(
                "UPDATE events SET deleted_at=NOW(), moderation_hidden=1 WHERE id=%s",
                (int(event_id),),
            )
        _audit(actor_id, "bot_event_delete", event_id, "Hard delete." if wants_hard else "Soft delete.")
        return _ok(
            {"event_id": int(event_id), "deleted": True, "hard": bool(wants_hard)},
            {
                "action": "bot_event_delete",
                "target_type": "event",
                "target_id": int(event_id),
                "detail": str(current.get("event_name") or "")[:180],
                "snapshot": {"event_id": int(event_id), "hard": bool(wants_hard)},
            },
        )
    except Exception as exc:
        print(f"bot event delete: {type(exc).__name__}")
        return _fail("That event could not be removed.", 500, "bot_event_delete")


def signups(event_id: int, body: dict | None, write: bool, signup_id: int | None = None) -> dict:
    try:
        current = _load(event_id)
        if not current or current.get("deleted_at"):
            return _fail("That event was not found.", 404, "bot_event_signup")
        ensure_event_columns()
        cur = _cur()
        if signup_id and write:
            cur.execute(
                "UPDATE potluck_signups SET removed_at=NOW() WHERE id=%s AND event_id=%s",
                (int(signup_id), int(event_id)),
            )
            return _ok(
                {"event_id": int(event_id), "signup_id": int(signup_id), "deleted": True},
                {
                    "action": "bot_event_signup",
                    "target_type": "event",
                    "target_id": int(event_id),
                    "detail": f"Hid signup {int(signup_id)}",
                    "snapshot": {"event_id": int(event_id), "signup_id": int(signup_id)},
                },
            )
        if not write:
            cur.execute(
                """
                SELECT id, event_id, name, item, quantity, note, created_at
                FROM potluck_signups
                WHERE event_id=%s AND removed_at IS NULL
                ORDER BY id
                """,
                (int(event_id),),
            )
            return _ok({"event_id": int(event_id), "signups": list(cur.fetchall() or [])})
        body = body or {}
        name = _clip(body.get("name"), 120)
        item = _clip(body.get("item"), 240)
        if not name or not item:
            return _fail("Give a name and the item they are bringing.", 400, "bot_event_signup")
        cur.execute(
            """
            INSERT INTO potluck_signups (event_id, name, item, quantity, note)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (int(event_id), name, item, _clip(body.get("quantity"), 40), _clip(body.get("note"), 240)),
        )
        return _ok(
            {"event_id": int(event_id), "signup_id": int(cur.lastrowid or 0)},
            {
                "action": "bot_event_signup",
                "target_type": "event",
                "target_id": int(event_id),
                "detail": item[:180],
                "snapshot": {"event_id": int(event_id), "signup_id": int(cur.lastrowid or 0)},
            },
        )
    except Exception as exc:
        print(f"bot event signups: {type(exc).__name__}")
        return _fail("Those signups could not be saved.", 500, "bot_event_signup")


def email_event(actor_id: int, event_id: int, body: dict, send_on: bool) -> dict:
    if not send_on:
        out = _fail("Sending mail is turned off for this key.", 403, "bot_event_email")
        out["code"] = "switch_off"
        out["missing"] = ["comms_send"]
        return out
    body = body or {}
    subject = _clip(body.get("subject"), 180)
    message = _clip(body.get("message"), 4000)
    if not subject:
        return _fail("Give a subject.", 400, "bot_event_email")
    try:
        current = _load(event_id)
        if not current or current.get("deleted_at"):
            return _fail("That event was not found.", 404, "bot_event_email")
        cur = _cur()
        ids = body.get("user_ids") if isinstance(body.get("user_ids"), list) else []
        clean_ids = []
        for raw in ids[:40]:
            try:
                clean_ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        if clean_ids:
            marks = ", ".join(["%s"] * len(clean_ids))
            cur.execute(
                f"SELECT email FROM users WHERE id IN ({marks}) AND accepts_event_emails=1 AND email IS NOT NULL",
                tuple(clean_ids),
            )
        else:
            cur.execute("SELECT email FROM users WHERE accepts_event_emails=1 AND email IS NOT NULL LIMIT 40")
        emails = [row.get("email") for row in (cur.fetchall() or []) if row.get("email")]
        if not emails:
            return _fail("No one on that list accepts event email.", 400, "bot_event_email")
        from app.utils.emailer import send_email
        note = f"{message}\n\nEvent: {current.get('event_name')}"
        sent = 0
        for address in emails:
            send_email(address, subject, note)
            sent += 1
        _audit(actor_id, "bot_event_email", event_id, f"Sent to {sent}.")
        return _ok(
            {"event_id": int(event_id), "sent": sent},
            {
                "action": "bot_event_email",
                "target_type": "event",
                "target_id": int(event_id),
                "detail": f"Sent to {sent}.",
                "snapshot": {"event_id": int(event_id), "sent": sent},
            },
        )
    except Exception as exc:
        print(f"bot event email: {type(exc).__name__}")
        return _fail("That event email could not be sent.", 500, "bot_event_email")


def apply_undo(plan: str, entry: dict) -> tuple[bool, str]:
    action = (entry or {}).get("action") or ""
    snapshot = entry.get("snapshot") or {}
    event_id = snapshot.get("event_id") or entry.get("target_id")
    if not event_id or snapshot.get("hard"):
        return False, "That event change cannot be put back."
    try:
        ensure_event_columns()
        cur = _cur()
        if action == "bot_event_delete":
            if plan in ("show", "restore"):
                cur.execute(
                    "UPDATE events SET deleted_at=NULL, moderation_hidden=0 WHERE id=%s",
                    (int(event_id),),
                )
                return True, "Put that event back."
            cur.execute(
                "UPDATE events SET deleted_at=NOW(), moderation_hidden=1 WHERE id=%s",
                (int(event_id),),
            )
            return True, "Hid that event again."
        if action == "bot_event_signup" and snapshot.get("signup_id"):
            if plan in ("show", "restore"):
                cur.execute("UPDATE potluck_signups SET removed_at=NULL WHERE id=%s", (int(snapshot["signup_id"]),))
                return True, "Put that signup back."
            cur.execute("UPDATE potluck_signups SET removed_at=NOW() WHERE id=%s", (int(snapshot["signup_id"]),))
            return True, "Hid that signup again."
        if action == "bot_event_update":
            side = snapshot.get("before") if plan == "restore" else snapshot.get("after")
            if not isinstance(side, dict) or not side:
                return False, "That event change has nothing to put back."
            fields = {key: side.get(key) for key in _FIELDS if key in side}
            sets = ", ".join(f"{key}=%s" for key in fields)
            cur.execute(
                f"UPDATE events SET {sets} WHERE id=%s",
                tuple(fields[key] for key in fields) + (int(event_id),),
            )
            return True, "Put the previous event fields back." if plan == "restore" else "Applied that event change again."
    except Exception as exc:
        print(f"bot event undo: {type(exc).__name__}")
        return False, "That event change could not be undone."
    return False, "That event change cannot be put back."
