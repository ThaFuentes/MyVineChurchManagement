"""Hide, edit, and delete for sermons, posts, and the lineup.

Soft delete sets removed_at and can be reversed. A hard delete runs only
when the hard_delete switch is on and the body says DELETE plus the id.
"""

from __future__ import annotations

from app.utils import bot_guard as guard
from app.utils.bot_sermon_common import _clip, _db, _fail, _ok

_SOFT = {
    "pastoral_sermons": "bot_sermon_delete",
    "sermon_sections": "bot_section_delete",
    "illustration_library": "bot_illustration_delete",
    "pastoral_vault": "bot_vault_delete",
    "community_posts": "bot_post_delete",
}
_MOD = {
    "post": "community_posts",
    "event": "events",
    "announcement": "announcements",
    "dream": "dreams",
    "prophecy": "prophecies",
    "prayer": "prayers",
    "sermon": "sermons",
}


def _columns(table: str) -> set[str]:
    cur = _db().cursor()
    cur.execute(
        """
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        """,
        (table,),
    )
    return {row.get("COLUMN_NAME") for row in (cur.fetchall() or []) if row.get("COLUMN_NAME")}


def _hard_block(body: dict, row_id: int, hard_on: bool, action: str):
    wants, err = guard.confirm_delete(body, row_id)
    if wants and not hard_on:
        out = _fail("Hard delete is turned off for this key.", 403, action)
        out["code"] = "hard_delete"
        out["missing"] = ["hard_delete"]
        return "blocked", out
    if err:
        return "blocked", _fail(err, 400, action)
    return ("hard" if wants else "soft"), None


def _set_removed(table: str, row_id: int, hide: bool) -> None:
    cur = _db().cursor()
    if hide:
        cur.execute(f"UPDATE {table} SET removed_at=NOW() WHERE id=%s", (int(row_id),))
    else:
        cur.execute(f"UPDATE {table} SET removed_at=NULL WHERE id=%s", (int(row_id),))


def hide_content(table: str, row_id: int, *, hide: bool, action: str, sermon_id: int | None = None) -> dict:
    if table not in _SOFT:
        return _fail("That item cannot be changed here.", 400, action)
    try:
        cur = _db().cursor()
        if table == "sermon_sections" and sermon_id:
            cur.execute(
                "SELECT id FROM sermon_sections WHERE id=%s AND sermon_id=%s",
                (int(row_id), int(sermon_id)),
            )
        else:
            cur.execute(f"SELECT id FROM {table} WHERE id=%s", (int(row_id),))
        if not cur.fetchone():
            return _fail("That item was not found.", 404, action)
        _set_removed(table, row_id, hide)
        return _ok(
            {"id": int(row_id), "hidden": bool(hide)},
            {
                "action": action,
                "target_type": table,
                "target_id": int(row_id),
                "detail": "Hidden." if hide else "Visible again.",
                "snapshot": {"id": int(row_id), "table": table, "sermon_id": sermon_id},
            },
        )
    except Exception as exc:
        print(f"bot content hide: {type(exc).__name__}")
        return _fail("That item could not be updated.", 500, action)


def delete_content(table: str, row_id: int, body: dict, hard_on: bool, *, sermon_id: int | None = None) -> dict:
    action = _SOFT.get(table) or "bot_content_delete"
    mode, blocked = _hard_block(body or {}, row_id, hard_on, action)
    if blocked:
        return blocked
    if mode == "soft":
        return hide_content(table, row_id, hide=True, action=action, sermon_id=sermon_id)
    try:
        cur = _db().cursor()
        if table == "sermon_sections" and sermon_id:
            cur.execute(
                "DELETE FROM sermon_sections WHERE id=%s AND sermon_id=%s",
                (int(row_id), int(sermon_id)),
            )
        else:
            cur.execute(f"DELETE FROM {table} WHERE id=%s", (int(row_id),))
        if not cur.rowcount:
            return _fail("That item was not found.", 404, action)
        return _ok(
            {"id": int(row_id), "deleted": True, "hard": True},
            {
                "action": action,
                "target_type": table,
                "target_id": int(row_id),
                "detail": "Hard delete.",
                "snapshot": {"id": int(row_id), "table": table, "hard": True},
            },
        )
    except Exception as exc:
        print(f"bot content purge: {type(exc).__name__}")
        return _fail("That item could not be removed.", 500, action)


