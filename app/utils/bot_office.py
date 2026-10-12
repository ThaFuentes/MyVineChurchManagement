"""Church office calls for the bot.

Groups, worship, giving, bills, accounting, inventory, and attendance.
The acting account is already chosen by the owner. This module does not
pick a different person. It never returns card numbers, account numbers,
bill logins, bank details, tax ids, or passwords, and it does not send email.
"""

from __future__ import annotations

from pymysql.err import IntegrityError

from app.utils.bot_sermon_common import (
    _clip,
    _db,
    _fail,
    _int_or_none,
    _ok,
    _parse_date,
    _plain,
)

GROUP_ROLES = ("member", "leader")
BILL_STATUSES = ("pending", "paid", "overdue", "partial")
WORSHIP_GROUP_NAME = "Worship Team Group"
SECRET_FIELDS = {
    "password",
    "account_number",
    "customer_number",
    "card",
    "card_number",
    "cvv",
    "cvc",
    "routing",
    "routing_number",
    "tax_id",
    "encrypted_username",
    "encrypted_password",
    "login",
    "login_url",
    "payment_url",
    "pin",
    "checkin_pin",
    "bank",
    "bank_account",
}
_COL_CACHE: dict[str, set[str]] = {}


def _cur():
    return _db().cursor()


def _columns(table: str) -> set[str]:
    if table in _COL_CACHE:
        return _COL_CACHE[table]
    found = set()
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            """,
            (table,),
        )
        for row in cur.fetchall() or []:
            name = row.get("COLUMN_NAME") or row.get("column_name")
            if name:
                found.add(name)
    except Exception as exc:
        print(f"bot office columns {table}: {exc}")
    _COL_CACHE[table] = found
    return found


def _missing(table: str):
    if _columns(table):
        return None
    return _fail(f"The {table.replace('_', ' ')} desk is not on this church yet.", 404)


def _secret(body) -> dict | None:
    if not isinstance(body, dict):
        return _fail("Send a JSON body.")
    for key in body:
        if str(key).lower() in SECRET_FIELDS:
            return _fail("That field is not on this bot.")
    return None


def _money(value):
    text = str(value if value is not None else "").strip().replace(",", "")
    if not text:
        return None
    try:
        amount = round(float(text), 2)
    except (TypeError, ValueError):
        return None
    if amount <= 0 or amount > 1000000:
        return None
    return amount


def _role(value, default="member") -> tuple[str | None, str | None]:
    role = (value or default).strip().lower()
    if role not in GROUP_ROLES:
        return None, "Role is member or leader."
    return role, None


def _truthy(value) -> bool:
    return value in (True, 1, "1", "true", "True", "on", "yes")


def _clean_name(value) -> str | None:
    text = _clip(value, 80)
    if not text or any(mark in text for mark in ("%", "_", "\\")):
        return None
    return text


def _find_user(body: dict):
    cur = _cur()
    uid = _int_or_none(body.get("user_id"))
    if uid:
        cur.execute(
            "SELECT id, username, first_name, last_name, role FROM users WHERE id=%s",
            (uid,),
        )
        return cur.fetchone()
    name = _clean_name(body.get("username") or body.get("user"))
    if not name:
        return None
    cur.execute(
        "SELECT id, username, first_name, last_name, role FROM users WHERE username=%s",
        (name,),
    )
    return cur.fetchone()


def _person(row: dict | None) -> dict:
    return _plain(row, ("id", "username", "first_name", "last_name", "role"))


def _membership(group_id: int, user_id: int):
    cur = _cur()
    cur.execute(
        """
        SELECT user_id, group_id, role_in_group
        FROM user_groups
        WHERE group_id=%s AND user_id=%s
        """,
        (int(group_id), int(user_id)),
    )
    return cur.fetchone()


def _insert_member(group_id: int, user_id: int, role: str, actor_id: int) -> None:
    cur = _cur()
    try:
        cur.execute(
            """
            INSERT INTO user_groups (user_id, group_id, role_in_group, assigned_by)
            VALUES (%s, %s, %s, %s)
            """,
            (int(user_id), int(group_id), role, int(actor_id)),
        )
    except IntegrityError:
        cur.execute(
            """
            UPDATE user_groups SET role_in_group=%s
            WHERE group_id=%s AND user_id=%s
            """,
            (role, int(group_id), int(user_id)),
        )


def _delete_member(group_id: int, user_id: int) -> None:
    cur = _cur()
    cur.execute(
        "DELETE FROM user_groups WHERE group_id=%s AND user_id=%s",
        (int(group_id), int(user_id)),
    )


def _group(group_id: int):
    if not _columns("groups"):
        return None
    fields = ["id", "name"]
    for extra in ("visibility", "system_key"):
        if extra in _columns("groups"):
            fields.append(extra)
    cur = _cur()
    cur.execute(
        f"SELECT {', '.join(fields)} FROM groups WHERE id=%s",
        (int(group_id),),
    )
    return cur.fetchone()


def _members(group_id: int) -> list[dict]:
    cur = _cur()
    cur.execute(
        """
        SELECT u.id, u.username, u.first_name, u.last_name, ug.role_in_group
        FROM user_groups ug
        JOIN users u ON u.id = ug.user_id
        WHERE ug.group_id=%s
        ORDER BY u.last_name, u.first_name, u.id
        """,
        (int(group_id),),
    )
    return [
        _plain(row, ("id", "username", "first_name", "last_name", "role_in_group"))
        for row in (cur.fetchall() or [])
    ]


def list_groups():
    missing = _missing("groups")
    if missing:
        return missing
    try:
        fields = ["id", "name"]
        for extra in ("visibility", "system_key"):
            if extra in _columns("groups"):
                fields.append(extra)
        cur = _cur()
        cur.execute(f"SELECT {', '.join(fields)} FROM groups ORDER BY name ASC, id ASC")
        rows = []
        for row in cur.fetchall() or []:
            item = _plain(row, tuple(fields))
            item["members"] = _members(int(row["id"]))
            rows.append(item)
        return _ok({"groups": rows, "count": len(rows)})
    except Exception as exc:
        print(f"bot office groups: {exc}")
        return _fail("The group list did not open.", 500)


def group_detail(group_id: int):
    try:
        row = _group(group_id)
    except Exception as exc:
        print(f"bot office group: {exc}")
        return _fail("That group did not open.", 500)
    if not row:
        return _fail("That group was not found.", 404)
    data = _plain(row)
    data["members"] = _members(int(row["id"]))
    return _ok(data)


def set_member(actor_id: int, group_id: int, body: dict):
    blocked = _secret(body)
    if blocked:
        return blocked
    try:
        group = _group(group_id)
        if not group:
            return _fail("That group was not found.", 404)
        user = _find_user(body)
        if not user:
            return _fail("Name that person with user_id or username.")
        prior = _membership(int(group["id"]), int(user["id"]))
        if _truthy(body.get("remove")):
            if not prior:
                return _fail("That person is not in the group.")
            _delete_member(int(group["id"]), int(user["id"]))
            return _ok(
                {"group_id": int(group["id"]), "user_id": int(user["id"]), "removed": True},
                {
                    "action": "group.remove",
                    "detail": f"Removed {user.get('username') or user['id']} from {group.get('name')}",
                    "target_type": "user_group",
                    "target_id": int(group["id"]),
                    "snapshot": {
                        "group_id": int(group["id"]),
                        "user_id": int(user["id"]),
                        "role_in_group": prior.get("role_in_group") or "member",
                        "actor_id": int(actor_id),
                    },
                },
            )
        role, err = _role(body.get("role"), "member")
        if err:
            return _fail(err)
        if prior and (prior.get("role_in_group") or "member") == role:
            return _ok({
                "group_id": int(group["id"]),
                "user_id": int(user["id"]),
                "role": role,
                "unchanged": True,
            })
        _insert_member(int(group["id"]), int(user["id"]), role, actor_id)
        action = "group.role" if prior else "group.add"
        return _ok(
            {"group_id": int(group["id"]), "user_id": int(user["id"]), "role": role},
            {
                "action": action,
                "detail": f"{user.get('username') or user['id']} is {role} in {group.get('name')}",
                "target_type": "user_group",
                "target_id": int(group["id"]),
                "snapshot": {
                    "group_id": int(group["id"]),
                    "user_id": int(user["id"]),
                    "before": prior.get("role_in_group") if prior else None,
                    "after": role,
                    "actor_id": int(actor_id),
                },
            },
        )
    except Exception as exc:
        print(f"bot office member: {exc}")
        return _fail("That membership did not save.", 500)


def _worship_group():
    if "system_key" not in _columns("groups"):
        cur = _cur()
        cur.execute("SELECT id, name FROM groups WHERE name=%s LIMIT 1", (WORSHIP_GROUP_NAME,))
        return cur.fetchone()
    cur = _cur()
    cur.execute(
        """
        SELECT id, name, system_key FROM groups
        WHERE system_key=%s OR name=%s
        ORDER BY (system_key=%s) DESC, id ASC
        LIMIT 1
        """,
        ("worship_team", WORSHIP_GROUP_NAME, "worship_team"),
    )
    return cur.fetchone()


def worship_team():
    try:
        group = _worship_group()
        if not group:
            return _fail("The worship team group was not found.", 404)
        members = _members(int(group["id"]))
        leaders = [row for row in members if row.get("role_in_group") == "leader"]
        defaults = _default_rows()
        return _ok({
            "group_id": int(group["id"]),
            "name": group.get("name"),
            "leaders": leaders,
            "members": members,
            "defaults": defaults,
            "note": "Leaders are people with the leader role in this group. An owner is not listed unless they have that role.",
        })
    except Exception as exc:
        print(f"bot office worship team: {exc}")
        return _fail("The worship team did not open.", 500)


def set_worship_role(actor_id: int, body: dict):
    blocked = _secret(body)
    if blocked:
        return blocked
    try:
        group = _worship_group()
        if not group:
            return _fail("The worship team group was not found.", 404)
        body = dict(body)
        body["remove"] = False
        result = set_member(actor_id, int(group["id"]), body)
        if not result.get("ok"):
            return result
        log = result.get("log")
        if log:
            if log.get("action") == "group.add":
                log["action"] = "worship.role"
            elif log.get("action") == "group.role":
                log["action"] = "worship.role"
            log["target_type"] = "worship_team"
        data = result.setdefault("data", {})
        data["worship"] = True
        return result
    except Exception as exc:
        print(f"bot office worship role: {exc}")
        return _fail("That worship role did not save.", 500)


def list_songs():
    missing = _missing("worship_songs")
    if missing:
        return missing
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT id, title, artist
            FROM worship_songs
            ORDER BY title ASC, id ASC
            LIMIT 100
            """
        )
        rows = [_plain(row, ("id", "title", "artist")) for row in (cur.fetchall() or [])]
        return _ok({"songs": rows, "count": len(rows)})
    except Exception as exc:
        print(f"bot office songs: {exc}")
        return _fail("The song list did not open.", 500)


