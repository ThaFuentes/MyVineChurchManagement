"""Illustrations, research notes, verses, and the speaking lineup."""

from __future__ import annotations

from datetime import date, timedelta

from app.utils.bot_sermon_common import (
    SECTION_TYPES,
    SHARE_VISIBILITY,
    TEXT_CAP,
    _blank_name,
    _clip,
    _db,
    _fail,
    _int_or_none,
    _jsonish,
    _like,
    _limit,
    _offset,
    _ok,
    _parse_date,
    _person,
    _plain,
    _sermon_brief,
    _sermon_exists,
    _tags,
    _tags_json,
    _too_big,
    _update_fields,
    ILLUSTRATION_FIELDS,
    as_html,
    assignments_with_speaker,
    ensure_soft_columns,
    illustration_visible_sql,
    may_see_illustration_notes,
    user_role,
    verse_span,
)

_ILLUSTRATION_KEYS = (
    "id", "title", "source", "notes", "user_id", "created_at", "content",
    "scripture_reference", "scripture_translation", "scripture_book", "scripture_chapter",
    "fact_check", "kind",
)


def _illustration_item(row: dict, preview: bool, actor_id: int | None = None, *, staff: bool | None = None,
                       link_tags: list[str] | None = None) -> dict:
    item = _plain(row, _ILLUSTRATION_KEYS)
    names = _tags(row.get("tags"))
    for name in link_tags or []:
        if name and name not in names and name.lower() not in {part.lower() for part in names}:
            names.append(name)
    item["tags"] = names
    item["visibility"] = "private" if row.get("user_id") else "pastoral_group"
    item["creator_name"] = _blank_name(row.get("creator_name"))
    if not may_see_illustration_notes(actor_id, row.get("user_id"), staff=staff):
        item["notes"] = None
    if preview:
        content = item.get("content") or ""
        item["content"] = content[:400]
        if len(content) > 400:
            item["content_preview"] = True
    return item


def _tag_names_for(ids: list[int]) -> dict[int, list[str]]:
    clean = []
    for raw in ids:
        try:
            clean.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not clean:
        return {}
    marks = ", ".join(["%s"] * len(clean))
    cur = _db().cursor()
    cur.execute(
        f"""
        SELECT l.illustration_id, t.name
        FROM illustration_tag_links l
        JOIN illustration_tags t ON t.id = l.tag_id
        WHERE l.illustration_id IN ({marks})
        ORDER BY t.name
        """,
        clean,
    )
    out: dict[int, list[str]] = {}
    for row in cur.fetchall() or []:
        try:
            iid = int(row["illustration_id"])
        except (TypeError, ValueError, KeyError):
            continue
        name = str(row.get("name") or "").strip()
        if name:
            out.setdefault(iid, []).append(name)
    return out


def _illustration_filters(filters: dict) -> tuple[str, list, str | None]:
    from app.utils.bot_illustration_fields import normalize_fact, normalize_kind, parse_scripture, tag_name
    sql = ""
    params: list = []
    book = str((filters or {}).get("book") or "").strip()
    if book:
        parsed = parse_scripture(book)
        canon = parsed.get("book") or book
        sql += (
            " AND (il.scripture_book = %s"
            " OR ((il.scripture_book IS NULL OR il.scripture_book = '')"
            " AND (il.scripture_reference = %s OR il.scripture_reference LIKE %s OR il.scripture_reference LIKE %s)))"
        )
        params.extend([canon, canon, f"{canon} %", f"{canon}:%"])
    chapter = (filters or {}).get("chapter")
    if chapter not in (None, ""):
        try:
            number = int(chapter)
        except (TypeError, ValueError):
            return "", [], "chapter must be a number."
        sql += (
            " AND (il.scripture_chapter = %s"
            " OR ((il.scripture_chapter IS NULL OR il.scripture_chapter = 0)"
            " AND (il.scripture_reference LIKE %s OR il.scripture_reference LIKE %s)))"
        )
        params.extend([number, f"% {number}:%", f"% {number} %"])
    kind = (filters or {}).get("kind")
    if kind not in (None, ""):
        canon_kind = normalize_kind(kind)
        if not canon_kind:
            return "", [], "kind must be testimony, historical, science, or bible."
        sql += " AND il.kind = %s"
        params.append(canon_kind)
    fact = (filters or {}).get("fact_check")
    if fact in (None, ""):
        fact = (filters or {}).get("fact")
    if fact not in (None, ""):
        canon_fact = normalize_fact(fact)
        if not canon_fact:
            return "", [], "fact_check must be verified, testimony, or needs_review."
        sql += " AND il.fact_check = %s"
        params.append(canon_fact)
    tag = tag_name((filters or {}).get("tag"))
    if tag:
        sql += (
            " AND (il.tags LIKE %s OR EXISTS ("
            " SELECT 1 FROM illustration_tag_links l"
            " JOIN illustration_tags t ON t.id = l.tag_id"
            " WHERE l.illustration_id = il.id AND LOWER(t.name) = LOWER(%s)))"
        )
        params.extend([f'%"{tag}"%', tag])
    return sql, params, None


