"""Read-only comment monitor for the church bot.

Area names and column names come from this file. A caller cannot pick a table.
IP addresses are never selected. Missing tables are skipped.
"""

from __future__ import annotations

from app.utils.bot_sermon_common import _clip, _db, _fail, _like, _limit, _ok, _plain

# parent_where uses only columns filled in at query time from this map.
AREAS = {
    "event": {
        "table": "event_comments",
        "parent": "events",
        "parent_col": "event_id",
        "text_col": "comment",
        "name_col": "name",
        "date_col": "created_at",
        "title_col": "event_name",
        "parent_public": (),
    },
    "sermon": {
        "table": "sermon_comments",
        "parent": "sermons",
        "parent_col": "sermon_id",
        "text_col": "comment",
        "name_col": "contributor_name",
        "date_col": "date_added",
        "title_col": "title",
        "parent_public": ("visibility",),
    },
    "prayer": {
        "table": "prayers_added",
        "parent": "prayers",
        "parent_col": "prayer_request_id",
        "text_col": "prayer",
        "name_col": "contributor_name",
        "date_col": "date_added",
        "title_col": "title",
        "parent_public": ("visibility",),
    },
    "dream": {
        "table": "dream_comments",
        "parent": "dreams",
        "parent_col": "dream_id",
        "text_col": "comment",
        "name_col": "contributor_name",
        "date_col": "date_posted",
        "title_col": "title",
        "parent_public": ("journal",),
    },
    "prophecy": {
        "table": "prophecy_comments",
        "parent": "prophecies",
        "parent_col": "prophecy_id",
        "text_col": "comment",
        "name_col": "contributor_name",
        "date_col": "date_added",
        "title_col": "title",
        "parent_public": ("journal",),
    },
    "announcement": {
        "table": "announcement_comments",
        "parent": "announcements",
        "parent_col": "announcement_id",
        "text_col": "comment",
        "name_col": "contributor_name",
        "date_col": "date_added",
        "title_col": "title",
        "parent_public": (),
    },
    "photo": {
        "table": "page_photo_comments",
        "parent": "page_photos",
        "parent_col": "photo_id",
        "text_col": "comment",
        "name_col": "contributor_name",
        "date_col": "date_added",
        "title_col": "caption",
        "parent_public": (),
    },
    "post": {
        "table": "community_post_comments",
        "parent": "community_posts",
        "parent_col": "post_id",
        "text_col": "comment",
        "name_col": "contributor_name",
        "date_col": "date_added",
        "title_col": "title",
        "parent_public": ("post",),
    },
    "ticket": {
        "table": "ticket_comments",
        "parent": "tickets",
        "parent_col": "ticket_id",
        "text_col": "comment",
        "name_col": "",
        "date_col": "date_added",
        "title_col": "title",
        "parent_public": (),
    },
}

_columns_cache: dict[str, set[str]] = {}


def area_names() -> list[str]:
    return list(AREAS)


def _columns(table: str) -> set[str]:
    if table in _columns_cache:
        return _columns_cache[table]
    cur = _db().cursor()
    cur.execute(
        """
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        """,
        (table,),
    )
    found = {row.get("COLUMN_NAME") for row in (cur.fetchall() or []) if row.get("COLUMN_NAME")}
    _columns_cache[table] = found
    return found


def _parent_filter(spec: dict, parent_cols: set[str]) -> str:
    kind = spec["parent_public"]
    parts = []
    if "journal" in kind or "visibility" in kind:
        if "visibility" in parent_cols:
            parts.append("p.visibility IN ('public', 'private')")
        if "moderation_hidden" in parent_cols:
            parts.append("COALESCE(p.moderation_hidden, 0) = 0")
        if "ownership_status" in parent_cols:
            parts.append("COALESCE(p.ownership_status, 'owned') <> 'pending'")
        if "journal" in kind and "is_approved" in parent_cols:
            parts.append("COALESCE(p.is_approved, 0) = 1")
    if "post" in kind:
        if "visibility" in parent_cols:
            parts.append("p.visibility = 'public'")
        if "removed_at" in parent_cols:
            parts.append("p.removed_at IS NULL")
        if "shadowed" in parent_cols:
            parts.append("COALESCE(p.shadowed, 0) = 0")
    return (" AND " + " AND ".join(parts)) if parts else ""


def _status_sql(cols: set[str], status: str) -> str | None:
    has_removed = "removed" in cols
    has_shadow = "shadowed" in cols
    if status == "visible":
        bits = []
        if has_removed:
            bits.append("COALESCE(c.removed, 0) = 0")
        if has_shadow:
            bits.append("COALESCE(c.shadowed, 0) = 0")
        return " AND ".join(bits) if bits else "1=1"
    if status == "removed":
        if not has_removed:
            return None
        return "COALESCE(c.removed, 0) = 1"
    if status == "shadowed":
        if not has_shadow:
            return None
        sql = "COALESCE(c.shadowed, 0) = 1"
        if has_removed:
            sql += " AND COALESCE(c.removed, 0) = 0"
        return sql
    if status == "all":
        return "1=1"
    return None