def save_song(actor_id: int, body: dict):
    blocked = _secret(body)
    if blocked:
        return blocked
    title = _clip(body.get("title"), 255)
    if not title:
        return _fail("A song needs a title.")
    artist = _clip(body.get("artist"), 255)
    song_id = _int_or_none(body.get("id") or body.get("song_id"))
    try:
        cur = _cur()
        if song_id:
            cur.execute("SELECT id, title, artist FROM worship_songs WHERE id=%s", (song_id,))
            row = cur.fetchone()
            if not row:
                return _fail("That song was not found.", 404)
            cur.execute(
                "UPDATE worship_songs SET title=%s, artist=%s, updated_by=%s WHERE id=%s",
                (title, artist, int(actor_id), song_id),
            )
            return _ok(
                {
                    "song_id": song_id,
                    "title": title,
                    "artist": artist,
                    "note": "The title and artist were saved. The bot does not delete songs.",
                },
                {
                    "action": "worship.song",
                    "detail": f"Song {title}",
                    "target_type": "worship_song",
                    "target_id": song_id,
                    "snapshot": {"song_id": song_id},
                },
            )
        cur.execute(
            """
            INSERT INTO worship_songs (title, artist, sections_json, created_by, updated_by)
            VALUES (%s, %s, '[]', %s, %s)
            """,
            (title, artist, int(actor_id), int(actor_id)),
        )
        song_id = int(cur.lastrowid)
        return _ok(
            {
                "song_id": song_id,
                "title": title,
                "artist": artist,
                "note": "The song was added. The bot does not delete songs.",
            },
            {
                "action": "worship.song",
                "detail": f"Song {title}",
                "target_type": "worship_song",
                "target_id": song_id,
                "snapshot": {"song_id": song_id},
            },
        )
    except Exception as exc:
        print(f"bot office song save: {exc}")
        return _fail("That song did not save.", 500)