def list_illustrations(search: str, limit, illus_id=None, actor_id: int | None = None, **filters) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "illustration.list")
    try:
        cur = _db().cursor()
        staff = user_role(int(actor_id)) in ("Owner", "Admin") if actor_id else False
        visible_sql, visible_params = illustration_visible_sql(int(actor_id)) if actor_id else ("", [])
        if illus_id not in (None, ""):
            try:
                wanted = int(illus_id)
            except (TypeError, ValueError):
                return _fail("Illustration id must be a number.", 400)
            cur.execute(
                """
                SELECT il.id, il.title, il.content, il.source, il.tags, il.notes,
                       il.user_id, il.created_at, il.scripture_reference, il.scripture_translation,
                       il.scripture_book, il.scripture_chapter, il.fact_check, il.kind,
                       u.username AS creator_name
                FROM illustration_library il
                LEFT JOIN users u ON u.id = il.user_id
                WHERE il.id=%s AND il.removed_at IS NULL
                """ + visible_sql,
                (wanted, *visible_params),
            )
            row = cur.fetchone()
            if not row:
                return _fail("That illustration is not in the library.", 404)
            names = _tag_names_for([wanted]).get(wanted, [])
            item = _illustration_item(row, False, actor_id, staff=staff, link_tags=names)
            from app.models.pastoral.illustrations import illustration_usage
            used, last_used = illustration_usage(wanted)
            item["used_in"] = used[:50]
            item["used_count"] = len(used)
            item["last_used"] = last_used
            return _ok(item)
        filter_sql, filter_params, filter_error = _illustration_filters(filters)
        if filter_error:
            return _fail(filter_error, 400)
        where = """
            FROM illustration_library il
            LEFT JOIN users u ON u.id = il.user_id
            WHERE il.removed_at IS NULL
        """ + visible_sql + filter_sql
        params = list(visible_params) + list(filter_params)
        if (search or "").strip():
            where += (
                " AND (il.title LIKE %s OR il.content LIKE %s OR il.source LIKE %s OR il.tags LIKE %s"
                " OR IFNULL(il.notes, '') LIKE %s OR IFNULL(il.scripture_reference, '') LIKE %s"
                " OR IFNULL(il.scripture_book, '') LIKE %s OR IFNULL(il.kind, '') LIKE %s"
                " OR IFNULL(il.fact_check, '') LIKE %s)"
            )
            like = _like(search)
            params.extend([like] * 9)
        preview = str((filters or {}).get("preview") or "").strip().lower() in ("1", "true", "yes", "on")
        page_limit = _limit(limit)
        page_offset = _offset((filters or {}).get("offset"))
        cur.execute("SELECT COUNT(*) AS n " + where, params)
        total = int((cur.fetchone() or {}).get("n") or 0)
        cur.execute(
            """
            SELECT il.id, il.title, il.content, il.source, il.tags, il.notes,
                   il.user_id, il.created_at, il.scripture_reference, il.scripture_translation,
                   il.scripture_book, il.scripture_chapter, il.fact_check, il.kind,
                   u.username AS creator_name
            """ + where + " ORDER BY il.created_at DESC, il.id DESC LIMIT %s OFFSET %s",
            [*params, page_limit, page_offset],
        )
        fetched = list(cur.fetchall() or [])
        names = _tag_names_for([int(row["id"]) for row in fetched])
        rows = [
            _illustration_item(row, preview, actor_id, staff=staff, link_tags=names.get(int(row["id"])))
            for row in fetched
        ]
        return _ok({
            "illustrations": rows,
            "count": len(rows),
            "total": total,
            "offset": page_offset,
            "limit": page_limit,
        })
    except Exception as exc:
        print(f"bot illustrations: {exc}")
        return _fail("The illustrations could not be read.", 500, "illustration.list")