def _row_from(spec: dict, row: dict, *, full: bool) -> dict:
    body = row.get("body") or ""
    item = _plain(row, ("id", "parent_id", "parent_title", "name", "posted_at", "user_id", "removed", "shadowed"))
    item["area"] = spec["area"]
    item["body"] = body if full else (_clip(body, 600) or "")
    if not full and body and len(body) > 600:
        item["body_preview"] = True
    return item


def _fetch(spec: dict, *, comment_id=None, parent_id=None, search: str = "", status: str = "visible", limit: int = 30):
    table = spec["table"]
    parent = spec["parent"]
    comment_cols = _columns(table)
    parent_cols = _columns(parent)
    if not comment_cols or not parent_cols:
        return None, "missing"
    status_sql = _status_sql(comment_cols, status)
    if status_sql is None:
        return [], "status"
    name_col = spec["name_col"]
    name_sql = f"COALESCE(c.{name_col}, '')" if name_col and name_col in comment_cols else "''"
    removed_sql = "COALESCE(c.removed, 0)" if "removed" in comment_cols else "0"
    shadow_sql = "COALESCE(c.shadowed, 0)" if "shadowed" in comment_cols else "0"
    user_sql = "c.user_id" if "user_id" in comment_cols else "NULL"
    title_col = spec["title_col"] if spec["title_col"] in parent_cols else ""
    title_sql = f"p.{title_col}" if title_col else "''"
    sql = f"""
        SELECT c.id, c.{spec['parent_col']} AS parent_id, {title_sql} AS parent_title,
               {name_sql} AS name, c.{spec['text_col']} AS body,
               c.{spec['date_col']} AS posted_at, {user_sql} AS user_id,
               {removed_sql} AS removed, {shadow_sql} AS shadowed
        FROM {table} c
        JOIN {parent} p ON p.id = c.{spec['parent_col']}
        WHERE {status_sql}
    """
    params: list = []
    sql += _parent_filter(spec, parent_cols)
    if comment_id is not None:
        sql += " AND c.id=%s"
        params.append(int(comment_id))
    if parent_id is not None:
        sql += f" AND c.{spec['parent_col']}=%s"
        params.append(int(parent_id))
    if (search or "").strip():
        like = _like(search)
        pieces = [f"c.{spec['text_col']} LIKE %s"]
        params.append(like)
        if name_col and name_col in comment_cols:
            pieces.append(f"c.{name_col} LIKE %s")
            params.append(like)
        if title_col:
            pieces.append(f"p.{title_col} LIKE %s")
            params.append(like)
        sql += " AND (" + " OR ".join(pieces) + ")"
    sql += f" ORDER BY c.{spec['date_col']} DESC, c.id DESC LIMIT %s"
    params.append(_limit(limit, 30))
    cur = _db().cursor()
    cur.execute(sql, params)
    return cur.fetchall() or [], ""


def list_comments(area: str, parent_id, search: str, status: str, limit) -> dict:
    status = (status or "visible").strip().lower()
    if status not in ("visible", "removed", "shadowed", "all"):
        return _fail("status must be visible, removed, shadowed, or all.", 400)
    chosen = (area or "").strip().lower()
    names = [chosen] if chosen else list(AREAS)
    if chosen and chosen not in AREAS:
        listed = ", ".join(AREAS)
        return _fail(f"area must be one of: {listed}.", 400)
    try:
        parent = None
        if parent_id not in (None, ""):
            try:
                parent = int(parent_id)
            except (TypeError, ValueError):
                return _fail("parent must be a number.", 400)
        rows = []
        skipped = []
        for name in names:
            spec = dict(AREAS[name])
            spec["area"] = name
            found, note = _fetch(
                spec, parent_id=parent, search=search or "", status=status, limit=limit,
            )
            if note == "missing":
                if chosen:
                    return _fail("That comment area is not on this church.", 404)
                skipped.append(name)
                continue
            if note == "status":
                if chosen:
                    return _fail("That area has no removed or shadowed flag.", 400)
                continue
            for row in found or []:
                rows.append(_row_from(spec, row, full=False))
        rows.sort(key=lambda item: str(item.get("posted_at") or ""), reverse=True)
        cap = _limit(limit, 30)
        rows = rows[:cap]
        data = {"comments": rows, "count": len(rows), "status": status, "areas": names}
        if skipped:
            data["skipped"] = skipped
        return _ok(data)
    except Exception as exc:
        print(f"bot comments: {exc}")
        return _fail("Those comments could not be read.", 500, "comments.list")


def comment_detail(area: str, comment_id: int) -> dict:
    name = (area or "").strip().lower()
    spec_src = AREAS.get(name)
    if not spec_src:
        listed = ", ".join(AREAS)
        return _fail(f"area must be one of: {listed}.", 400)
    try:
        spec = dict(spec_src)
        spec["area"] = name
        found, note = _fetch(spec, comment_id=int(comment_id), status="all", limit=1)
        if note == "missing":
            return _fail("That comment area is not on this church.", 404)
        if not found:
            return _fail("That comment is not available.", 404)
        return _ok(_row_from(spec, found[0], full=True))
    except Exception as exc:
        print(f"bot comment detail: {exc}")
        return _fail("That comment could not be read.", 500, "comments.detail")