def _default_rows() -> list[dict]:
    cols = _columns("worship_default_assignments")
    if not cols:
        return []
    guest = ", guest_name" if "guest_name" in cols else ""
    cur = _cur()
    cur.execute(
        f"""
        SELECT role_name, user_id{guest}
        FROM worship_default_assignments
        ORDER BY role_name ASC
        """
    )
    return [
        _plain(row, ("role_name", "user_id", "guest_name"))
        for row in (cur.fetchall() or [])
    ]


def _write_defaults(rows: list[dict]) -> None:
    db = _db()
    db.autocommit(False)
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM worship_default_assignments")
        for row in rows:
            role = _clip(row.get("role_name"), 120)
            if not role:
                continue
            uid = _int_or_none(row.get("user_id"))
            guest = None if uid else _clip(row.get("guest_name"), 160)
            if "guest_name" in _columns("worship_default_assignments"):
                cur.execute(
                    """
                    INSERT INTO worship_default_assignments (role_name, user_id, guest_name)
                    VALUES (%s, %s, %s)
                    """,
                    (role, uid, guest),
                )
            else:
                cur.execute(
                    "INSERT INTO worship_default_assignments (role_name, user_id) VALUES (%s, %s)",
                    (role, uid),
                )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.autocommit(True)


def list_defaults():
    missing = _missing("worship_default_assignments")
    if missing:
        return missing
    try:
        rows = _default_rows()
        return _ok({"roles": rows, "count": len(rows)})
    except Exception as exc:
        print(f"bot office defaults: {exc}")
        return _fail("Worship defaults did not open.", 500)