def create_illustration_item(actor_id: int, body: dict) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "illustration.create")
    body = body or {}
    title = str(body.get("title") or "").strip()[:500]
    content = str(body.get("content") or "").strip()[:TEXT_CAP]
    if not title or not content:
        return _fail("An illustration needs a title and the story.", 400)
    visibility = str(body.get("visibility") or "pastoral_group").strip().lower()
    if visibility not in SHARE_VISIBILITY:
        return _fail("visibility must be private or pastoral_group.", 400)
    from app.utils.bot_illustration_fields import meta_columns, truthy
    columns, meta_error = meta_columns(body)
    if meta_error:
        return _fail(meta_error, 400)
    scripture = columns.get("scripture_reference") if columns else None
    if not truthy(body.get("confirm_duplicate")):
        try:
            from app.models.pastoral.illustrations import find_similar_illustrations
            matches = find_similar_illustrations(int(actor_id), title, scripture)
        except Exception as exc:
            print(f"bot illustration duplicate check: {exc}")
            return _fail("That illustration could not be saved.", 500, "illustration.create")
        if matches:
            return _fail(
                "This looks like an illustration you already have.",
                409,
                data={"matches": matches},
                code="possible_duplicate",
            )
    payload = {
        "title": title,
        "content": content,
        "source": _clip(body.get("source"), 500),
        "tags": body.get("tags"),
        "notes": _clip(body.get("notes"), TEXT_CAP),
        "visibility": visibility,
    }
    payload.update(columns or {})
    try:
        from app.models.pastoral.illustrations import create_illustration
        illus_id = create_illustration(payload, int(actor_id))
    except ValueError as exc:
        return _fail(str(exc), 400)
    except Exception as exc:
        print(f"bot illustration create: {exc}")
        return _fail("That illustration could not be saved.", 500, "illustration.create")
    if not illus_id:
        return _fail("That illustration could not be saved.", 500, "illustration.create")
    return _ok(
        {"illustration_id": int(illus_id), "title": title, "visibility": visibility, **(columns or {})},
        {
            "action": "illustration.create",
            "target_type": "illustration",
            "target_id": int(illus_id),
            "detail": title,
            "snapshot": {"illustration_id": int(illus_id)},
        },
    )


def update_illustration_item(actor_id: int | None, illus_id: int, body: dict) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "illustration.update")
    try:
        cur = _db().cursor()
        cur.execute(
            """
            SELECT id, title, content, source, tags, notes, user_id,
                   scripture_reference, scripture_translation, scripture_book, scripture_chapter,
                   fact_check, kind
            FROM illustration_library
            WHERE id=%s AND removed_at IS NULL
            """ + (" AND (user_id=%s OR user_id IS NULL)" if actor_id else ""),
            (int(illus_id), int(actor_id)) if actor_id else (int(illus_id),),
        )
        row = cur.fetchone()
        if not row:
            return _fail("That illustration is not in the library.", 404)
        body = body or {}
        changes = {}
        if "title" in body:
            title = str(body.get("title") or "").strip()[:500]
            if not title:
                return _fail("An illustration needs a title.", 400)
            changes["title"] = title
        if "content" in body:
            content = str(body.get("content") or "").strip()[:TEXT_CAP]
            if not content:
                return _fail("An illustration needs the story.", 400)
            changes["content"] = content
        if "source" in body:
            changes["source"] = _clip(body.get("source"), 500)
        if "tags" in body:
            changes["tags"] = _tags_json(body.get("tags"))
        if "notes" in body:
            if not may_see_illustration_notes(actor_id, row.get("user_id")):
                return _fail("Those private notes belong to someone else.", 403)
            changes["notes"] = _clip(body.get("notes"), TEXT_CAP)
        if "visibility" in body:
            visibility = str(body.get("visibility") or "").strip().lower()
            if visibility not in SHARE_VISIBILITY:
                return _fail("visibility must be private or pastoral_group.", 400)
            if visibility == "private":
                if not actor_id:
                    return _fail("This key has no owner on it, so it cannot make a private illustration.", 400)
                changes["user_id"] = int(actor_id)
            else:
                changes["user_id"] = None
        from app.utils.bot_illustration_fields import meta_columns
        columns, meta_error = meta_columns(body)
        if meta_error:
            return _fail(meta_error, 400)
        changes.update(columns or {})
        if not changes:
            return _fail("Send a title, story, source, tags, scripture, fact-check, or kind to change.", 400)
        before = {key: _jsonish(row.get(key)) for key in changes}
        after = {key: _jsonish(value) for key, value in changes.items()}
        snapshot = {"illustration_id": int(illus_id), "before": before, "after": after}
        if _too_big(snapshot):
            return _fail("That change is too large to undo, so it was not saved.", 400)
        _update_fields("illustration_library", int(illus_id), changes, ILLUSTRATION_FIELDS)
        if "tags" in changes:
            from app.models.pastoral.illustrations import replace_illustration_tags
            replace_illustration_tags(int(illus_id), _tags(changes.get("tags")))
        return _ok(
            {"illustration_id": int(illus_id), **after},
            {
                "action": "illustration.update",
                "target_type": "illustration",
                "target_id": int(illus_id),
                "detail": str(after.get("title") or row.get("title") or "Illustration")[:180],
                "snapshot": snapshot,
            },
        )
    except Exception as exc:
        print(f"bot illustration update: {exc}")
        return _fail("That illustration could not be saved.", 500, "illustration.update")


