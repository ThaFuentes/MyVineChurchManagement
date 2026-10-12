"""Full records for every church desk the office key may open.

Each desk is the real table, with every column except secrets. List, open,
create, and update use those columns. This does not hard-delete content.
Link rows (a follow, a permission, a campus membership) can be removed
because that is how those tables work, and undo puts the link back.

Mail passwords, API keys, payment secrets, private messages, and payroll
are not desks. Child check-in is a desk, without PINs or pickup codes.
"""

from __future__ import annotations

import json
import re

from pymysql.err import IntegrityError

from app.utils.bot_sermon_common import _db, _fail, _like, _limit, _ok, _plain

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_PARTS = (
    "password",
    "passwd",
    "checkin_pin",
    "secret",
    "token",
    "encrypted",
    "account_number",
    "customer_number",
    "card_number",
    "cvv",
    "cvc",
    "routing",
    "tax_id",
    "api_key",
    "twofa",
    "session_hash",
    "key_hash",
    "private_key",
    "shadow_ip",
    "ip_address",
    "smtp",
    "body_enc",
    "login_url",
    "payment_url",
    "bank",
)
# Exact names. "pin" as a fragment would also hide pinned_by.
_EXACT_SECRETS = (
    "pin_code",
    "family_pin",
    "pickup_code",
    "security_code",
)
_SEARCH_NAMES = (
    "name",
    "title",
    "username",
    "first_name",
    "last_name",
    "email",
    "bill_name",
    "event_name",
    "vendor_name",
    "role_name",
    "code",
)
# A hide stores the hidden value. Undo writes the previous value back.
_HIDE_ON = {
    "removed_at": "NOW()",
    "moderation_hidden": 1,
    "is_active": 0,
    "active": 0,
    "is_hidden": 1,
}
_COL_CACHE: dict[str, list[str]] = {}


def _desk(area_id, group, table, *, keys=None, read_only=False, link=False, keep_ips=False, own=None):
    return {
        "id": area_id,
        "group": group,
        "table": table,
        "keys": keys,
        "read_only": read_only,
        "link": link,
        "keep_ips": keep_ips,
        "own": own,
    }


def _bundle(group, tables, **flags):
    rows = []
    for table in tables:
        local = dict(flags)
        keys = None
        name = table
        if isinstance(table, tuple):
            name = table[0]
            if len(table) > 1 and isinstance(table[1], (tuple, list)):
                keys = tuple(table[1])
            elif len(table) > 1 and isinstance(table[1], dict):
                local.update(table[1])
            if len(table) > 2 and isinstance(table[2], dict):
                local.update(table[2])
        rows.append(_desk(
            name,
            group,
            name,
            keys=keys,
            read_only=bool(local.get("read_only")),
            link=bool(local.get("link")),
            keep_ips=bool(local.get("keep_ips")),
            own=local.get("own"),
        ))
    return rows