def save_defaults(actor_id: int, body: dict):
    del actor_id
    blocked = _secret(body)
    if blocked:
        return blocked
    incoming = body.get("roles") if isinstance(body.get("roles"), list) else body.get("assignments")
    if not isinstance(incoming, list) or not incoming:
        return _fail("Send roles as a list of role_name and user_id.")
    try:
        before = _default_rows()
        cleaned = []
        for row in incoming:
            if not isinstance(row, dict):
                continue
            role = _clip(row.get("role_name"), 120)
            if not role:
                continue
            cleaned.append({
                "role_name": role,
                "user_id": _int_or_none(row.get("user_id")),
                "guest_name": _clip(row.get("guest_name"), 160),
            })
        if not cleaned:
            return _fail("Each role needs a role_name.")
        _write_defaults(cleaned)
        after = _default_rows()
        return _ok(
            {"roles": after, "count": len(after)},
            {
                "action": "worship.defaults",
                "detail": "Worship defaults saved",
                "target_type": "worship_defaults",
                "snapshot": {"before": before, "after": after},
            },
        )
    except Exception as exc:
        print(f"bot office save defaults: {exc}")
        return _fail("Worship defaults did not save.", 500)


def record_donation(actor_id: int, body: dict):
    del actor_id
    blocked = _secret(body)
    if blocked:
        return blocked
    missing = _missing("donations")
    if missing:
        return missing
    name = _clip(body.get("name"), 255)
    amount = _money(body.get("amount"))
    day, date_err = _parse_date(body.get("date"), required=True)
    method = _clip(body.get("method"), 40)
    notes = _clip(body.get("notes"), 500)
    if not name or amount is None or date_err or not method:
        return _fail(date_err or "A gift needs a name, a positive amount, a date, and a method.")
    try:
        cur = _cur()
        cur.execute(
            """
            INSERT INTO donations (name, amount, date, method, notes)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (name, amount, day, method, notes),
        )
        return _ok(
            {
                "donation_id": int(cur.lastrowid),
                "name": name,
                "amount": amount,
                "date": day,
                "method": method,
                "note": "The gift is recorded. Reverse does not void it.",
            },
            {
                "action": "donation.create",
                "detail": f"Gift {amount} from {name}",
                "target_type": "donation",
                "target_id": int(cur.lastrowid),
                "snapshot": {"donation_id": int(cur.lastrowid)},
            },
        )
    except Exception as exc:
        print(f"bot office donation: {exc}")
        return _fail("That gift did not save.", 500)


def update_bill(actor_id: int, bill_id: int, body: dict):
    blocked = _secret(body)
    if blocked:
        return blocked
    missing = _missing("recurring_bills")
    if missing:
        return missing
    fields = {}
    if "typical_amount" in body:
        amount = _money(body.get("typical_amount"))
        if amount is None:
            return _fail("The amount has to be a positive number.")
        fields["typical_amount"] = amount
    if "current_status" in body:
        status = (body.get("current_status") or "").strip().lower()
        if status not in BILL_STATUSES:
            return _fail("Status is pending, paid, overdue, or partial.")
        fields["current_status"] = status
    if "next_due_date" in body:
        day, err = _parse_date(body.get("next_due_date"), required=True)
        if err:
            return _fail(err)
        fields["next_due_date"] = day
    if "notes" in body:
        fields["notes"] = _clip(body.get("notes"), 2000) or ""
    if not fields:
        return _fail("Send an amount, status, due date, or notes. Account numbers and logins stay off.")
    safe = ("id", "bill_name", "vendor_name", "typical_amount", "frequency", "next_due_date", "current_status", "notes")
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT id, bill_name, vendor_name, typical_amount, frequency,
                   next_due_date, current_status, notes
            FROM recurring_bills WHERE id=%s
            """,
            (int(bill_id),),
        )
        row = cur.fetchone()
        if not row:
            return _fail("That bill was not found.", 404)
        before = _plain(row, safe)
        sets = ", ".join(f"{name}=%s" for name in fields)
        params = list(fields.values())
        if "updated_by" in _columns("recurring_bills"):
            sets += ", updated_by=%s"
            params.append(int(actor_id))
        params.append(int(bill_id))
        cur.execute(f"UPDATE recurring_bills SET {sets} WHERE id=%s", params)
        cur.execute(
            """
            SELECT id, bill_name, vendor_name, typical_amount, frequency,
                   next_due_date, current_status, notes
            FROM recurring_bills WHERE id=%s
            """,
            (int(bill_id),),
        )
        after = _plain(cur.fetchone(), safe)
        return _ok(
            after,
            {
                "action": "bill.update",
                "detail": f"Bill {before.get('bill_name') or bill_id} updated",
                "target_type": "recurring_bill",
                "target_id": int(bill_id),
                "snapshot": {"bill_id": int(bill_id), "before": before, "after": after},
            },
        )
    except Exception as exc:
        print(f"bot office bill: {exc}")
        return _fail("That bill did not save.", 500)