def rename_illustration_tags(actor_id: int | None, body: dict) -> dict:
    """Rename or merge tags on illustrations this account can open."""
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "illustration.tags")
    from app.utils.bot_illustration_fields import rewrite_tags, tag_rename_request
    sources, dest, error = tag_rename_request(body or {})
    if error:
        return _fail(error, 400)
    if not actor_id:
        return _fail("This key has no person assigned, so it cannot rename tags.", 400)
    try:
        cur = _db().cursor()
        visible_sql, visible_params = illustration_visible_sql(int(actor_id))
        cur.execute(
            """
            SELECT il.id, il.tags
            FROM illustration_library il
            WHERE il.removed_at IS NULL
            """ + visible_sql,
            visible_params,
        )
        planned = []
        for row in cur.fetchall() or []:
            current = _tags(row.get("tags"))
            updated, changed = rewrite_tags(current, sources, dest)
            if not changed:
                continue
            planned.append((int(row["id"]), current, updated))
        if not planned:
            return _fail("No illustration you can open uses that tag.", 404)
        before = [{"id": iid, "tags": _tags_json(old)} for iid, old, _new in planned]
        after = [{"id": iid, "tags": _tags_json(new)} for iid, _old, new in planned]
        snapshot = {
            "sources": sources,
            "destination": dest,
            "before": before,
            "after": after,
        }
        if _too_big(snapshot):
            return _fail("That tag is on too many illustrations to undo in one step, so nothing was renamed.", 400)
        from app.models.pastoral.illustrations import replace_illustration_tags
        for iid, _old, new in planned:
            cur.execute(
                "UPDATE illustration_library SET tags=%s WHERE id=%s",
                (_tags_json(new), iid),
            )
            replace_illustration_tags(iid, new)
        return _ok(
            {"renamed": len(planned), "from": sources, "to": dest},
            {
                "action": "illustration.tags",
                "target_type": "illustration",
                "target_id": planned[0][0],
                "detail": f"{', '.join(sources)} -> {dest}"[:180],
                "snapshot": snapshot,
            },
        )
    except Exception as exc:
        print(f"bot illustration tags: {exc}")
        return _fail("Those tags could not be renamed.", 500, "illustration.tags")


def _undo_illustration_tags(plan: str, snapshot: dict):
    side = snapshot.get("before") if plan == "restore" else snapshot.get("after")
    if not isinstance(side, list) or not side:
        return False, "That tag change has nothing to put back."
    from app.models.pastoral.illustrations import replace_illustration_tags
    cur = _db().cursor()
    for item in side:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        cur.execute(
            "UPDATE illustration_library SET tags=%s WHERE id=%s",
            (item.get("tags") or "[]", int(item["id"])),
        )
        replace_illustration_tags(int(item["id"]), _tags(item.get("tags")))
    if plan == "restore":
        return True, "Put the previous tags back."
    return True, "Applied that tag change again."


def hide_illustration(actor_id: int, illus_id: int) -> dict:
    """Soft-hide an illustration this person owns, or a shared one they can open."""
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "illustration.hide")
    if not actor_id:
        return _fail("This key has no person assigned, so it cannot hide an illustration.", 400)
    try:
        cur = _db().cursor()
        cur.execute(
            """
            SELECT id, title, user_id
            FROM illustration_library
            WHERE id=%s AND removed_at IS NULL AND (user_id=%s OR user_id IS NULL)
            """,
            (int(illus_id), int(actor_id)),
        )
        row = cur.fetchone()
        if not row:
            return _fail("That illustration is not in the library.", 404)
        cur.execute(
            "UPDATE illustration_library SET removed_at=NOW() WHERE id=%s AND removed_at IS NULL",
            (int(illus_id),),
        )
        title = str(row.get("title") or "Illustration")[:180]
        return _ok(
            {"illustration_id": int(illus_id), "hidden": True, "title": title},
            {
                "action": "illustration.hide",
                "target_type": "illustration",
                "target_id": int(illus_id),
                "detail": title,
                "snapshot": {"illustration_id": int(illus_id)},
            },
        )
    except Exception as exc:
        print(f"bot illustration hide: {exc}")
        return _fail("That illustration could not be hidden.", 500, "illustration.hide")