# id is the table name. A tuple is (table, key columns) when there is no single id.
# A third dict sets link (the row may be removed and put back), keep_ips, or own.
_LINK = {"link": True}
DESKS = (
    _bundle("People", [
        "users", "member_roles", "groups", "campuses", "access_templates", "security_area_grants",
        ("family_relations", ("user_id", "relative_id"), _LINK),
        ("user_groups", ("user_id", "group_id"), _LINK),
        ("user_permissions", ("user_id", "permission_key"), _LINK),
        ("user_permission_blocks", ("user_id", "permission_key"), _LINK),
        ("campus_members", ("campus_id", "user_id"), _LINK),
        ("campus_staff", ("campus_id", "user_id"), _LINK),
        ("campus_follows", ("user_id", "campus_id"), _LINK),
        ("member_privacy", ("user_id",)),
        ("member_privacy_branches", ("user_id", "campus_id"), _LINK),
        ("user_follows", ("follower_id", "followed_id"), _LINK),
        ("user_blocks", ("blocker_id", "blocked_id"), _LINK),
        ("user_widgets", None, {"link": True, "own": "user_id"}),
    ])
    + _bundle("Church life", [
        "events", "event_comments",
        "announcements", "announcement_comments",
        "prayers", "prayers_added", "dreams", "dream_comments",
        "prophecies", "prophecy_comments", "sermons", "sermon_comments",
        "help_categories", "help_articles",
        "legal_categories", "legal_notices", "church_promotions",
        "custom_module_types", "custom_modules", "custom_module_records",
        ("potluck_signups", None, _LINK),
        ("event_registrations", None, _LINK),
        ("user_help_pins", None, _LINK),
    ])
    + _bundle("Pastoral", [
        "pastoral_sermons", "sermon_sections", "illustration_library", "pastoral_vault",
        "sermon_templates", "service_templates", "service_plans",
        "pastoral_care_requests", "pastoral_care_notes", "pastoral_rites",
        ("sermon_collaborators", ("sermon_id", "user_id"), _LINK),
        ("service_template_assignments", None, _LINK),
        ("service_plan_assignments", None, _LINK),
        ("default_service_plan_assignments", None, _LINK),
        ("pastoral_care_assignments", None, _LINK),
        ("pastoral_group_members", ("user_id",), _LINK),
    ])
    + _bundle("Pastoral", [
        "sermon_edits", "bible_books", "bible_verses", "strongs_occurrences",
        ("bible_translations", ("code",)),
        ("strongs_lexicon", ("number",)),
    ], read_only=True)
    + _bundle("Bible study", [
        ("bible_highlights", None, {"link": True, "own": "user_id"}),
        ("bible_notes", None, {"link": True, "own": "user_id"}),
        ("bible_favorites", None, {"link": True, "own": "user_id"}),
    ])
    + _bundle("Curriculum", [
        "curriculum_series", "curriculum_lessons", "curriculum_blocks",
        "curriculum_choices", "curriculum_progress",
        ("curriculum_enrollments", None, _LINK),
    ])
    + _bundle("Worship", [
        "worship_songs", "worship_rehearsal_templates", "worship_setlists",
        "worship_weekly_templates", "worship_member_notes", "worship_song_plays",
        "worship_song_charts", "worship_ccli_settings",
        ("worship_default_assignments", None, _LINK),
        ("worship_template_assignments", None, _LINK),
        ("worship_setlist_assignments", None, _LINK),
        ("worship_setlist_songs", None, _LINK),
        ("worship_weekly_template_songs", None, _LINK),
        ("worship_weekly_template_assignments", None, _LINK),
        ("worship_user_prefs", ("user_id",), {"own": "user_id"}),
        ("worship_user_chart_notes", None, {"link": True, "own": "user_id"}),
    ])
    + _bundle("Giving and bills", [
        "donations", "donation_recurring", "online_donation_options",
        "recurring_bills", "bill_payment_history",
        ("recurring_bill_assignments", None, _LINK),
    ])
    + _bundle("Accounting", [
        "acct_accounts", "acct_vendors", "acct_journal_entries", "acct_journal_lines",
        "acct_expenses", "acct_budgets", "acct_budget_lines",
    ])
    + _bundle("Inventory", [
        "categories", "vendors", "locations", "items",
        "inventory_batches", "inventory_transactions", "barcode_scans",
        ("item_kit_components", None, _LINK),
    ])
    + _bundle("Attendance", [("attendance", None, _LINK)])
    + _bundle("Child check-in", [
        "child_classrooms", "child_profiles", "child_guardians", "child_checkins",
    ])
    + _bundle("Tickets", [
        "ticket_categories", "tickets", "ticket_comments",
        ("ticket_managers", ("user_id",), _LINK),
    ])
    + _bundle("Volunteers", [
        "vol_skills", "vol_teams", "vol_roles", "vol_events",
        ("vol_person_skills", ("user_id", "skill_id"), _LINK),
        ("vol_team_members", None, _LINK),
        ("vol_assignments", None, _LINK),
        ("vol_rotations", None, _LINK),
    ])
    + _bundle("Community", [
        ("church_pages", ("campus_id",)),
        ("member_spaces", ("user_id",)),
        "page_links", "page_photos", "page_photo_comments",
        "community_posts", "community_post_comments", "member_badges",
        "content_flags", "notifications", "moderation_actions",
        ("content_reactions", ("content_type", "content_id", "user_id"), _LINK),
        ("content_shares", None, _LINK),
        ("content_posting", ("content_type", "content_id")),
        ("church_page_editors", ("campus_id", "user_id"), _LINK),
        ("page_pins", None, _LINK),
        ("user_notice_state", ("user_id",), {"own": "user_id"}),
    ])
    + _bundle("Site", [
        "site_hero_images", "site_welcome_features", "settings", "pwa_prompt_choices",
        ("banned_ips", ("ip_address",), {"link": True, "keep_ips": True}),
    ])
    + _bundle("Site", [
        "comm_campaigns", "comm_campaign_recipients", "comm_workflows",
        "comm_workflow_steps", "comm_workflow_enrollments",
        "comm_message_log", "change_records",
    ], read_only=True)
    + _bundle("Security", [
        ("pbt_security_events", None, {"read_only": True, "keep_ips": True}),
        ("pbt_traffic", None, {"read_only": True, "keep_ips": True}),
        ("pbt_device_prints", None, {"read_only": True, "keep_ips": True}),
        ("pbt_attack_stats", ("attack_type",), {"read_only": True, "keep_ips": True}),
        ("pbt_ip_geo", ("ip",), {"read_only": True, "keep_ips": True}),
        ("pbt_reputation", ("ip",), {"link": True, "keep_ips": True}),
        ("pbt_device_bans", ("device_fp",), _LINK),
    ])
)