def accounting_overview():
    try:
        accounts = []
        expenses = []
        budgets = []
        if _columns("acct_accounts"):
            cur = _cur()
            cur.execute(
                """
                SELECT id, code, name, account_type, is_active
                FROM acct_accounts
                ORDER BY code ASC
                LIMIT 100
                """
            )
            accounts = [
                _plain(row, ("id", "code", "name", "account_type", "is_active"))
                for row in (cur.fetchall() or [])
            ]
        if _columns("acct_expenses"):
            cur = _cur()
            cur.execute(
                """
                SELECT id, expense_date, vendor_name, amount, description, status
                FROM acct_expenses
                ORDER BY id DESC
                LIMIT 40
                """
            )
            expenses = [
                _plain(row, ("id", "expense_date", "vendor_name", "amount", "description", "status"))
                for row in (cur.fetchall() or [])
            ]
        if _columns("acct_budgets"):
            cur = _cur()
            cur.execute(
                """
                SELECT id, name, fiscal_year, status
                FROM acct_budgets
                ORDER BY id DESC
                LIMIT 20
                """
            )
            budgets = [
                _plain(row, ("id", "name", "fiscal_year", "status"))
                for row in (cur.fetchall() or [])
            ]
        return _ok({
            "accounts": accounts,
            "expenses": expenses,
            "budgets": budgets,
            "note": "Payroll, bank details, and tax ids are not on this bot.",
        })
    except Exception as exc:
        print(f"bot office accounting: {exc}")
        return _fail("Accounting did not open.", 500)