def _load_illustration_for_actor(actor_id: int, illus_id: int) -> dict | None:
    cur = _db().cursor()
    visible_sql, visible_params = illustration_visible_sql(int(actor_id))
    cur.execute(
        """
        SELECT il.id, il.title, il.content, il.source, il.tags, il.notes, il.user_id,
               il.scripture_reference, il.scripture_translation, il.scripture_book,
               il.scripture_chapter, il.fact_check, il.kind
        FROM illustration_library il
        WHERE il.id=%s AND il.removed_at IS NULL
        """ + visible_sql,
        (int(illus_id), *visible_params),
    )
    return cur.fetchone()


def download_illustration(actor_id: int, illus_id: int, fmt: str, as_file: bool = False) -> dict:
    """Markdown in the JSON envelope, or file bytes for docx and file=1."""
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "illustration.download")
    if not actor_id:
        return _fail("This key has no person assigned, so it cannot download an illustration.", 400)
    kind = (fmt or "md").strip().lower()
    if kind in ("doc", "word"):
        kind = "docx"
    if kind not in ("md", "docx"):
        return _fail("format must be md or docx.", 400)
    try:
        row = _load_illustration_for_actor(actor_id, illus_id)
        if not row:
            return _fail("That illustration is not in the library.", 404)
        staff = user_role(int(actor_id)) in ("Owner", "Admin")
        item = _illustration_item(row, False, actor_id, staff=staff)
        item["source_url"] = item.get("source")
        from app.models.pastoral.content_export import (
            content_disposition_attachment,
            docx_bytes,
            format_illustration_markdown,
            illustration_to_docx,
            safe_filename,
        )
        base = safe_filename(item.get("title") or f"illustration_{int(illus_id)}")
        title = str(item.get("title") or "Illustration")[:180]
        detail = f"{kind}: {title}"[:180]
        if kind == "md" and not as_file:
            result = _ok({
                "illustration_id": int(illus_id),
                "format": "md",
                "filename": f"{base}.md",
                "markdown": format_illustration_markdown(item, kind="illustration"),
            })
            result["download_detail"] = detail
            return result
        if kind == "docx":
            data = docx_bytes(illustration_to_docx(item, kind="illustration")).getvalue()
            filename = f"{base}.docx"
            mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            data = format_illustration_markdown(item, kind="illustration").encode("utf-8")
            filename = f"{base}.md"
            mimetype = "text/markdown; charset=utf-8"
        return {
            "ok": True,
            "download_detail": detail,
            "download": {
                "bytes": data,
                "mimetype": mimetype,
                "disposition": content_disposition_attachment(filename),
            },
        }
    except Exception as exc:
        print(f"bot illustration download: {exc}")
        return _fail("That illustration could not be downloaded.", 500, "illustration.download")


def _vault_visible_sql(actor_id):
    if actor_id:
        return "(visibility='pastoral_group' OR user_id=%s)", [int(actor_id)]
    return "visibility='pastoral_group'", []


def _vault_item(row: dict, preview: bool) -> dict:
    item = _plain(row)
    item["tags"] = _tags(row.get("tags"))
    if preview:
        content = item.get("content") or ""
        item["content"] = content[:400]
        if len(content) > 400:
            item["content_preview"] = True
    return item


def list_vault(actor_id: int | None, search: str, limit, item_id=None) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "vault.list")
    try:
        where, params = _vault_visible_sql(actor_id)
        cur = _db().cursor()
        if item_id not in (None, ""):
            try:
                wanted = int(item_id)
            except (TypeError, ValueError):
                return _fail("Vault id must be a number.", 400)
            cur.execute(
                f"""
                SELECT id, user_id, title, content, reference, notes, tags, section_type,
                       scripture_reference, source_url, visibility, created_at
                FROM pastoral_vault
                WHERE id=%s AND removed_at IS NULL AND {where}
                """,
                [wanted, *params],
            )
            row = cur.fetchone()
            if not row:
                return _fail("That research note is not in the vault.", 404)
            return _ok(_vault_item(row, False))
        sql = f"""
            SELECT id, user_id, title, content, reference, notes, tags, section_type,
                   scripture_reference, source_url, visibility, created_at
            FROM pastoral_vault
            WHERE removed_at IS NULL AND {where}
        """
        if (search or "").strip():
            sql += (
                " AND (title LIKE %s OR content LIKE %s OR scripture_reference LIKE %s"
                " OR notes LIKE %s)"
            )
            like = _like(search)
            params.extend([like, like, like, like])
        sql += " ORDER BY created_at DESC, id DESC LIMIT %s"
        params.append(_limit(limit))
        cur.execute(sql, params)
        rows = [_vault_item(row, True) for row in (cur.fetchall() or [])]
        return _ok({"notes": rows, "count": len(rows)})
    except Exception as exc:
        print(f"bot vault: {exc}")
        return _fail("The research vault could not be read.", 500, "vault.list")


