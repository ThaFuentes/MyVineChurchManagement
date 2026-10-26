# app/models/pastoral/illustrations.py
# Full path: WebChurchMan/app/models/pastoral/illustrations.py
# File name: illustrations.py
# Brief, detailed purpose:
#   Pure database layer for the Illustration Library.
#   Handles fetching, CRUD, search, and tag parsing.
#   Visibility: 'private' (user_id = owner), 'pastoral_group' (user_id IS NULL).
#   Personal notes stored in notes column (creator-only display in UI).
#   NO Flask imports - models must remain independent of routes.

import pymysql
import json
from app.models.db import get_db


def _parse_tags(tags_raw) -> list:
    """Parse tags from JSON array or legacy comma-separated text."""
    if not tags_raw:
        return []
    if isinstance(tags_raw, list):
        return tags_raw
    if isinstance(tags_raw, str):
        try:
            parsed = json.loads(tags_raw)
            return parsed if isinstance(parsed, list) else [str(parsed)]
        except json.JSONDecodeError:
            return [t.strip() for t in tags_raw.split(',') if t.strip()]
    return []


def _normalize_tags_for_storage(tags) -> str:
    """Store tags consistently as JSON array string."""
    if not tags:
        return json.dumps([])
    if isinstance(tags, list):
        return json.dumps(tags)
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
            return json.dumps(parsed if isinstance(parsed, list) else [tags])
        except json.JSONDecodeError:
            return json.dumps([t.strip() for t in tags.split(',') if t.strip()])
    return json.dumps([])


def _resolve_owner(data: dict, acting_user_id: int):
    """Private → owner user_id; shared/pastoral_group → NULL (visible to pastoral group)."""
    vis = data.get('visibility') or 'private'
    if isinstance(vis, str):
        vis = vis.strip().lower()
    if vis in ('private', 'only_me', 'me'):
        return acting_user_id
    return None


def get_visible_illustrations(user_id: int, search: str | None = None) -> list[dict]:
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    sql = """
        SELECT il.*,
               u.username AS creator_name,
               CASE WHEN il.user_id IS NOT NULL THEN 'private' ELSE 'pastoral_group' END AS visibility
        FROM illustration_library il
        LEFT JOIN users u ON il.user_id = u.id
        WHERE (il.user_id = %s OR il.user_id IS NULL)
          AND il.removed_at IS NULL
    """
    params = [user_id]

    try:
        from app.models.campuses import content_campus_filter_sql
        frag, cparams = content_campus_filter_sql(
            'il.campus_id', user_id=user_id, owner_column='il.user_id'
        )
        sql += frag
        params.extend(cparams)
    except Exception:
        pass

    if search:
        like = f"%{search}%"
        sql += (
            " AND (il.title LIKE %s OR il.content LIKE %s OR il.source LIKE %s"
            " OR il.tags LIKE %s OR IFNULL(il.notes, '') LIKE %s)"
        )
        params.extend([like] * 5)

    sql += " ORDER BY il.created_at DESC"

    cur.execute(sql, params)
    results = cur.fetchall()

    for r in results:
        r['tags'] = _parse_tags(r.get('tags'))

    return results


def get_illustration_by_id(illus_id: int, user_id: int) -> dict | None:
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)

    sql = """
        SELECT il.*,
               u.username AS creator_name,
               CASE WHEN il.user_id IS NOT NULL THEN 'private' ELSE 'pastoral_group' END AS visibility
        FROM illustration_library il
        LEFT JOIN users u ON il.user_id = u.id
        WHERE il.id = %s
          AND il.removed_at IS NULL
          AND (il.user_id = %s OR il.user_id IS NULL)
    """
    params = [illus_id, user_id]
    try:
        from app.models.campuses import content_campus_filter_sql
        frag, cparams = content_campus_filter_sql(
            'il.campus_id', user_id=user_id, owner_column='il.user_id'
        )
        sql += frag
        params.extend(cparams)
    except Exception:
        pass
    cur.execute(sql, params)

    result = cur.fetchone()
    if result:
        result['tags'] = _parse_tags(result.get('tags'))
    return result


