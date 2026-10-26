"""Member directory writes for the church bot.

Passwords are emailed and never returned. An owner account cannot be
demoted, disabled, or deleted. The acting account cannot change its own
role or access.
"""

from __future__ import annotations

import secrets

from app.utils import bot_guard as guard
from app.utils import bot_policy as policy
from app.utils.bot_sermon_common import _fail, _ok

_ready = False
_EDIT = ("first_name", "last_name", "email", "phone", "address", "role", "accepts_emails", "birthday", "show_birthday")


def _cur():
    from app.models.db import get_db
    return get_db().cursor()


def _clip(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def ensure_member_columns() -> None:
    global _ready
    if _ready:
        return
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'deleted_at'
            """
        )
        if not cur.fetchone():
            cur.execute("ALTER TABLE users ADD COLUMN deleted_at DATETIME NULL")
        _ready = True
    except Exception as exc:
        print(f"bot member columns: {type(exc).__name__}")


def _load(member_id: int) -> dict | None:
    ensure_member_columns()
    cur = _cur()
    cur.execute(
        """
        SELECT id, username, first_name, last_name, email, phone, address, role,
               needs_approval, accepts_emails, birthday, show_birthday, created_at,
               COALESCE(email_verified, 0) AS email_verified, deleted_at
        FROM users WHERE id=%s
        """,
        (int(member_id),),
    )
    return cur.fetchone()


def _block(current, changes, acting_id, *, deleting=False, access=False):
    found = guard.member_write_block(current, changes, acting_id, deleting=deleting, access=access)
    if not found:
        return None
    code, message = found
    status = 400 if code == "role" else 403
    out = _fail(message, status, "bot_member_update")
    out["code"] = code
    return out


def _audit_change(actor_id, action: str, item_id, title: str, detail: str) -> None:
    if not actor_id:
        return
    try:
        from app.models.log import log_change
        log_change(int(actor_id), action[:80], item_id=int(item_id) if item_id else None,
                   item_title=(title or "")[:120], details=(detail or "")[:500])
    except Exception as exc:
        print(f"bot member audit: {type(exc).__name__}")


def list_members(search: str = "", page=1) -> dict:
    try:
        ensure_member_columns()
        try:
            page_no = max(1, int(page or 1))
        except (TypeError, ValueError):
            page_no = 1
        cap = 40
        offset = (page_no - 1) * cap
        sql = (
            "SELECT id, username, first_name, last_name, email, phone, address, role, "
            "needs_approval, accepts_emails, birthday, show_birthday, created_at, "
            "COALESCE(email_verified, 0) AS email_verified "
            "FROM users WHERE deleted_at IS NULL"
        )
        params: list = []
        term = (search or "").strip()
        if term:
            like = f"%{term}%"
            sql += (
                " AND (first_name LIKE %s OR last_name LIKE %s OR email LIKE %s "
                "OR username LIKE %s OR phone LIKE %s)"
            )
            params.extend([like, like, like, like, like])
        sql += " ORDER BY last_name, first_name, id LIMIT %s OFFSET %s"
        params.extend([cap, offset])
        cur = _cur()
        cur.execute(sql, tuple(params))
        rows = [guard.public_member(row) for row in (cur.fetchall() or [])]
        return _ok({"members": rows, "page": page_no, "count": len(rows)})
    except Exception as exc:
        print(f"bot members list: {type(exc).__name__}")
        return _fail("The member directory could not be read.", 500, "bot_member_list")


def member_detail(member_id: int) -> dict:
    try:
        row = _load(member_id)
        if not row or row.get("deleted_at"):
            return _fail("That member was not found.", 404, "bot_member_update")
        return _ok({"member": guard.public_member(row)})
    except Exception as exc:
        print(f"bot member detail: {type(exc).__name__}")
        return _fail("That member could not be read.", 500, "bot_member_update")


def _email_taken(email: str, except_id: int | None = None) -> bool:
    cur = _cur()
    if except_id:
        cur.execute("SELECT id FROM users WHERE email=%s AND id<>%s LIMIT 1", (email, int(except_id)))
    else:
        cur.execute("SELECT id FROM users WHERE email=%s LIMIT 1", (email,))
    return bool(cur.fetchone())


def create_member(actor_id: int, body: dict) -> dict:
    body = body or {}
    role = _clip(body.get("role") or "Member", 40) or "Member"
    blocked = _block({"id": 0, "role": ""}, {"role": role}, actor_id)
    if blocked:
        return blocked
    email = policy.normalize_email(body.get("email") or "")
    if not policy.email_ok(email):
        return _fail("Give a real email address.", 400, "bot_member_create")
    first = _clip(body.get("first_name"), 80)
    last = _clip(body.get("last_name"), 80)
    if not first or not last:
        return _fail("Give a first and last name.", 400, "bot_member_create")
    try:
        ensure_member_columns()
        if _email_taken(email):
            return _fail("That email is already on a member.", 400, "bot_member_create")
        from werkzeug.security import generate_password_hash
        raw_password = secrets.token_urlsafe(9)
        username = _clip(body.get("username") or email.split("@", 1)[0], 40) or "member"
        cur = _cur()
        cur.execute("SELECT id FROM users WHERE username=%s LIMIT 1", (username,))
        if cur.fetchone():
            username = _clip(username + str(secrets.randbelow(9000) + 1000), 40)
        cur.execute(
            """
            INSERT INTO users
                (username, password, first_name, last_name, email, phone, address,
                 role, accepts_emails, needs_approval, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s)
            """,
            (
                username,
                generate_password_hash(raw_password),
                first,
                last,
                email,
                _clip(body.get("phone"), 40),
                _clip(body.get("address"), 240),
                role,
                1 if body.get("accepts_emails") in (None, True, 1, "1", "true") else 0,
                int(actor_id) if actor_id else None,
            ),
        )
        new_id = int(cur.lastrowid or 0)
        if not new_id:
            return _fail("That member could not be saved.", 500, "bot_member_create")
        try:
            from app.utils.emailer import send_email
            send_email(
                email,
                "Your My Vine Church account",
                "\n".join([
                    f"Hello {first}.",
                    "",
                    "An account was created for you.",
                    f"Username: {username}",
                    f"Temporary password: {raw_password}",
                    "",
                    "Sign in and change this password.",
                ]),
            )
        except Exception as exc:
            print(f"bot member mail: {type(exc).__name__}")
            cur.execute("DELETE FROM users WHERE id=%s", (new_id,))
            return _fail("The welcome email did not send, so the member was not kept.", 502, "bot_member_create")
        _audit_change(actor_id, "bot_member_create", new_id, f"{first} {last}", "Member created. Password emailed.")
        return _ok(
            {"member": guard.public_member({
                "id": new_id, "username": username, "first_name": first, "last_name": last,
                "email": email, "role": role,
            })},
            {
                "action": "bot_member_create",
                "target_type": "user",
                "target_id": new_id,
                "detail": f"{first} {last}",
                "snapshot": {"member_id": new_id, "email": email},
            },
        )
    except Exception as exc:
        print(f"bot member create: {type(exc).__name__}")
        return _fail("That member could not be saved.", 500, "bot_member_create")


def update_member(actor_id: int, member_id: int, body: dict) -> dict:
    body = body or {}
    try:
        current = _load(member_id)
        if not current or current.get("deleted_at"):
            return _fail("That member was not found.", 404, "bot_member_update")
        changes = {}
        for key in _EDIT:
            if key in body:
                changes[key] = body.get(key)
        if "email" in changes:
            changes["email"] = policy.normalize_email(changes.get("email") or "")
            if not policy.email_ok(changes["email"]):
                return _fail("Give a real email address.", 400, "bot_member_update")
        if "role" in changes:
            changes["role"] = _clip(changes.get("role"), 40)
        blocked = _block(current, changes, actor_id)
        if blocked:
            return blocked
        if not changes:
            return _fail("Send the fields to change.", 400, "bot_member_update")
        if "email" in changes and _email_taken(changes["email"], member_id):
            return _fail("That email is already on a member.", 400, "bot_member_update")
        before = {key: current.get(key) for key in changes}
        sets = ", ".join(f"{key}=%s" for key in changes)
        cur = _cur()
        cur.execute(
            f"UPDATE users SET {sets} WHERE id=%s",
            tuple(changes[key] for key in changes) + (int(member_id),),
        )
        _audit_change(actor_id, "bot_member_update", member_id, current.get("email") or "", "Member updated.")
        fresh = _load(member_id) or current
        return _ok(
            {"member": guard.public_member(fresh)},
            {
                "action": "bot_member_update",
                "target_type": "user",
                "target_id": int(member_id),
                "detail": str(fresh.get("email") or fresh.get("username") or member_id)[:180],
                "snapshot": {"member_id": int(member_id), "before": before, "after": changes},
            },
        )
    except Exception as exc:
        print(f"bot member update: {type(exc).__name__}")
        return _fail("That member could not be saved.", 500, "bot_member_update")


def delete_member(actor_id: int, member_id: int, body: dict, hard_on: bool) -> dict:
    try:
        current = _load(member_id)
        if not current or current.get("deleted_at"):
            return _fail("That member was not found.", 404, "bot_member_delete")
        blocked = _block(current, {}, actor_id, deleting=True)
        if blocked:
            blocked["action"] = "bot_member_delete"
            return blocked
        wants_hard, confirm_err = guard.confirm_delete(body, member_id)
        if wants_hard and not hard_on:
            out = _fail("Hard delete is turned off for this key.", 403, "bot_member_delete")
            out["code"] = "hard_delete"
            out["missing"] = ["hard_delete"]
            return out
        if confirm_err:
            return _fail(confirm_err, 400, "bot_member_delete")
        cur = _cur()
        if wants_hard:
            from app.routes.members.queries import delete_member as hard_remove_user
            hard_remove_user(int(member_id), reassign_to=int(actor_id) if actor_id else None)
            detail = "Hard delete."
        else:
            cur.execute("UPDATE users SET deleted_at=NOW() WHERE id=%s", (int(member_id),))
            detail = "Soft delete."
        _audit_change(actor_id, "bot_member_delete", member_id, current.get("email") or "", detail)
        return _ok(
            {"member_id": int(member_id), "deleted": True, "hard": bool(wants_hard)},
            {
                "action": "bot_member_delete",
                "target_type": "user",
                "target_id": int(member_id),
                "detail": detail,
                "snapshot": {"member_id": int(member_id), "hard": bool(wants_hard)},
            },
        )
    except Exception as exc:
        print(f"bot member delete: {type(exc).__name__}")
        return _fail("That member could not be removed.", 500, "bot_member_delete")


def decide_registration(actor_id: int, user_id: int, approve: bool) -> dict:
    try:
        current = _load(user_id)
        if not current or current.get("deleted_at"):
            return _fail("That registration was not found.", 404, "bot_member_approve")
        if (current.get("role") or "") == "Owner":
            out = _fail("The owner account stays as it is.", 403, "bot_member_approve")
            out["code"] = "owner_protected"
            return out
        cur = _cur()
        if approve:
            cur.execute(
                """
                UPDATE users
                SET needs_approval=0, approved_by=%s, approved_at=NOW()
                WHERE id=%s
                """,
                (int(actor_id) if actor_id else None, int(user_id)),
            )
            action = "bot_member_approve"
            detail = "Approved."
        else:
            cur.execute("UPDATE users SET deleted_at=NOW() WHERE id=%s", (int(user_id),))
            action = "bot_member_reject"
            detail = "Rejected."
        _audit_change(actor_id, action, user_id, current.get("email") or "", detail)
        return _ok(
            {"user_id": int(user_id), "approved": bool(approve)},
            {
                "action": action,
                "target_type": "user",
                "target_id": int(user_id),
                "detail": detail,
                "snapshot": {"member_id": int(user_id), "approve": bool(approve)},
            },
        )
    except Exception as exc:
        print(f"bot registration: {type(exc).__name__}")
        return _fail("That registration could not be updated.", 500, "bot_member_approve")


def list_visitors() -> dict:
    try:
        ensure_member_columns()
        cur = _cur()
        cur.execute(
            """
            SELECT id, username, first_name, last_name, email, phone, role,
                   needs_approval, created_at
            FROM users
            WHERE deleted_at IS NULL
              AND (COALESCE(needs_approval, 0) = 1 OR role IN ('Visitor', 'pending'))
            ORDER BY id DESC
            LIMIT 100
            """
        )
        rows = [guard.public_member(row) for row in (cur.fetchall() or [])]
        return _ok({"visitors": rows, "count": len(rows)})
    except Exception as exc:
        print(f"bot visitors: {type(exc).__name__}")
        return _fail("Visitors could not be read.", 500, "bot_member_list")


def export_members(fmt: str = "json") -> dict:
    try:
        ensure_member_columns()
        cur = _cur()
        cur.execute(
            """
            SELECT id, username, first_name, last_name, email, phone, address, role,
                   accepts_emails, birthday
            FROM users
            WHERE deleted_at IS NULL
            ORDER BY last_name, first_name, id
            LIMIT 2000
            """
        )
        rows = [guard.public_member(row) for row in (cur.fetchall() or [])]
        data = {"members": rows, "count": len(rows), "format": "json"}
        if (fmt or "").lower() == "csv":
            lines = ["id,username,first_name,last_name,email,phone,role"]
            for row in rows:
                lines.append(",".join(
                    str(row.get(key) or "").replace(",", " ")
                    for key in ("id", "username", "first_name", "last_name", "email", "phone", "role")
                ))
            data["format"] = "csv"
            data["csv"] = "\n".join(lines)
        return _ok(
            data,
            {
                "action": "bot_member_export",
                "target_type": "user",
                "target_id": None,
                "detail": f"{len(rows)} members",
                "snapshot": {"count": len(rows)},
            },
        )
    except Exception as exc:
        print(f"bot member export: {type(exc).__name__}")
        return _fail("The member export could not be built.", 500, "bot_member_export")


def member_access(actor_id: int, member_id: int, body: dict | None, write: bool) -> dict:
    try:
        current = _load(member_id)
        if not current or current.get("deleted_at"):
            return _fail("That member was not found.", 404, "bot_member_access")
        cur = _cur()
        if not write:
            cur.execute("SELECT role_name FROM member_roles WHERE user_id=%s ORDER BY role_name", (int(member_id),))
            names = [row.get("role_name") for row in (cur.fetchall() or []) if row.get("role_name")]
            return _ok({"member_id": int(member_id), "role": current.get("role"), "roles": names})
        blocked = _block(current, {}, actor_id, access=True)
        if blocked:
            blocked["action"] = "bot_member_access"
            return blocked
        body = body or {}
        roles = body.get("roles") if isinstance(body.get("roles"), list) else None
        if roles is not None:
            clean = []
            for name in roles:
                text = _clip(name, 50)
                if text and text not in clean:
                    clean.append(text)
            cur.execute("DELETE FROM member_roles WHERE user_id=%s", (int(member_id),))
            for name in clean:
                cur.execute(
                    "INSERT INTO member_roles (user_id, role_name) VALUES (%s, %s)",
                    (int(member_id), name),
                )
        template_id = body.get("template_id")
        if template_id not in (None, ""):
            from app.utils.access_templates import apply_template_to_user
            apply_template_to_user(cur, int(member_id), int(template_id), int(actor_id) if actor_id else None)
        _audit_change(actor_id, "bot_member_access", member_id, current.get("email") or "", "Access updated.")
        return _ok(
            {"member_id": int(member_id), "updated": True},
            {
                "action": "bot_member_access",
                "target_type": "user",
                "target_id": int(member_id),
                "detail": "Access updated.",
                "snapshot": {"member_id": int(member_id), "roles": roles},
            },
        )
    except Exception as exc:
        print(f"bot member access: {type(exc).__name__}")
        return _fail("That access list could not be saved.", 500, "bot_member_access")


def templates(actor_id: int, template_id: int | None, body: dict | None, write: bool) -> dict:
    try:
        from app.utils import access_templates as templates_api
        cur = _cur()
        if not write and template_id is None:
            rows = templates_api.list_templates(cur) or []
            clean = []
            for row in rows:
                item = guard.redact(row)
                item.pop("permissions", None)
                item["permissions"] = row.get("permission_list") or []
                clean.append(item)
            return _ok({"templates": clean, "count": len(clean)})
        if not write:
            row = templates_api.get_template(cur, int(template_id))
            if not row:
                return _fail("That template was not found.", 404, "bot_member_access")
            item = guard.redact(row)
            item.pop("permissions", None)
            item["permissions"] = row.get("permission_list") or []
            return _ok({"template": item})
        body = body or {}
        if body.get("delete") and template_id:
            templates_api.delete_template(cur, int(template_id))
            action_detail = "Template removed."
            saved_id = int(template_id)
        elif template_id:
            current = templates_api.get_template(cur, int(template_id)) or {}
            templates_api.update_template(
                cur,
                int(template_id),
                name=_clip(body.get("name") or current.get("name") or "Template", 120),
                description=body.get("description") if "description" in body else (current.get("description") or ""),
                for_role=_clip(body.get("for_role") or current.get("for_role") or "any", 20),
                permissions=body.get("permissions") if isinstance(body.get("permissions"), list) else (current.get("permission_list") or []),
                is_default=bool(body.get("is_default")) if "is_default" in body else bool(current.get("is_default")),
            )
            action_detail = "Template updated."
            saved_id = int(template_id)
        else:
            saved_id = int(templates_api.create_template(
                cur,
                name=_clip(body.get("name") or "Template", 120),
                description=_clip(body.get("description"), 500),
                for_role=_clip(body.get("for_role") or "any", 20),
                permissions=body.get("permissions") or [],
                created_by=int(actor_id) if actor_id else None,
                is_default=bool(body.get("is_default")),
            ) or 0)
            action_detail = "Template created."
        _audit_change(actor_id, "bot_member_access", saved_id, body.get("name") or "", action_detail)
        return _ok(
            {"template_id": saved_id},
            {
                "action": "bot_member_access",
                "target_type": "access_template",
                "target_id": saved_id or None,
                "detail": action_detail,
                "snapshot": {"template_id": saved_id},
            },
        )
    except Exception as exc:
        print(f"bot access templates: {type(exc).__name__}")
        return _fail("That access template could not be saved.", 500, "bot_member_access")


def apply_undo(plan: str, entry: dict) -> tuple[bool, str]:
    action = (entry or {}).get("action") or ""
    snapshot = entry.get("snapshot") or {}
    member_id = snapshot.get("member_id") or entry.get("target_id")
    if not member_id or snapshot.get("hard"):
        return False, "That member change cannot be put back."
    try:
        ensure_member_columns()
        cur = _cur()
        if action == "bot_member_create":
            if plan == "hide":
                cur.execute("UPDATE users SET deleted_at=NOW() WHERE id=%s", (int(member_id),))
                return True, "Hid that member."
            cur.execute("UPDATE users SET deleted_at=NULL WHERE id=%s", (int(member_id),))
            return True, "Put that member back."
        if action == "bot_member_delete":
            if plan in ("show", "restore"):
                cur.execute("UPDATE users SET deleted_at=NULL WHERE id=%s", (int(member_id),))
                return True, "Put that member back."
            cur.execute("UPDATE users SET deleted_at=NOW() WHERE id=%s", (int(member_id),))
            return True, "Hid that member again."
        if action == "bot_member_update":
            side = snapshot.get("before") if plan == "restore" else snapshot.get("after")
            if not isinstance(side, dict) or not side:
                return False, "That member change has nothing to put back."
            fields = {key: side.get(key) for key in _EDIT if key in side}
            if not fields:
                return False, "That member change has nothing to put back."
            sets = ", ".join(f"{key}=%s" for key in fields)
            cur.execute(
                f"UPDATE users SET {sets} WHERE id=%s",
                tuple(fields[key] for key in fields) + (int(member_id),),
            )
            return True, "Put the previous member fields back." if plan == "restore" else "Applied that member change again."
        if action == "bot_member_reject":
            if plan in ("show", "restore"):
                cur.execute("UPDATE users SET deleted_at=NULL WHERE id=%s", (int(member_id),))
                return True, "Put that registration back."
            return False, "That registration change cannot be put back."
    except Exception as exc:
        print(f"bot member undo: {type(exc).__name__}")
        return False, "That member change could not be undone."
    return False, "That member change cannot be put back."