def create_vault_item(actor_id: int, body: dict) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "vault.create")
    body = body or {}
    title = str(body.get("title") or "").strip()[:500]
    content = str(body.get("content") or "").strip()[:TEXT_CAP]
    if not title or not content:
        return _fail("A research note needs a title and some words.", 400)
    visibility = str(body.get("visibility") or "pastoral_group").strip().lower()
    if visibility not in SHARE_VISIBILITY:
        return _fail("visibility must be private or pastoral_group.", 400)
    section_type = str(body.get("section_type") or "point").strip().lower()
    if section_type not in SECTION_TYPES:
        return _fail(
            "section_type must be introduction, point, scripture, application, illustration, conclusion, or other.",
            400,
        )
    owner_id = int(actor_id) if visibility == "private" else None
    try:
        from app.models.pastoral.vault import add_vault_item
        item_id = add_vault_item({
            "title": title,
            "content": content,
            "reference": _clip(body.get("reference"), 500),
            "notes": _clip(body.get("notes"), TEXT_CAP),
            "tags": _tags(body.get("tags")),
            "section_type": section_type,
            "scripture_reference": _clip(body.get("scripture_reference"), 500),
            "source_url": _clip(body.get("source_url"), 500),
            "visibility": visibility,
        }, owner_id)
    except Exception as exc:
        print(f"bot vault create: {exc}")
        return _fail("That research note could not be saved.", 500, "vault.create")
    if not item_id:
        return _fail("That research note could not be saved.", 500, "vault.create")
    return _ok(
        {"vault_id": int(item_id), "title": title, "visibility": visibility},
        {
            "action": "vault.create",
            "target_type": "pastoral_vault",
            "target_id": int(item_id),
            "detail": title,
            "snapshot": {"vault_id": int(item_id)},
        },
    )


def update_vault_item(actor_id: int | None, item_id: int, body: dict) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "vault.update")
    try:
        where, params = _vault_visible_sql(actor_id)
        cur = _db().cursor()
        cur.execute(
            f"""
            SELECT id, user_id, title, content, reference, notes, tags, section_type,
                   scripture_reference, source_url, visibility
            FROM pastoral_vault
            WHERE id=%s AND removed_at IS NULL AND {where}
            """,
            [int(item_id), *params],
        )
        row = cur.fetchone()
        if not row:
            return _fail("That research note is not in the vault.", 404)
        body = body or {}
        changes = {}
        if "title" in body:
            title = str(body.get("title") or "").strip()[:500]
            if not title:
                return _fail("A research note needs a title.", 400)
            changes["title"] = title
        if "content" in body:
            content = str(body.get("content") or "").strip()[:TEXT_CAP]
            if not content:
                return _fail("A research note needs some words.", 400)
            changes["content"] = content
        for key, cap in (
            ("reference", 500),
            ("notes", TEXT_CAP),
            ("scripture_reference", 500),
            ("source_url", 500),
        ):
            if key in body:
                changes[key] = _clip(body.get(key), cap)
        if "tags" in body:
            changes["tags"] = _tags_json(body.get("tags"))
        if "section_type" in body:
            section_type = str(body.get("section_type") or "").strip().lower()
            if section_type not in SECTION_TYPES:
                return _fail(
                    "section_type must be introduction, point, scripture, application, illustration, conclusion, or other.",
                    400,
                )
            changes["section_type"] = section_type
        if "visibility" in body:
            visibility = str(body.get("visibility") or "").strip().lower()
            if visibility not in SHARE_VISIBILITY:
                return _fail("visibility must be private or pastoral_group.", 400)
            changes["visibility"] = visibility
            if visibility == "private":
                if not actor_id:
                    return _fail("This key has no owner on it, so it cannot make a private note.", 400)
                changes["user_id"] = int(actor_id)
            else:
                changes["user_id"] = None
        if not changes:
            return _fail("Send the words to change on that note.", 400)
        before = {key: _jsonish(row.get(key)) for key in changes}
        after = {key: _jsonish(value) for key, value in changes.items()}
        snapshot = {"vault_id": int(item_id), "before": before, "after": after}
        if _too_big(snapshot):
            return _fail("That change is too large to undo, so it was not saved.", 400)
        _update_fields("pastoral_vault", int(item_id), changes, VAULT_FIELDS)
        return _ok(
            {"vault_id": int(item_id), **after},
            {
                "action": "vault.update",
                "target_type": "pastoral_vault",
                "target_id": int(item_id),
                "detail": str(after.get("title") or row.get("title") or "Note")[:180],
                "snapshot": snapshot,
            },
        )
    except Exception as exc:
        print(f"bot vault update: {exc}")
        return _fail("That research note could not be saved.", 500, "vault.update")