def record_expense(actor_id: int, body: dict):
    blocked = _secret(body)
    if blocked:
        return blocked
    missing = _missing("acct_expenses")
    if missing:
        return missing
    day, err = _parse_date(body.get("expense_date") or body.get("date"), required=True)
    amount = _money(body.get("amount"))
    account_id = _int_or_none(body.get("expense_account_id"))
    if err or amount is None or not account_id:
        return _fail(err or "An expense needs a date, a positive amount, and expense_account_id.")
    vendor = _clip(body.get("vendor_name"), 255)
    description = _clip(body.get("description"), 500)
    try:
        cur = _cur()
        cur.execute(
            "SELECT id FROM acct_accounts WHERE id=%s AND is_active=1",
            (account_id,),
        )
        if not cur.fetchone():
            return _fail("That expense account was not found.", 404)
        cur.execute(
            """
            INSERT INTO acct_expenses
                (expense_date, vendor_name, amount, expense_account_id, description, status, created_by)
            VALUES (%s, %s, %s, %s, %s, 'posted', %s)
            """,
            (day, vendor, amount, account_id, description, int(actor_id)),
        )
        expense_id = int(cur.lastrowid)
        return _ok(
            {
                "expense_id": expense_id,
                "expense_date": day,
                "amount": amount,
                "vendor_name": vendor,
                "expense_account_id": account_id,
                "note": "The expense is recorded. Reverse does not void it.",
            },
            {
                "action": "expense.create",
                "detail": f"Expense {amount}",
                "target_type": "acct_expense",
                "target_id": expense_id,
                "snapshot": {"expense_id": expense_id},
            },
        )
    except Exception as exc:
        print(f"bot office expense: {exc}")
        return _fail("That expense did not save.", 500)


def inventory_overview():
    try:
        items = []
        locations = []
        if _columns("items"):
            cur = _cur()
            stock = ""
            group = "i.id, i.name, i.unit_of_measure, i.min_stock_level"
            if _columns("inventory_batches"):
                stock = ", COALESCE(SUM(b.quantity_on_hand), 0) AS on_hand"
                cur.execute(
                    f"""
                    SELECT i.id, i.name, i.unit_of_measure, i.min_stock_level {stock}
                    FROM items i
                    LEFT JOIN inventory_batches b ON b.item_id = i.id
                    GROUP BY {group}
                    ORDER BY i.name ASC
                    LIMIT 100
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT id, name, unit_of_measure, min_stock_level
                    FROM items
                    ORDER BY name ASC
                    LIMIT 100
                    """
                )
            items = [
                _plain(row, ("id", "name", "unit_of_measure", "min_stock_level", "on_hand"))
                for row in (cur.fetchall() or [])
            ]
        if _columns("locations"):
            cur = _cur()
            cur.execute("SELECT id, name FROM locations ORDER BY name ASC LIMIT 100")
            locations = [_plain(row, ("id", "name")) for row in (cur.fetchall() or [])]
        return _ok({"items": items, "locations": locations})
    except Exception as exc:
        print(f"bot office inventory: {exc}")
        return _fail("Inventory did not open.", 500)