_BY_ID = {row["id"]: row for row in DESKS}

# Not desks, on purpose. Tests lock this list.
CLOSED_TABLES = (
    "bot_access_keys",
    "bot_access_voices",
    "bot_access_log",
    "bot_admin_grants",
    "api_keys",
    "ai_providers",
    "app_email_settings",
    "church_email_settings",
    "email_accounts",
    "donation_email_mailbox",
    "donation_email_messages",
    "donation_payment_providers",
    "kiosk_sessions",
    "push_subscriptions",
    "dm_threads",
    "dm_messages",
    "dm_members",
    "acct_employees",
    "acct_pay_runs",
    "acct_pay_items",
    "maya_bot_settings",
    "maya_bot_permissions",
    "maya_bot_perm_log",
)


def desk_ids() -> list[str]:
    return [row["id"] for row in DESKS]


def secret_column(name: str) -> bool:
    """True when a column can hold a password, card, pin, address, or mail secret."""
    low = (name or "").lower()
    if low in _EXACT_SECRETS or low in ("ip", "pin") or low.endswith("_ip") or low.endswith("_enc"):
        return True
    return any(part in low for part in _SECRET_PARTS)


def _ip_only(name: str) -> bool:
    """An address column with no password or mail secret in the name."""
    low = (name or "").lower()
    if not (low in ("ip", "ip_address", "shadow_ip") or low.endswith("_ip")):
        return False
    ignored = {"ip_address", "shadow_ip"}
    return not any(part in low for part in _SECRET_PARTS if part not in ignored)


def _blocked_field(name: str, desk) -> bool:
    if not secret_column(name):
        return False
    if desk and desk.get("keep_ips") and _ip_only(name):
        return False
    return True


def safe_columns(names, *, keep_ips: bool = False) -> list[str]:
    out = []
    for name in names or []:
        if not name or not _IDENT.match(name):
            continue
        if secret_column(name) and not (keep_ips and _ip_only(name)):
            continue
        out.append(name)
    return out


def _cur():
    return _db().cursor()