def _load_verses(ref, translation) -> dict:
    from app.models.pastoral.bible import parse_reference
    parsed = parse_reference(str(ref or ""))
    if not parsed:
        return _fail("Send a reference like John 3:16 or Romans 8:28-30.", 400)
    span = verse_span(int(parsed["verse_start"]), int(parsed["verse_end"]))
    if not span:
        return _fail("Ask for 40 verses or fewer.", 400)
    start, end = span
    trans = str(translation or "").strip() or None
    sql = """
        SELECT translation, book, chapter, verse, text
        FROM bible_verses
        WHERE book=%s AND chapter=%s AND verse BETWEEN %s AND %s
    """
    params = [parsed["book"], int(parsed["chapter"]), start, end]
    if trans:
        sql += " AND translation=%s"
        params.append(trans)
    else:
        sql += " AND translation=(SELECT code FROM bible_translations WHERE is_default=1 LIMIT 1)"
    sql += " ORDER BY verse"
    cur = _db().cursor()
    cur.execute(sql, params)
    rows = list(cur.fetchall() or [])
    if not rows:
        return _fail("That verse is not in the Bible loaded on this church.", 404)
    label = f"{parsed['book']} {parsed['chapter']}:{start}"
    if end != start:
        label = f"{label}-{end}"
    verses = [
        {
            "verse": int(row["verse"]),
            "text": row.get("text") or "",
            "reference": f"{row['book']} {row['chapter']}:{row['verse']}",
        }
        for row in rows
    ]
    return _ok({
        "reference": label,
        "translation": rows[0].get("translation"),
        "book": parsed["book"],
        "chapter": int(parsed["chapter"]),
        "verses": verses,
    })


def lookup_reference(ref: str, translation: str | None = None) -> dict:
    if not str(ref or "").strip():
        return _fail("Send ref= as in John 3:16.", 400)
    try:
        return _load_verses(ref, translation)
    except Exception as exc:
        print(f"bot verses: {exc}")
        return _fail("That verse could not be read.", 500, "verses")


def _lineup_card(plan: dict) -> dict:
    from app.models.pastoral.service_plans import _extract_preacher_info
    preacher = _extract_preacher_info(plan)
    service_date = plan.get("service_date")
    day = _jsonish(service_date)
    if isinstance(day, str):
        day = day[:10]
    roles = []
    for assignment in plan.get("assignments") or []:
        name = _blank_name(assignment.get("user_full_name")) or _blank_name(assignment.get("guest_name"))
        roles.append({
            "role": assignment.get("role_name"),
            "name": name,
            "user_id": _int_or_none(assignment.get("user_id")),
        })
    return {
        "date": day,
        "title": plan.get("title") or "Service",
        "source": plan.get("source") or "override",
        "start_time": _jsonish(plan.get("start_time")),
        "preacher": {"name": preacher.get("name"), "user_id": preacher.get("user_id")},
        "sermon": _sermon_brief(plan.get("pastoral_sermon_id")),
        "roles": roles,
    }


def _copy_assignments(assignments) -> list[dict]:
    rows = []
    for raw in assignments or []:
        role = str(raw.get("role_name") or "").strip()
        if not role:
            continue
        user_id = _int_or_none(raw.get("user_id"))
        guest = str(raw.get("guest_name") or "").strip() or None
        if user_id:
            guest = None
        rows.append({"role_name": role, "user_id": user_id, "guest_name": guest})
    return rows


def _write_plan(day: str, shell: dict, side: dict, actor_id: int) -> None:
    from app.models.pastoral.service_plans import create_or_update_service_plan
    create_or_update_service_plan({
        "service_date": day,
        "title": shell.get("title"),
        "notes": shell.get("notes"),
        "pastoral_sermon_id": side.get("pastoral_sermon_id"),
        "start_time": shell.get("start_time"),
        "worship_start_time": shell.get("worship_start_time"),
        "assignments": side.get("assignments") or [],
    }, int(actor_id))