def adjust_inventory(actor_id: int, body: dict):
    blocked = _secret(body)
    if blocked:
        return blocked
    if not _columns("inventory_batches"):
        return _fail("Stock batches are not on this church yet.", 404)
    item_id = _int_or_none(body.get("item_id"))
    location_id = _int_or_none(body.get("location_id"))
    try:
        change = int(body.get("quantity_change"))
    except (TypeError, ValueError):
        change = 0
    if not item_id or not location_id or change == 0 or abs(change) > 100000:
        return _fail("Send item_id, location_id, and a quantity_change other than zero.")
    notes = _clip(body.get("notes"), 500)
    try:
        cur = _cur()
        cur.execute("SELECT id, name FROM items WHERE id=%s", (item_id,))
        item = cur.fetchone()
        if not item:
            return _fail("That item was not found.", 404)
        cur.execute("SELECT id FROM locations WHERE id=%s", (location_id,))
        if not cur.fetchone():
            return _fail("That location was not found.", 404)
        cur.execute(
            """
            SELECT id, quantity_on_hand FROM inventory_batches
            WHERE item_id=%s AND location_id=%s
            ORDER BY id ASC LIMIT 1
            """,
            (item_id, location_id),
        )
        batch = cur.fetchone()
        if not batch:
            if change < 0:
                return _fail("There is no stock there to take from.")
            cur.execute(
                """
                INSERT INTO inventory_batches (item_id, location_id, quantity_on_hand)
                VALUES (%s, %s, 0)
                """,
                (item_id, location_id),
            )
            batch = {"id": int(cur.lastrowid), "quantity_on_hand": 0}
        before = int(batch.get("quantity_on_hand") or 0)
        after = before + change
        if after < 0:
            return _fail("That would take the stock below zero.")
        cur.execute(
            "UPDATE inventory_batches SET quantity_on_hand=%s WHERE id=%s",
            (after, int(batch["id"])),
        )
        if _columns("inventory_transactions"):
            kind = "receive" if change > 0 else "use"
            cur.execute(
                """
                INSERT INTO inventory_transactions
                    (batch_id, transaction_type, quantity_change, user_id, notes)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (int(batch["id"]), kind, change, int(actor_id), notes),
            )
        return _ok(
            {
                "item_id": item_id,
                "location_id": location_id,
                "before": before,
                "on_hand": after,
            },
            {
                "action": "inventory.adjust",
                "detail": f"{item.get('name') or item_id} stock {before} to {after}",
                "target_type": "inventory_batch",
                "target_id": int(batch["id"]),
                "snapshot": {"batch_id": int(batch["id"]), "before": before, "after": after},
            },
        )
    except Exception as exc:
        print(f"bot office stock: {exc}")
        return _fail("That stock change did not save.", 500)


def record_attendance(actor_id: int, body: dict):
    blocked = _secret(body)
    if blocked:
        return blocked
    missing = _missing("attendance")
    if missing:
        return missing
    day, err = _parse_date(body.get("service_date") or body.get("date"), required=True)
    if err:
        return _fail(err)
    try:
        user = _find_user(body)
        if not user:
            return _fail("Name that person with user_id or username.")
        notes = _clip(body.get("notes"), 500)
        cur = _cur()
        cur.execute(
            """
            INSERT INTO attendance (user_id, service_date, notes, checked_in_by)
            VALUES (%s, %s, %s, %s)
            """,
            (int(user["id"]), day, notes, int(actor_id)),
        )
        return _ok(
            {
                "attendance_id": int(cur.lastrowid),
                "user_id": int(user["id"]),
                "service_date": day,
            },
            {
                "action": "attendance.checkin",
                "detail": f"Checked in {user.get('username') or user['id']} on {day}",
                "target_type": "attendance",
                "target_id": int(cur.lastrowid),
                "snapshot": {
                    "user_id": int(user["id"]),
                    "service_date": day,
                    "notes": notes,
                    "checked_in_by": int(actor_id),
                },
            },
        )
    except IntegrityError:
        return _fail("That person is already checked in on that date.")
    except Exception as exc:
        print(f"bot office attendance: {exc}")
        return _fail("That check-in did not save.", 500)


def _set_role(snapshot: dict, role: str | None, actor_fallback: int) -> tuple[bool, str]:
    group_id = snapshot.get("group_id")
    user_id = snapshot.get("user_id")
    if not group_id or not user_id:
        return False, "That entry has no membership to put back."
    if not role:
        _delete_member(int(group_id), int(user_id))
        return True, "Removed that person from the group."
    _insert_member(int(group_id), int(user_id), role, int(snapshot.get("actor_id") or actor_fallback))
    return True, "Put that group role back."


def _bill_side(plan: str, snapshot: dict) -> tuple[bool, str]:
    bill_id = snapshot.get("bill_id")
    side = snapshot.get("before" if plan == "restore" else "after") or {}
    if not bill_id or not isinstance(side, dict):
        return False, "That entry has no bill to put back."
    allowed = ("typical_amount", "current_status", "next_due_date", "notes")
    fields = {key: side.get(key) for key in allowed if key in side}
    if not fields:
        return False, "That entry has no bill fields to put back."
    sets = ", ".join(f"{name}=%s" for name in fields)
    params = list(fields.values()) + [int(bill_id)]
    cur = _cur()
    cur.execute(f"UPDATE recurring_bills SET {sets} WHERE id=%s", params)
    return True, "Put the bill back."


def apply_undo(plan: str, entry: dict) -> tuple[bool, str]:
    """Put back one office change. Gifts and expenses stay on the books."""
    action = (entry or {}).get("action") or ""
    snapshot = entry.get("snapshot") or {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    try:
        if action in ("group.add", "group.role", "worship.role"):
            role = snapshot.get("before") if plan == "restore" else snapshot.get("after")
            return _set_role(snapshot, role, 1)
        if action == "group.remove":
            if plan == "restore":
                return _set_role(snapshot, snapshot.get("role_in_group") or "member", 1)
            _delete_member(int(snapshot["group_id"]), int(snapshot["user_id"]))
            return True, "Removed that person from the group again."
        if action == "worship.defaults":
            rows = snapshot.get("before" if plan == "restore" else "after") or []
            if not isinstance(rows, list):
                return False, "That entry has no worship defaults to put back."
            _write_defaults(rows)
            return True, "Put the worship defaults back."
        if action == "bill.update":
            return _bill_side(plan, snapshot)
        if action == "inventory.adjust":
            batch_id = snapshot.get("batch_id")
            qty = snapshot.get("before" if plan == "restore" else "after")
            if not batch_id or qty is None:
                return False, "That entry has no stock count to put back."
            cur = _cur()
            cur.execute(
                "UPDATE inventory_batches SET quantity_on_hand=%s WHERE id=%s",
                (int(qty), int(batch_id)),
            )
            return True, "Put the stock count back."
        if action == "attendance.checkin":
            user_id = snapshot.get("user_id")
            day = snapshot.get("service_date")
            if not user_id or not day:
                return False, "That entry has no check-in to put back."
            cur = _cur()
            if plan == "restore":
                cur.execute(
                    "DELETE FROM attendance WHERE user_id=%s AND service_date=%s",
                    (int(user_id), day),
                )
                return True, "Removed that check-in."
            cur.execute(
                """
                INSERT INTO attendance (user_id, service_date, notes, checked_in_by)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    int(user_id),
                    day,
                    snapshot.get("notes"),
                    int(snapshot.get("checked_in_by") or 1),
                ),
            )
            return True, "Checked that person in again."
    except Exception as exc:
        print(f"bot office undo {action}: {exc}")
        return False, "That office change could not be reversed."
    return False, "That entry cannot be reversed."