def _columns(table: str) -> list[str]:
    if table in _COL_CACHE:
        return _COL_CACHE[table]
    found = []
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
            """,
            (table,),
        )
        for row in cur.fetchall() or []:
            name = row.get("COLUMN_NAME") or row.get("column_name")
            if name and _IDENT.match(name):
                found.append(name)
    except Exception as exc:
        print(f"bot desk columns {table}: {exc}")
    _COL_CACHE[table] = found
    return found


def _live_columns() -> dict[str, list[str]]:
    tables = [row["table"] for row in DESKS]
    marks = ",".join(["%s"] * len(tables))
    found: dict[str, list[str]] = {table: [] for table in tables}
    cur = _cur()
    cur.execute(
        f"""
        SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ({marks})
        ORDER BY ORDINAL_POSITION
        """,
        tables,
    )
    for row in cur.fetchall() or []:
        table = row.get("TABLE_NAME") or row.get("table_name")
        name = row.get("COLUMN_NAME") or row.get("column_name")
        if table in found and name and _IDENT.match(name):
            found[table].append(name)
            _COL_CACHE[table] = found[table]
    return found


def catalog():
    """Every desk and the columns that are actually on this church database."""
    from app.utils.bot_areas import covers
    try:
        live = _live_columns()
    except Exception as exc:
        print(f"bot desks catalog: {exc}")
        return _fail("The desk list did not open.", 500)
    areas = []
    for row in DESKS:
        cols = safe_columns(live.get(row["table"]) or [], keep_ips=row["keep_ips"])
        areas.append({
            "area": row["id"],
            "group": row["group"],
            "columns": cols,
            "key": list(row["keys"] or ("id",)),
            "read_only": row["read_only"],
            "link": row["link"],
            "own": row["own"],
            "present": bool(live.get(row["table"])),
        })
    groups = []
    for area in areas:
        if not groups or groups[-1]["name"] != area["group"]:
            groups.append({"name": area["group"], "areas": []})
        groups[-1]["areas"].append(area["area"])
    return _ok({
        "areas": areas,
        "groups": groups,
        "count": len(areas),
        "closed": list(CLOSED_TABLES),
        "covers": covers(),
        "note": "Send the columns named here. A missing table is present=false on this church. covers names the church areas.",
    })


def _find(area: str):
    row = _BY_ID.get((area or "").strip())
    if not row:
        return None, _fail("That desk is not on the bot. GET /api/bot/desks lists them.", 404)
    cols = _columns(row["table"])
    if not cols:
        return None, _fail("That desk is not on this church yet.", 404)
    safe = safe_columns(cols, keep_ips=row["keep_ips"])
    if not safe:
        return None, _fail("That desk has no columns this bot can use.", 404)
    return (row, safe), None


def _quote(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(name)
    return f"`{name}`"


def _cell(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value)[:200000]
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, str) and len(value) > 200000:
        return value[:200000]
    return value


def _where_id(row_id):
    return "`id`=%s", [int(row_id)]


def _key_where(desk, source):
    keys = desk.get("keys") or ()
    if not keys:
        return None, None, None
    missing = [key for key in keys if source.get(key) in (None, "")]
    if missing:
        return None, None, _fail("Send " + ", ".join(keys) + " for this desk.")
    clause = " AND ".join(f"{_quote(key)}=%s" for key in keys)
    params = [source.get(key) for key in keys]
    return clause, params, None


def _one(table, safe, clause, params):
    cur = _cur()
    cur.execute(
        f"SELECT {', '.join(_quote(name) for name in safe)} FROM {_quote(table)} WHERE {clause} LIMIT 1",
        params,
    )
    return cur.fetchone()


def _truthy(value) -> bool:
    return value in (True, 1, "1", "true", "True", "on", "yes")


def _hide_column(columns: list[str]) -> str | None:
    for name in _HIDE_ON:
        if name in columns:
            return name
    return None


def read_desk(area: str, args, actor_id: int | None = None):
    found, err = _find(area)
    if err:
        return err
    desk, safe = found
    own = desk.get("own")
    if own and actor_id in (None, ""):
        return _fail("That desk is for the account this bot acts as.", 403)
    try:
        clause = None
        params: list = []
        if desk.get("keys") and all(args.get(key) not in (None, "") for key in desk["keys"]):
            clause, params, key_err = _key_where(desk, args)
            if key_err:
                return key_err
        elif args.get("id") not in (None, ""):
            try:
                clause, params = _where_id(args.get("id"))
            except (TypeError, ValueError):
                return _fail("id has to be a number.")
        if clause:
            row = _one(desk["table"], safe, clause, params)
            if not row:
                return _fail("That record was not found.", 404)
            plain = _plain(row, tuple(safe))
            if own and str(plain.get(own)) != str(int(actor_id)):
                return _fail("That record was not found.", 404)
            return _ok({"area": desk["id"], "row": plain})
        filters = []
        filter_params = []
        for key in safe:
            if key in ("id",) or key in _SEARCH_NAMES:
                pass
            raw = args.get(key)
            if raw in (None, ""):
                continue
            filters.append(f"{_quote(key)}=%s")
            filter_params.append(_cell(raw) if not isinstance(raw, str) else raw[:500])
        if own:
            filters.append(f"{_quote(own)}=%s")
            filter_params.append(int(actor_id))
        query = (args.get("q") or "").strip()
        if query:
            names = [name for name in _SEARCH_NAMES if name in safe]
            if names:
                like = _like(query)
                filters.append("(" + " OR ".join(f"{_quote(name)} LIKE %s" for name in names) + ")")
                filter_params.extend([like] * len(names))
        where = (" WHERE " + " AND ".join(filters)) if filters else ""
        order = "`id` DESC" if "id" in safe else ", ".join(_quote(key) for key in (desk.get("keys") or safe[:1]))
        limit = _limit(args.get("limit"), 40)
        cur = _cur()
        cur.execute(
            f"SELECT {', '.join(_quote(name) for name in safe)} FROM {_quote(desk['table'])}{where} ORDER BY {order} LIMIT %s",
            filter_params + [limit],
        )
        rows = [_plain(row, tuple(safe)) for row in (cur.fetchall() or [])]
        return _ok({
            "area": desk["id"],
            "columns": safe,
            "rows": rows,
            "count": len(rows),
            "read_only": desk["read_only"],
        })
    except Exception as exc:
        print(f"bot desk read {area}: {exc}")
        return _fail("That desk did not open.", 500)


def _role_guard(actor_role, table, fields, current):
    if table != "users" or "role" not in fields:
        if table == "users" and current and (current.get("role") or "") == "Owner" and actor_role != "Owner":
            return "An admin bot cannot change an owner account."
        return None
    if str(fields.get("role") or "") == "Owner" and actor_role != "Owner":
        return "Only an owner bot can set the owner role."
    if current and (current.get("role") or "") == "Owner" and actor_role != "Owner":
        return "An admin bot cannot change an owner account."
    return None


def _stamp(columns, fields, actor_id, creating: bool):
    if creating and "created_by" in columns and "created_by" not in fields:
        fields["created_by"] = int(actor_id)
    if "updated_by" in columns and "updated_by" not in fields:
        fields["updated_by"] = int(actor_id)
    return fields


def _refuse_own(desk, actor_id, source, current=None):
    col = desk.get("own")
    if not col:
        return None
    if current is not None and str(current.get(col)) != str(int(actor_id)):
        return _fail("That record was not found.", 404)
    sent = source.get(col)
    if sent not in (None, "") and str(sent) != str(int(actor_id)):
        return _fail("This bot can only use its own rows on that desk.", 403)
    return None


def write_desk(actor_id: int, actor_role: str | None, area: str, body: dict):
    if not isinstance(body, dict):
        return _fail("Send a JSON body.")
    found, err = _find(area)
    if err:
        return err
    desk, safe = found
    if desk["read_only"]:
        return _fail("That desk is read-only.")
    raw_cols = _columns(desk["table"])
    fields = {}
    nested = body.get("fields") if isinstance(body.get("fields"), dict) else None
    source = dict(nested or {})
    source.update({key: value for key, value in body.items() if key != "fields"})
    owned = _refuse_own(desk, actor_id, source)
    if owned:
        return owned
    if desk.get("own") and source.get(desk["own"]) in (None, ""):
        source[desk["own"]] = int(actor_id)
    for key, value in source.items():
        if key in ("id", "hide", "fields", "remove"):
            continue
        if key in safe:
            fields[key] = _cell(value)
        elif _blocked_field(str(key), desk):
            return _fail("That field is not on this bot.")
    if desk.get("own") and desk["own"] in safe:
        fields[desk["own"]] = int(actor_id)
    try:
        if _truthy(source.get("remove")):
            return _remove_row(desk, safe, source, actor_id)
        if _truthy(source.get("hide")):
            return _hide(desk, safe, raw_cols, source, actor_id)
        if desk.get("keys"):
            return _write_link(desk, safe, raw_cols, fields, source, actor_id)
        return _write_row(desk, safe, raw_cols, fields, source, actor_id, actor_role)
    except IntegrityError:
        return _fail("That record is already there, or a required value is missing.")
    except Exception as exc:
        print(f"bot desk write {area}: {exc}")
        return _fail("That record did not save.", 500)


def _child_checkin_codes(table: str, raw_cols) -> dict:
    """The board needs a code. The bot never sees it or accepts one."""
    if table != "child_checkins":
        return {}
    import secrets
    filled = {}
    cols = set(raw_cols or [])
    if "pickup_code" in cols:
        filled["pickup_code"] = secrets.token_hex(4).upper()[:12]
    if "security_code" in cols:
        filled["security_code"] = secrets.token_hex(4).upper()[:12]
    return filled


def _write_row(desk, safe, raw_cols, fields, source, actor_id, actor_role):
    table = desk["table"]
    row_id = source.get("id")
    if row_id in (None, ""):
        if table == "users":
            return _fail("This bot cannot set a password, so it cannot open a new login. It can update every other profile field.")
        if not fields:
            return _fail("Send the columns to save.")
        fields = _stamp(raw_cols, fields, actor_id, True)
        if table == "child_checkins" and "checked_in_by" in set(raw_cols or []) and "checked_in_by" not in fields:
            fields["checked_in_by"] = int(actor_id)
        secret_fill = _child_checkin_codes(table, raw_cols)
        blocked = _role_guard(actor_role, table, fields, None)
        if blocked:
            return _fail(blocked, 403)
        names = list(fields) + list(secret_fill)
        cur = _cur()
        cur.execute(
            f"INSERT INTO {_quote(table)} ({', '.join(_quote(name) for name in names)}) VALUES ({', '.join(['%s'] * len(names))})",
            [fields[name] for name in fields] + [secret_fill[name] for name in secret_fill],
        )
        new_id = int(cur.lastrowid)
        saved = _one(table, safe, "`id`=%s", [new_id])
        if desk.get("link"):
            created_action = "desk.link"
        else:
            created_action = "desk.update" if _hide_column(raw_cols) else "desk.create"
        return _ok(
            {"area": desk["id"], "id": new_id, "row": _plain(saved, tuple(safe))},
            {
                "action": created_action,
                "detail": f"Created {desk['id']} {new_id}",
                "target_type": desk["id"][:40],
                "target_id": new_id,
                "snapshot": {
                    "table": table,
                    "id": new_id,
                    "before": None,
                    "after": _plain(saved, tuple(safe)),
                    "created": True,
                },
            },
        )
    try:
        row_id = int(row_id)
    except (TypeError, ValueError):
        return _fail("id has to be a number.")
    if not fields:
        return _fail("Send the columns to change.")
    current = _one(table, safe, "`id`=%s", [row_id])
    if not current:
        return _fail("That record was not found.", 404)
    owned = _refuse_own(desk, actor_id, source, current)
    if owned:
        return owned
    blocked = _role_guard(actor_role, table, fields, current)
    if blocked:
        return _fail(blocked, 403)
    fields = _stamp(raw_cols, fields, actor_id, False)
    before = {key: _plain(current, tuple(safe)).get(key) for key in fields}
    sets = ", ".join(f"{_quote(name)}=%s" for name in fields)
    cur = _cur()
    cur.execute(
        f"UPDATE {_quote(table)} SET {sets} WHERE `id`=%s",
        [fields[name] for name in fields] + [row_id],
    )
    saved = _one(table, safe, "`id`=%s", [row_id])
    after = {key: _plain(saved, tuple(safe)).get(key) for key in fields}
    return _ok(
        {"area": desk["id"], "id": row_id, "row": _plain(saved, tuple(safe))},
        {
            "action": "desk.update",
            "detail": f"Updated {desk['id']} {row_id}",
            "target_type": desk["id"][:40],
            "target_id": row_id,
            "snapshot": {
                "table": table,
                "id": row_id,
                "before": before,
                "after": after,
                "created": False,
            },
        },
    )


def _write_link(desk, safe, raw_cols, fields, source, actor_id):
    clause, params, key_err = _key_where(desk, source)
    if key_err:
        return key_err
    keys = list(desk["keys"])
    current = _one(desk["table"], safe, clause, params)
    if current:
        owned = _refuse_own(desk, actor_id, source, current)
        if owned:
            return owned
    writable = {key: value for key, value in fields.items() if key not in keys}
    if current and not writable:
        return _ok({"area": desk["id"], "row": _plain(current, tuple(safe)), "unchanged": True})
    if not current:
        insert = {key: source.get(key) for key in keys}
        insert.update(writable)
        insert = _stamp(raw_cols, insert, actor_id, True)
        names = list(insert)
        cur = _cur()
        cur.execute(
            f"INSERT INTO {_quote(desk['table'])} ({', '.join(_quote(name) for name in names)}) VALUES ({', '.join(['%s'] * len(names))})",
            [insert[name] for name in names],
        )
        saved = _one(desk["table"], safe, clause, params)
        return _ok(
            {"area": desk["id"], "row": _plain(saved, tuple(safe))},
            {
                "action": "desk.link",
                "detail": f"Added {desk['id']}",
                "target_type": desk["id"][:40],
                "snapshot": {
                    "table": desk["table"],
                    "keys": {key: source.get(key) for key in keys},
                    "before": None,
                    "after": _plain(saved, tuple(safe)),
                    "link": True,
                },
            },
        )
    before = {key: _plain(current, tuple(safe)).get(key) for key in writable}
    sets = ", ".join(f"{_quote(name)}=%s" for name in writable)
    cur = _cur()
    cur.execute(
        f"UPDATE {_quote(desk['table'])} SET {sets} WHERE {clause}",
        [writable[name] for name in writable] + params,
    )
    saved = _one(desk["table"], safe, clause, params)
    return _ok(
        {"area": desk["id"], "row": _plain(saved, tuple(safe))},
        {
            "action": "desk.update",
            "detail": f"Updated {desk['id']}",
            "target_type": desk["id"][:40],
            "snapshot": {
                "table": desk["table"],
                "keys": {key: source.get(key) for key in keys},
                "before": before,
                "after": {key: _plain(saved, tuple(safe)).get(key) for key in writable},
                "created": False,
            },
        },
    )


def _hide(desk, safe, raw_cols, source, actor_id):
    column = _hide_column(raw_cols)
    if not column or column not in safe:
        return _fail("This record has no hide column. The bot does not delete it.")
    if desk.get("keys"):
        clause, params, key_err = _key_where(desk, source)
        if key_err:
            return key_err
        ident = {"keys": {key: source.get(key) for key in desk["keys"]}}
    else:
        try:
            clause, params = _where_id(source.get("id"))
        except (TypeError, ValueError):
            return _fail("Send id to hide that record.")
        ident = {"id": int(source.get("id"))}
    current = _one(desk["table"], safe, clause, params)
    if not current:
        return _fail("That record was not found.", 404)
    owned = _refuse_own(desk, actor_id, source, current)
    if owned:
        return owned
    before = _plain(current, (column,)).get(column)
    hidden = _HIDE_ON[column]
    cur = _cur()
    if hidden == "NOW()":
        cur.execute(f"UPDATE {_quote(desk['table'])} SET {_quote(column)}=NOW() WHERE {clause}", params)
    else:
        cur.execute(
            f"UPDATE {_quote(desk['table'])} SET {_quote(column)}=%s WHERE {clause}",
            [hidden] + params,
        )
    saved = _one(desk["table"], safe, clause, params)
    return _ok(
        {"area": desk["id"], "row": _plain(saved, tuple(safe)), "hidden": True},
        {
            "action": "desk.hide",
            "detail": f"Hid {desk['id']}",
            "target_type": desk["id"][:40],
            "target_id": ident.get("id"),
            "snapshot": {
                "table": desk["table"],
                "column": column,
                "before": before,
                "after": _plain(saved, (column,)).get(column),
                **ident,
            },
        },
    )


def _remove_row(desk, safe, source, actor_id):
    """Drop a membership or assignment row. Undo inserts that same row again."""
    if not desk.get("link"):
        return _fail("This record stays. This bot does not delete it.")
    clause, params, err = _locate(desk, safe, source)
    if err:
        return err
    current = _one(desk["table"], safe, clause, params)
    if not current:
        return _fail("That record was not found.", 404)
    owned = _refuse_own(desk, actor_id, source, current)
    if owned:
        return owned
    plain = _plain(current, tuple(safe))
    cur = _cur()
    cur.execute(f"DELETE FROM {_quote(desk['table'])} WHERE {clause}", params)
    ident = {}
    if desk.get("keys") and all(source.get(key) not in (None, "") for key in desk["keys"]):
        ident["keys"] = {key: source.get(key) for key in desk["keys"]}
    elif plain.get("id") not in (None, ""):
        ident["id"] = plain.get("id")
    elif desk.get("keys"):
        ident["keys"] = {key: plain.get(key) for key in desk["keys"]}
    return _ok(
        {"area": desk["id"], "removed": True},
        {
            "action": "desk.link",
            "detail": f"Removed {desk['id']}",
            "target_type": desk["id"][:40],
            "target_id": ident.get("id"),
            "snapshot": {
                "table": desk["table"],
                "before": plain,
                "after": None,
                "link": True,
                **ident,
            },
        },
    )


def _locate(desk, safe, source):
    keys = desk.get("keys") or ()
    if keys and all(source.get(key) not in (None, "") for key in keys):
        return _key_where(desk, source)
    if source.get("id") not in (None, "") and (not keys or "id" in safe):
        try:
            clause, params = _where_id(source.get("id"))
        except (TypeError, ValueError):
            return None, None, _fail("id has to be a number.")
        return clause, params, None
    if keys:
        return _key_where(desk, source)
    return None, None, _fail("Send id for this record.")


def _set_fields(table, clause, params, fields):
    if not fields:
        return
    sets = ", ".join(f"{_quote(name)}=%s" for name in fields)
    cur = _cur()
    values = []
    for name in fields:
        if fields[name] == "NOW()":
            continue
        values.append(fields[name])
    # NOW() is not used on undo. Null clears removed_at.
    cur.execute(
        f"UPDATE {_quote(table)} SET {sets} WHERE {clause}",
        values + params,
    )


def apply_undo(plan: str, entry: dict) -> tuple[bool, str]:
    """Put a desk edit back. A brand-new content row is not deleted."""
    action = (entry or {}).get("action") or ""
    snapshot = entry.get("snapshot") or {}
    if not isinstance(snapshot, dict):
        return False, "That entry has nothing to put back."
    table = snapshot.get("table")
    if table not in {row["table"] for row in DESKS} or not _IDENT.match(table or ""):
        return False, "That entry is not a church desk."
    side_name = "before" if plan == "restore" else "after"
    try:
        if action == "desk.hide":
            column = snapshot.get("column")
            if column not in _HIDE_ON or secret_column(column or ""):
                return False, "That entry has no hide column to put back."
            if snapshot.get("keys"):
                clause, params, key_err = _key_where({"keys": tuple(snapshot["keys"])}, snapshot["keys"])
                if key_err:
                    return False, "That entry has no row to put back."
            else:
                clause, params = _where_id(snapshot.get("id"))
            _set_fields(table, clause, params, {column: snapshot.get(side_name)})
            return True, "Put that record back."
        if action == "desk.link":
            added = snapshot.get("before") is None and snapshot.get("after")
            removed = snapshot.get("after") is None and isinstance(snapshot.get("before"), dict)
            if added and plan == "restore":
                return _delete_link(table, snapshot)
            if added and plan == "reapply":
                return _reinsert(table, snapshot.get("keys") or {}, snapshot.get("after") or {})
            if removed and plan == "restore":
                return _reinsert(table, snapshot.get("keys") or {}, snapshot.get("before") or {})
            if removed and plan == "reapply":
                return _delete_link(table, snapshot)
            return False, "That link has nothing to put back."
        fields = snapshot.get(side_name)
        if action == "desk.update" and snapshot.get("created") and plan == "restore":
            column = _hide_column(_columns(table))
            if not column:
                return False, "That new record stays. This bot does not delete it."
            clause, params = _where_id(snapshot.get("id"))
            hidden = None if column == "removed_at" else _HIDE_ON[column]
            if column == "removed_at":
                cur = _cur()
                cur.execute(f"UPDATE {_quote(table)} SET `removed_at`=NOW() WHERE {clause}", params)
            else:
                _set_fields(table, clause, params, {column: hidden})
            return True, "Hid that new record."
        if not isinstance(fields, dict) or not fields:
            return False, "That entry has no earlier values to put back."
        desk_row = _BY_ID.get(table)
        clean = {
            key: value
            for key, value in fields.items()
            if key in safe_columns(_columns(table), keep_ips=bool(desk_row and desk_row.get("keep_ips")))
        }
        if snapshot.get("id"):
            clause, params = _where_id(snapshot.get("id"))
        elif snapshot.get("keys"):
            clause, params, key_err = _key_where({"keys": tuple(snapshot["keys"])}, snapshot["keys"])
            if key_err:
                return False, "That entry has no row to put back."
        else:
            return False, "That entry has no row to put back."
        _set_fields(table, clause, params, clean)
        return True, "Put that record back."
    except Exception as exc:
        print(f"bot desk undo {action}: {exc}")
        return False, "That desk change could not be reversed."


def _delete_link(table, snapshot) -> tuple[bool, str]:
    desk_row = _BY_ID.get(table) or next((row for row in DESKS if row["table"] == table), None)
    if not desk_row or not desk_row.get("link"):
        return False, "That record stays. This bot does not delete it."
    if snapshot.get("keys"):
        clause, params, key_err = _key_where({"keys": tuple(snapshot["keys"])}, snapshot["keys"])
        if key_err:
            return False, "That entry has no row to put back."
    elif snapshot.get("id") not in (None, ""):
        clause, params = _where_id(snapshot.get("id"))
    else:
        return False, "That entry has no row to put back."
    cur = _cur()
    cur.execute(f"DELETE FROM {_quote(table)} WHERE {clause}", params)
    return True, "Removed that link."


def _reinsert(table, keys, after) -> tuple[bool, str]:
    row = {}
    row.update(keys or {})
    row.update(after or {})
    desk_row = _BY_ID.get(table)
    clean = {
        key: value
        for key, value in row.items()
        if _IDENT.match(key or "") and not _blocked_field(key, desk_row)
    }
    if not clean:
        return False, "That link has nothing to put back."
    names = list(clean)
    cur = _cur()
    cur.execute(
        f"INSERT INTO {_quote(table)} ({', '.join(_quote(name) for name in names)}) VALUES ({', '.join(['%s'] * len(names))})",
        [clean[name] for name in names],
    )
    return True, "Put that link back."