def lineup_for(days) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "lineup")
    try:
        from app.models.pastoral.service_plans import get_plan_for_date
        try:
            count = int(days if days not in (None, "") else 21)
        except (TypeError, ValueError):
            count = 21
        count = max(1, min(count, 60))
        start = date.today()
        services = []
        for offset in range(count):
            day = (start + timedelta(days=offset)).isoformat()
            plan = get_plan_for_date(day)
            if not plan:
                continue
            services.append(_lineup_card(plan))
        return _ok({"days": count, "services": services, "count": len(services)})
    except Exception as exc:
        print(f"bot lineup: {exc}")
        return _fail("The lineup could not be read.", 500, "lineup")


def set_lineup(actor_id: int, body: dict) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "lineup.set")
    body = body or {}
    day, derr = _parse_date(body.get("date"), required=True)
    if derr:
        return _fail(derr, 400)
    try:
        preacher_id = None
        change_speaker = False
        if "preacher_id" in body or "preacher" in body:
            token = body.get("preacher_id")
            if token in (None, "") and "preacher" in body:
                token = body.get("preacher")
            if token not in (None, ""):
                preacher_id, perr = _person(token)
                if perr:
                    return _fail(perr, 400)
                change_speaker = True
        guest = str(body.get("guest_name") or "").strip()[:191]
        if guest and not preacher_id:
            change_speaker = True
        sermon_given = "sermon_id" in body
        if not change_speaker and not sermon_given:
            return _fail("Say who is speaking or which sermon.", 400)
        from app.models.pastoral.service_plans import get_plan_for_date, get_service_plan_by_date
        existing = get_service_plan_by_date(day)
        plan = existing or get_plan_for_date(day)
        if not plan:
            return _fail("That date has no service. The weekly template decides which days meet.", 400)
        sermon_id = _int_or_none(plan.get("pastoral_sermon_id"))
        if sermon_given:
            raw_sermon = body.get("sermon_id")
            if raw_sermon in (None, "", 0, "0"):
                sermon_id = None
            else:
                try:
                    sermon_id = int(raw_sermon)
                except (TypeError, ValueError):
                    return _fail("sermon_id must be a number.", 400)
                if not _sermon_exists(sermon_id):
                    return _fail("That sermon is not in the builder.", 404)
        before_assignments = _copy_assignments(plan.get("assignments"))
        after_assignments = assignments_with_speaker(
            before_assignments, preacher_id, guest or None, change_speaker,
        )
        before = {"pastoral_sermon_id": _int_or_none(plan.get("pastoral_sermon_id")), "assignments": before_assignments}
        after = {"pastoral_sermon_id": sermon_id, "assignments": after_assignments}
        _write_plan(day, plan, after, int(actor_id))
        saved = get_service_plan_by_date(day) or get_plan_for_date(day)
        card = _lineup_card(saved) if saved else {"date": day}
        return _ok(
            card,
            {
                "action": "lineup.set",
                "target_type": "service_plan",
                "target_id": int(saved["id"]) if saved and saved.get("id") else None,
                "detail": f"{day}",
                "snapshot": {
                    "date": day,
                    "created_override": existing is None,
                    "actor_id": int(actor_id),
                    "before": before,
                    "after": after,
                },
            },
        )
    except Exception as exc:
        print(f"bot lineup set: {exc}")
        return _fail("That lineup could not be saved.", 500, "lineup.set")


def _undo_lineup(plan: str, snapshot: dict):
    day = snapshot.get("date")
    if not day:
        return False, "That lineup change has no date."
    from app.models.pastoral.service_plans import get_plan_for_date, get_service_plan_by_date
    if snapshot.get("created_override") and plan == "restore":
        # Only the dated row this bot added. The weekly template stays.
        _db().cursor().execute("DELETE FROM service_plans WHERE service_date=%s", (day,))
        return True, "Removed that one-day lineup change. The weekly plan is back."
    side = snapshot.get("before") if plan == "restore" else snapshot.get("after")
    if not isinstance(side, dict):
        return False, "That lineup change has nothing to restore."
    current = get_service_plan_by_date(day) or get_plan_for_date(day)
    if not current:
        return False, "That date has no service to put the speaker back on."
    actor = _int_or_none(snapshot.get("actor_id")) or _int_or_none(current.get("created_by"))
    if not actor:
        return False, "That lineup change has no owner to save under."
    _write_plan(day, current, side, actor)
    if plan == "restore":
        return True, "Put the previous speaker and sermon back for that day."
    return True, "Applied that lineup change again."