def get_post(post_id: int) -> dict:
    try:
        cur = _db().cursor()
        cur.execute(
            """
            SELECT id, user_id, kind, title, body, visibility, removed_at, created_at
            FROM community_posts WHERE id=%s
            """,
            (int(post_id),),
        )
        row = cur.fetchone()
        if not row:
            return _fail("That post was not found.", 404, "bot_post_edit")
        item = {key: row.get(key) for key in ("id", "user_id", "kind", "title", "body", "visibility", "removed_at", "created_at")}
        item["hidden"] = bool(row.get("removed_at"))
        return _ok({"post": item})
    except Exception as exc:
        print(f"bot post get: {type(exc).__name__}")
        return _fail("That post could not be read.", 500, "bot_post_edit")


def edit_post(post_id: int, body: dict) -> dict:
    body = body or {}
    try:
        cur = _db().cursor()
        cur.execute(
            "SELECT id, title, body, visibility FROM community_posts WHERE id=%s",
            (int(post_id),),
        )
        row = cur.fetchone()
        if not row:
            return _fail("That post was not found.", 404, "bot_post_edit")
        changes = {}
        if "title" in body:
            changes["title"] = _clip(body.get("title"), 255) or "Post"
        if "body" in body:
            changes["body"] = _clip(body.get("body"), 8000)
        if "visibility" in body:
            visibility = _clip(body.get("visibility") or "public", 20).lower()
            changes["visibility"] = visibility if visibility in ("public", "private", "personal", "followers") else "public"
        if not changes:
            return _fail("Send a title, body, or visibility.", 400, "bot_post_edit")
        before = {key: row.get(key) for key in changes}
        sets = ", ".join(f"{key}=%s" for key in changes)
        cur.execute(
            f"UPDATE community_posts SET {sets} WHERE id=%s",
            tuple(changes[key] for key in changes) + (int(post_id),),
        )
        return _ok(
            {"post_id": int(post_id), **changes},
            {
                "action": "bot_post_edit",
                "target_type": "community_post",
                "target_id": int(post_id),
                "detail": str(changes.get("title") or row.get("title") or "Post")[:180],
                "snapshot": {"id": int(post_id), "before": before, "after": changes},
            },
        )
    except Exception as exc:
        print(f"bot post edit: {type(exc).__name__}")
        return _fail("That post could not be saved.", 500, "bot_post_edit")


def hide_post(post_id: int, hide: bool) -> dict:
    try:
        cur = _db().cursor()
        cur.execute("SELECT id, title FROM community_posts WHERE id=%s", (int(post_id),))
        row = cur.fetchone()
        if not row:
            return _fail("That post was not found.", 404, "bot_post_hide")
        _set_removed("community_posts", post_id, hide)
        return _ok(
            {"post_id": int(post_id), "hidden": bool(hide)},
            {
                "action": "bot_post_hide",
                "target_type": "community_post",
                "target_id": int(post_id),
                "detail": str(row.get("title") or "Post")[:180],
                "snapshot": {"id": int(post_id), "table": "community_posts"},
            },
        )
    except Exception as exc:
        print(f"bot post hide: {type(exc).__name__}")
        return _fail("That post could not be updated.", 500, "bot_post_hide")


def clear_lineup(plan_id: int, body: dict, hard_on: bool) -> dict:
    mode, blocked = _hard_block(body or {}, plan_id, hard_on, "bot_lineup_delete")
    if blocked:
        return blocked
    try:
        cur = _db().cursor()
        cur.execute(
            "SELECT id, service_date, pastoral_sermon_id FROM service_plans WHERE id=%s",
            (int(plan_id),),
        )
        row = cur.fetchone()
        if not row:
            return _fail("That lineup day was not found.", 404, "bot_lineup_delete")
        if mode == "hard":
            cur.execute("DELETE FROM service_plans WHERE id=%s", (int(plan_id),))
            return _ok(
                {"id": int(plan_id), "deleted": True, "hard": True},
                {
                    "action": "bot_lineup_delete",
                    "target_type": "service_plan",
                    "target_id": int(plan_id),
                    "detail": str(row.get("service_date") or plan_id),
                    "snapshot": {"id": int(plan_id), "hard": True},
                },
            )
        before = row.get("pastoral_sermon_id")
        cur.execute("UPDATE service_plans SET pastoral_sermon_id=NULL WHERE id=%s", (int(plan_id),))
        return _ok(
            {"id": int(plan_id), "hidden": True},
            {
                "action": "bot_lineup_delete",
                "target_type": "service_plan",
                "target_id": int(plan_id),
                "detail": str(row.get("service_date") or plan_id),
                "snapshot": {"id": int(plan_id), "before_sermon_id": before},
            },
        )
    except Exception as exc:
        print(f"bot lineup delete: {type(exc).__name__}")
        return _fail("That lineup day could not be changed.", 500, "bot_lineup_delete")