def create_illustration(data: dict, user_id: int) -> int:
    """Create illustration. user_id is the acting user; visibility in data controls owner."""
    from app.utils.bot_illustration_fields import meta_columns
    _columns, meta_error = meta_columns(data or {})
    if meta_error:
        raise ValueError(meta_error)
    db = get_db()
    cur = db.cursor()

    owner = _resolve_owner(data, user_id)
    campus_id = data.get('campus_id')
    if campus_id in (None, '', 0, '0'):
        try:
            from app.models.campuses import resolve_campus_id_for_write
            campus_id = resolve_campus_id_for_write(data.get('campus_id'))
        except Exception:
            campus_id = None

    notes = data.get('notes')
    if notes is not None:
        notes = str(notes).strip() or None

    cur.execute("""
        INSERT INTO illustration_library (user_id, title, content, source, tags, notes, campus_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        owner,
        data['title'],
        data['content'],
        data.get('source'),
        _normalize_tags_for_storage(data.get('tags')),
        notes,
        campus_id,
    ))

    db.commit()
    new_id = cur.lastrowid
    _write_meta_and_tags(new_id, data)
    return new_id


def update_illustration(illus_id: int, data: dict, user_id: int) -> None:
    """Update illustration. user_id is the acting user (for ownership check + private owner)."""
    from app.utils.bot_illustration_fields import meta_columns
    _columns, meta_error = meta_columns(data or {})
    if meta_error:
        raise ValueError(meta_error)
    db = get_db()
    cur = db.cursor()

    owner = _resolve_owner(data, user_id)
    notes = data.get('notes')
    if notes is not None:
        notes = str(notes).strip() or None

    cur.execute("""
        UPDATE illustration_library
        SET user_id = %s, title = %s, content = %s, source = %s, tags = %s, notes = %s
        WHERE id = %s AND (user_id = %s OR user_id IS NULL)
    """, (
        owner,
        data['title'],
        data['content'],
        data.get('source'),
        _normalize_tags_for_storage(data.get('tags')),
        notes,
        illus_id,
        user_id,
    ))

    db.commit()
    _write_meta_and_tags(illus_id, data)


def _write_meta_and_tags(illus_id: int, data: dict) -> None:
    """Scripture, fact-check, kind, and real tag rows. Missing keys stay as they are."""
    if not illus_id or not isinstance(data, dict):
        return
    from app.utils.bot_illustration_fields import meta_columns, tag_name
    columns, error = meta_columns(data)
    if error:
        raise ValueError(error)
    write_illustration_meta(illus_id, columns or {})
    if "tags" in data:
        replace_illustration_tags(illus_id, _parse_tags(data.get("tags")))


def write_illustration_meta(illus_id: int, columns: dict) -> None:
    allowed = (
        "scripture_reference",
        "scripture_translation",
        "scripture_book",
        "scripture_chapter",
        "fact_check",
        "kind",
    )
    sets = []
    params = []
    for key in allowed:
        if key not in (columns or {}):
            continue
        sets.append(f"{key}=%s")
        params.append(columns[key])
    if not sets:
        return
    params.append(int(illus_id))
    db = get_db()
    cur = db.cursor()
    cur.execute(f"UPDATE illustration_library SET {', '.join(sets)} WHERE id=%s", params)
    db.commit()


def replace_illustration_tags(illus_id: int, names) -> None:
    """Replace the tag links for one illustration. The JSON tags column is left to the caller."""
    from app.utils.bot_illustration_fields import tag_name
    clean = []
    seen = set()
    for raw in names or []:
        name = tag_name(raw if not isinstance(raw, dict) else raw.get("name"))
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        clean.append(name)
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM illustration_tag_links WHERE illustration_id=%s", (int(illus_id),))
    for name in clean:
        cur.execute("SELECT id FROM illustration_tags WHERE LOWER(name)=LOWER(%s) LIMIT 1", (name,))
        row = cur.fetchone()
        if row:
            tag_id = int(row["id"])
        else:
            try:
                cur.execute("INSERT INTO illustration_tags (name) VALUES (%s)", (name,))
                tag_id = int(cur.lastrowid)
            except Exception:
                cur.execute("SELECT id FROM illustration_tags WHERE LOWER(name)=LOWER(%s) LIMIT 1", (name,))
                row = cur.fetchone()
                if not row:
                    continue
                tag_id = int(row["id"])
        cur.execute(
            "INSERT IGNORE INTO illustration_tag_links (illustration_id, tag_id) VALUES (%s, %s)",
            (int(illus_id), tag_id),
        )
    db.commit()


def _visible_illustration_sql(user_id: int) -> tuple[str, list]:
    sql = " AND (il.user_id = %s OR il.user_id IS NULL) AND il.removed_at IS NULL"
    params: list = [user_id]
    try:
        from app.models.campuses import content_campus_filter_sql
        frag, extra = content_campus_filter_sql(
            "il.campus_id", user_id=user_id, owner_column="il.user_id",
        )
        sql += frag
        params.extend(extra)
    except Exception:
        pass
    return sql, params


def find_similar_illustrations(user_id: int, title: str, scripture_reference: str | None = None,
                               exclude_id: int | None = None, limit: int = 5) -> list[dict]:
    """Same normalized title, or the same book and chapter."""
    from app.utils.bot_illustration_fields import parse_scripture, title_key
    parsed = parse_scripture(scripture_reference or "")
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    where, params = _visible_illustration_sql(int(user_id))
    cur.execute(
        f"""
        SELECT il.id, il.title, il.scripture_reference, il.scripture_book, il.scripture_chapter
        FROM illustration_library il
        WHERE 1=1 {where}
        """,
        params,
    )
    want = title_key(title)
    book = parsed.get("book")
    chapter = parsed.get("chapter")
    matches = []
    for row in cur.fetchall() or []:
        if exclude_id and int(row["id"]) == int(exclude_id):
            continue
        same_title = bool(want) and title_key(row.get("title")) == want
        same_place = False
        if book and chapter and (row.get("scripture_book") or "") == book:
            try:
                same_place = int(row.get("scripture_chapter") or 0) == int(chapter)
            except (TypeError, ValueError):
                same_place = False
        if not same_title and not same_place:
            continue
        matches.append({
            "id": int(row["id"]),
            "title": row.get("title"),
            "scripture_reference": row.get("scripture_reference"),
            "scripture_book": row.get("scripture_book"),
            "scripture_chapter": row.get("scripture_chapter"),
        })
        if len(matches) >= max(1, int(limit)):
            break
    return matches


def illustration_usage(illus_id: int, *, campus_id=None, exclude_section_id=None) -> tuple[list[dict], str | None]:
    """Sermons that already link this illustration, and the latest date."""
    from app.utils.bot_illustration_fields import blank_date
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    cur.execute(
        """
        SELECT ss.id AS section_id, ss.sermon_id, ps.title, ps.service_date,
               ps.campus_id, ps.updated_at, ps.created_at
        FROM sermon_sections ss
        JOIN pastoral_sermons ps ON ps.id = ss.sermon_id
        WHERE ss.illustration_id=%s AND ss.removed_at IS NULL AND ps.removed_at IS NULL
        ORDER BY ps.id DESC
        """,
        (int(illus_id),),
    )
    rows = []
    for row in cur.fetchall() or []:
        if exclude_section_id and int(row["section_id"]) == int(exclude_section_id):
            continue
        other = row.get("campus_id")
        if campus_id not in (None, "", 0, "0") and other not in (None, "", 0, "0"):
            try:
                if int(other) != int(campus_id):
                    continue
            except (TypeError, ValueError):
                pass
        service_date = blank_date(row.get("service_date"))
        used_on = service_date
        if not used_on:
            stamp = row.get("updated_at") or row.get("created_at")
            used_on = str(stamp)[:10] if stamp else None
            if used_on and used_on.startswith("0000"):
                used_on = None
        rows.append({
            "sermon_id": int(row["sermon_id"]),
            "section_id": int(row["section_id"]),
            "title": row.get("title"),
            "service_date": service_date,
            "used_on": used_on,
        })
    last = None
    for item in rows:
        stamp = item.get("used_on") or item.get("service_date")
        if stamp and (last is None or str(stamp) > str(last)):
            last = str(stamp)[:10]
    return rows, last


def illustration_use_counts(ids: list[int]) -> dict[int, dict]:
    """One grouped lookup: how many live sections use each illustration, and the last date."""
    clean = []
    for raw in ids or []:
        try:
            clean.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not clean:
        return {}
    from app.utils.bot_illustration_fields import blank_date
    db = get_db()
    cur = db.cursor(pymysql.cursors.DictCursor)
    marks = ", ".join(["%s"] * len(clean))
    cur.execute(
        f"""
        SELECT ss.illustration_id AS illustration_id, ps.service_date, ps.updated_at, ps.created_at
        FROM sermon_sections ss
        JOIN pastoral_sermons ps ON ps.id = ss.sermon_id
        WHERE ss.illustration_id IN ({marks})
          AND ss.removed_at IS NULL AND ps.removed_at IS NULL
        """,
        clean,
    )
    out: dict[int, dict] = {}
    for row in cur.fetchall() or []:
        try:
            iid = int(row["illustration_id"])
        except (TypeError, ValueError, KeyError):
            continue
        bucket = out.setdefault(iid, {"count": 0, "last_used": None})
        bucket["count"] += 1
        service_date = blank_date(row.get("service_date"))
        stamp = service_date
        if not stamp:
            raw = row.get("updated_at") or row.get("created_at")
            stamp = str(raw)[:10] if raw else None
            if stamp and stamp.startswith("0000"):
                stamp = None
        if stamp and (bucket["last_used"] is None or str(stamp) > str(bucket["last_used"])):
            bucket["last_used"] = str(stamp)[:10]
    return out


def delete_illustration(illus_id: int, user_id: int) -> bool:
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        DELETE FROM illustration_library
        WHERE id = %s AND (user_id = %s OR user_id IS NULL)
    """, (illus_id, user_id))

    db.commit()
    return cur.rowcount > 0