def moderate(kind: str, item_id: int, body: dict) -> dict:
    kind = (kind or "").strip().lower()
    table = _MOD.get(kind)
    if not table:
        return _fail("kind must be post, event, announcement, dream, prophecy, prayer, or sermon.", 400, "bot_moderate")
    action = _clip((body or {}).get("action") or (body or {}).get("decision") or "", 20).lower()
    if action not in ("approve", "reject", "hide"):
        return _fail("action must be approve, reject, or hide.", 400, "bot_moderate")
    try:
        cols = _columns(table)
        if not cols:
            return _fail("That content is not on this church.", 404, "bot_moderate")
        cur = _db().cursor()
        cur.execute(f"SELECT id FROM {table} WHERE id=%s", (int(item_id),))
        if not cur.fetchone():
            return _fail("That item was not found.", 404, "bot_moderate")
        if action in ("hide", "reject") and "moderation_hidden" in cols:
            cur.execute(f"UPDATE {table} SET moderation_hidden=1 WHERE id=%s", (int(item_id),))
        elif action in ("hide", "reject") and "removed_at" in cols:
            cur.execute(f"UPDATE {table} SET removed_at=NOW() WHERE id=%s", (int(item_id),))
        elif action == "approve" and "is_approved" in cols:
            cur.execute(f"UPDATE {table} SET is_approved=1 WHERE id=%s", (int(item_id),))
            if "moderation_hidden" in cols:
                cur.execute(f"UPDATE {table} SET moderation_hidden=0 WHERE id=%s", (int(item_id),))
        elif action == "approve" and "moderation_hidden" in cols:
            cur.execute(f"UPDATE {table} SET moderation_hidden=0 WHERE id=%s", (int(item_id),))
        else:
            return _fail("That item has no moderation column.", 400, "bot_moderate")
        return _ok(
            {"kind": kind, "id": int(item_id), "action": action},
            {
                "action": "bot_moderate",
                "target_type": table,
                "target_id": int(item_id),
                "detail": f"{action} {kind} {int(item_id)}",
                "snapshot": {"id": int(item_id), "table": table, "decision": action},
            },
        )
    except Exception as exc:
        print(f"bot moderate: {type(exc).__name__}")
        return _fail("That item could not be moderated.", 500, "bot_moderate")


def apply_undo(plan: str, entry: dict) -> tuple[bool, str]:
    action = (entry or {}).get("action") or ""
    snapshot = entry.get("snapshot") or {}
    if snapshot.get("hard"):
        return False, "A hard delete cannot be put back."
    table = snapshot.get("table")
    row_id = snapshot.get("id") or entry.get("target_id")
    try:
        if action == "bot_post_edit":
            side = snapshot.get("before") if plan == "restore" else snapshot.get("after")
            if not isinstance(side, dict) or not side:
                return False, "That post change has nothing to put back."
            cur = _db().cursor()
            sets = ", ".join(f"{key}=%s" for key in side)
            cur.execute(
                f"UPDATE community_posts SET {sets} WHERE id=%s",
                tuple(side[key] for key in side) + (int(row_id),),
            )
            return True, "Put the previous post back." if plan == "restore" else "Applied that post change again."
        if action == "bot_lineup_delete" and "before_sermon_id" in snapshot:
            cur = _db().cursor()
            sermon_id = snapshot.get("before_sermon_id") if plan in ("show", "restore") else None
            cur.execute(
                "UPDATE service_plans SET pastoral_sermon_id=%s WHERE id=%s",
                (sermon_id, int(row_id)),
            )
            return True, "Put that lineup sermon back." if sermon_id else "Cleared that lineup sermon again."
        if table in _SOFT and row_id:
            hide = plan == "hide" or (action.endswith("_delete") and plan not in ("show", "restore"))
            if action.endswith("_unhide"):
                hide = plan == "hide"
            if plan in ("show", "restore"):
                hide = False
            _set_removed(table, int(row_id), hide)
            return True, "Put that back." if not hide else "Hid that again."
        if action == "bot_comment_edit" and snapshot.get("area") and row_id:
            from app.utils.bot_comments import restore_comment_text
            side = snapshot.get("before") if plan == "restore" else snapshot.get("after")
            if side is None:
                return False, "That comment change has nothing to put back."
            return restore_comment_text(snapshot.get("area"), int(row_id), str(side))
        if action == "bot_comment_delete" and snapshot.get("area") and row_id:
            from app.utils.bot_comments import set_comment_removed
            return set_comment_removed(snapshot.get("area"), int(row_id), plan == "hide")
    except Exception as exc:
        print(f"bot content undo: {type(exc).__name__}")
        return False, "That change could not be undone."
    return False, "That change cannot be put back."
