"""Sermon drafts and soft undo for the church bot.

The illustration library, research vault, verses, and lineup live in
bot_sermon_library. This module is what the bot routes call.
"""

from __future__ import annotations

import html

from app.utils.bot_sermon_common import (
    HIDE_SNAPSHOT_KEY,
    HIDE_TABLES,
    SECTION_FIELDS,
    SECTION_TYPES,
    SERMON_FIELDS,
    SERMON_VISIBILITY,
    TEXT_CAP,
    ILLUSTRATION_FIELDS,
    VAULT_FIELDS,
    _blank_name,
    _clip,
    _db,
    _fail,
    _int_or_none,
    _jsonish,
    _like,
    _limit,
    _ok,
    _parse_date,
    _person,
    _plain,
    _sermon_row,
    _too_big,
    _update_fields,
    as_html,
    assignments_with_speaker,
    ensure_soft_columns,
    illustration_visible_sql,
    verse_span,
    visible_sermon_filter,
)
from app.utils.bot_illustration_fields import (
    link_without_section,
    passage_from,
    truthy,
    wants_explicit_insert,
)
from app.utils.bot_sermon_library import (
    create_illustration_item,
    create_vault_item,
    lineup_for,
    list_illustrations,
    list_vault,
    lookup_reference,
    rename_illustration_tags,
    set_lineup,
    download_illustration,
    hide_illustration,
    update_illustration_item,
    update_vault_item,
    _load_verses,
    _undo_illustration_tags,
    _undo_lineup,
)

__all__ = [
    "as_html",
    "assignments_with_speaker",
    "verse_span",
    "apply_undo",
    "create_builder_sermon",
    "create_illustration_item",
    "create_vault_item",
    "lineup_for",
    "list_builder_sermons",
    "list_illustrations",
    "list_vault",
    "lookup_reference",
    "save_section",
    "sermon_detail",
    "set_lineup",
    "update_builder_sermon",
    "update_illustration_item",
    "update_vault_item",
]

def _guard_sermon(sermon_id: int, actor_id: int | None, *, write: bool):
    """Open a draft the assigned person can see. Writes stay on drafts they created."""
    if actor_id:
        from app.models.pastoral.sermons import get_sermon_by_id
        if not get_sermon_by_id(int(sermon_id), int(actor_id)):
            return None, _fail("That sermon is not in the builder.", 404)
    row = _sermon_row(sermon_id)
    if not row:
        return None, _fail("That sermon is not in the builder.", 404)
    if write and actor_id and int(row.get("created_by") or 0) != int(actor_id):
        return None, _fail("That sermon belongs to someone else, so this person cannot change it.", 403)
    return row, None


def list_builder_sermons(search: str, limit, actor_id: int | None = None) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "sermon.list")
    try:
        sql = """
            SELECT ps.id, ps.title, ps.primary_passage, ps.service_date, ps.visibility,
                   ps.preacher_id, ps.created_at,
                   LEFT(IFNULL(ps.notes, ''), 240) AS notes,
                   TRIM(CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.last_name, ''))) AS preacher_name,
                   (SELECT COUNT(*) FROM sermon_sections ss
                    WHERE ss.sermon_id = ps.id AND ss.removed_at IS NULL) AS sections
            FROM pastoral_sermons ps
            LEFT JOIN users p ON p.id = ps.preacher_id
            WHERE ps.removed_at IS NULL
        """
        params = []
        if actor_id:
            frag, extra = visible_sermon_filter(int(actor_id))
            sql += frag
            params.extend(extra)
        if (search or "").strip():
            sql += " AND (ps.title LIKE %s OR ps.primary_passage LIKE %s)"
            like = _like(search)
            params.extend([like, like])
        sql += " ORDER BY ps.created_at DESC, ps.id DESC LIMIT %s"
        params.append(_limit(limit))
        cur = _db().cursor()
        cur.execute(sql, params)
        rows = []
        for row in cur.fetchall() or []:
            item = _plain(row)
            item["preacher_name"] = _blank_name(item.get("preacher_name"))
            item["sections"] = int(row.get("sections") or 0)
            rows.append(item)
        return _ok({"sermons": rows, "count": len(rows)})
    except Exception as exc:
        print(f"bot sermon list: {exc}")
        return _fail("The sermon drafts could not be read.", 500, "sermon.list")


def sermon_detail(sermon_id: int, actor_id: int | None = None) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "sermon.detail")
    try:
        _row, denied = _guard_sermon(sermon_id, actor_id, write=False)
        if denied:
            return denied
        cur = _db().cursor()
        cur.execute(
            """
            SELECT ps.id, ps.title, ps.preacher_id, ps.primary_passage, ps.service_date,
                   ps.visibility, ps.header_text, ps.footer_text, ps.conclusion_text,
                   ps.series_tags, ps.notes, ps.created_by, ps.created_at, ps.updated_at,
                   TRIM(CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.last_name, ''))) AS preacher_name,
                   TRIM(CONCAT(IFNULL(c.first_name, ''), ' ', IFNULL(c.last_name, ''))) AS creator_name
            FROM pastoral_sermons ps
            LEFT JOIN users p ON p.id = ps.preacher_id
            LEFT JOIN users c ON c.id = ps.created_by
            WHERE ps.id=%s AND ps.removed_at IS NULL
            """,
            (int(sermon_id),),
        )
        row = cur.fetchone()
        if not row:
            return _fail("That sermon is not in the builder.", 404)
        cur.execute(
            """
            SELECT id, sort_order, section_type, title, content, scripture_reference,
                   translation, source, notes, illustration_id
            FROM sermon_sections
            WHERE sermon_id=%s AND removed_at IS NULL
            ORDER BY sort_order, id
            """,
            (int(sermon_id),),
        )
        sections = []
        for sec in cur.fetchall() or []:
            item = _plain(sec)
            content = item.get("content") or ""
            if len(content) > TEXT_CAP:
                item["content"] = content[:TEXT_CAP]
                item["content_truncated"] = True
            sections.append(item)
        data = _plain(row)
        data["preacher_name"] = _blank_name(data.get("preacher_name"))
        data["creator_name"] = _blank_name(data.get("creator_name"))
        data["passage"] = data.get("primary_passage")
        data["sections"] = sections
        return _ok(data)
    except Exception as exc:
        print(f"bot sermon detail: {exc}")
        return _fail("That sermon could not be read.", 500, "sermon.detail")


def create_builder_sermon(actor_id: int, body: dict) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "sermon.create")
    title = str((body or {}).get("title") or "").strip()[:500]
    if not title:
        return _fail("A sermon needs a title.", 400)
    visibility = str(body.get("visibility") or "pastoral_group").strip().lower()
    if visibility not in SERMON_VISIBILITY:
        return _fail("visibility must be private, collaborators, or pastoral_group.", 400)
    preacher_id = None
    if body.get("preacher_id") not in (None, "") or body.get("preacher") not in (None, ""):
        preacher_id, perr = _person(body.get("preacher_id") or body.get("preacher"))
        if perr:
            return _fail(perr, 400)
    service_date, derr = _parse_date(body.get("service_date"))
    if derr:
        return _fail(derr, 400)
    passage, passage_set = passage_from(body or {})
    try:
        from app.models.pastoral.sermons import create_sermon
        sermon_id = create_sermon({
            "title": title,
            "preacher_id": preacher_id,
            "primary_passage": _clip(passage, 500) if passage_set else None,
            "service_date": service_date,
            "visibility": visibility,
            "header_text": _clip(body.get("header_text"), TEXT_CAP),
            "footer_text": _clip(body.get("footer_text"), TEXT_CAP),
            "conclusion_text": _clip(body.get("conclusion_text"), TEXT_CAP),
            "series_tags": _clip(body.get("series_tags"), 500),
            "notes": _clip(body.get("notes"), TEXT_CAP),
        }, int(actor_id))
    except Exception as exc:
        print(f"bot sermon create: {exc}")
        return _fail("That sermon could not be saved.", 500, "sermon.create")
    if not sermon_id:
        return _fail("That sermon could not be saved.", 500, "sermon.create")
    return _ok(
        {"sermon_id": int(sermon_id), "title": title, "visibility": visibility},
        {
            "action": "sermon.create",
            "target_type": "pastoral_sermon",
            "target_id": int(sermon_id),
            "detail": title,
            "snapshot": {"sermon_id": int(sermon_id)},
        },
    )


def update_builder_sermon(sermon_id: int, body: dict, actor_id: int | None = None) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "sermon.update")
    try:
        row, denied = _guard_sermon(sermon_id, actor_id, write=True)
        if denied:
            return denied
        changes, error = _sermon_changes(body or {}, row)
        if error:
            return _fail(error, 400)
        if not changes:
            return _fail("Send a title, passage, preacher, date, notes, or conclusion to change.", 400)
        before = {key: _jsonish(row.get(key)) for key in changes}
        after = {key: _jsonish(value) for key, value in changes.items()}
        snapshot = {"sermon_id": int(sermon_id), "before": before, "after": after}
        if _too_big(snapshot):
            return _fail("That change is too large to undo, so it was not saved.", 400)
        _update_fields("pastoral_sermons", int(sermon_id), changes, SERMON_FIELDS)
        return _ok(
            {"sermon_id": int(sermon_id), **after},
            {
                "action": "sermon.update",
                "target_type": "pastoral_sermon",
                "target_id": int(sermon_id),
                "detail": str(after.get("title") or row.get("title") or "Sermon")[:180],
                "snapshot": snapshot,
            },
        )
    except Exception as exc:
        print(f"bot sermon update: {exc}")
        return _fail("That sermon could not be saved.", 500, "sermon.update")


def _sermon_changes(body: dict, row: dict):
    changes = {}
    if "title" in body:
        title = str(body.get("title") or "").strip()[:500]
        if not title:
            return None, "A sermon needs a title."
        changes["title"] = title
    if "preacher_id" in body or "preacher" in body:
        token = body.get("preacher_id")
        if token in (None, "") and "preacher" in body:
            token = body.get("preacher")
        if token in (None, ""):
            changes["preacher_id"] = None
        else:
            preacher_id, perr = _person(token)
            if perr:
                return None, perr
            changes["preacher_id"] = preacher_id
    passage, passage_set = passage_from(body)
    if passage_set:
        changes["primary_passage"] = _clip(passage, 500)
    for key, cap in (
        ("header_text", TEXT_CAP),
        ("footer_text", TEXT_CAP),
        ("conclusion_text", TEXT_CAP),
        ("series_tags", 500),
        ("notes", TEXT_CAP),
    ):
        if key in body:
            changes[key] = _clip(body.get(key), cap)
    if "service_date" in body:
        service_date, derr = _parse_date(body.get("service_date"))
        if derr:
            return None, derr
        changes["service_date"] = service_date
    if "visibility" in body:
        visibility = str(body.get("visibility") or "").strip().lower()
        if visibility not in SERMON_VISIBILITY:
            return None, "visibility must be private, collaborators, or pastoral_group."
        changes["visibility"] = visibility
    return changes, None


def save_section(sermon_id: int, body: dict, actor_id: int | None = None) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "section.add")
    try:
        _row, denied = _guard_sermon(sermon_id, actor_id, write=True)
        if denied:
            return denied
        body = body or {}
        if body.get("section_id") not in (None, "", 0, "0"):
            return _update_section(int(sermon_id), body, actor_id)
        refusal = link_without_section(body)
        if refusal:
            return _fail(refusal, 400)
        if wants_explicit_insert(body) and body.get("illustration_id") not in (None, "", 0, "0"):
            return _add_illustration_section(int(sermon_id), body, actor_id)
        if (body.get("reference") or body.get("ref")):
            return _add_verse_section(int(sermon_id), body)
        return _add_text_section(int(sermon_id), body)
    except Exception as exc:
        print(f"bot section: {exc}")
        return _fail("That section could not be saved.", 500, "section.add")


def _section_translation(body: dict) -> str | None:
    if "translation" in (body or {}):
        return _clip(body.get("translation"), 40) or ""
    if "scripture_translation" in (body or {}):
        return _clip(body.get("scripture_translation"), 40) or ""
    return None


def _insert_section(sermon_id, section_type, title, content, scripture_reference, source, notes,
                    illustration_id=None, translation=None):
    cur = _db().cursor()
    cur.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM sermon_sections WHERE sermon_id=%s",
        (int(sermon_id),),
    )
    sort_order = int((cur.fetchone() or {}).get("n") or 1)
    cur.execute(
        """
        INSERT INTO sermon_sections (
            sermon_id, sort_order, section_type, title, content,
            scripture_reference, translation, source, notes, illustration_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            int(sermon_id),
            sort_order,
            section_type,
            title,
            content,
            scripture_reference or "",
            (translation or "")[:40],
            source or "",
            notes or "",
            illustration_id,
        ),
    )
    return int(cur.lastrowid), sort_order


def _section_log(sermon_id, section_id, title, section_type):
    return _ok(
        {
            "sermon_id": int(sermon_id),
            "section_id": int(section_id),
            "section_type": section_type,
            "title": title,
        },
        {
            "action": "section.add",
            "target_type": "sermon_section",
            "target_id": int(section_id),
            "detail": f"{section_type}: {title}"[:180],
            "snapshot": {"section_id": int(section_id), "sermon_id": int(sermon_id)},
        },
    )


def _add_text_section(sermon_id: int, body: dict) -> dict:
    section_type = str(body.get("section_type") or "point").strip().lower()
    if section_type not in SECTION_TYPES:
        return _fail(
            "section_type must be introduction, point, scripture, application, illustration, conclusion, or other.",
            400,
        )
    title = _clip(body.get("title"), 500) or section_type.replace("_", " ").title()
    raw = body.get("content")
    if not str(raw or "").strip() and not str(body.get("title") or "").strip():
        return _fail("A section needs a title or some words.", 400)
    translation = _section_translation(body)
    source = _clip(body.get("source"), 500) or ""
    if translation and "source" not in body and not source:
        source = translation
    section_id, _order = _insert_section(
        sermon_id,
        section_type,
        title,
        as_html(str(raw or "")),
        _clip(body.get("scripture_reference"), 500) or "",
        source,
        _clip(body.get("notes"), TEXT_CAP) or "",
        translation=translation or "",
    )
    return _section_log(sermon_id, section_id, title, section_type)


def _add_illustration_section(sermon_id: int, body: dict, actor_id: int | None = None) -> dict:
    try:
        illus_id = int(body.get("illustration_id"))
    except (TypeError, ValueError):
        return _fail("illustration_id must be a number.", 400)
    cur = _db().cursor()
    sql = """
        SELECT il.id, il.title, il.content, il.source
        FROM illustration_library il
        WHERE il.id=%s AND il.removed_at IS NULL
    """
    params = [illus_id]
    if actor_id:
        frag, extra = illustration_visible_sql(int(actor_id))
        sql += frag
        params.extend(extra)
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        return _fail("That illustration is not in the library.", 404)
    if not truthy(body.get("confirm_reuse")):
        refused = _reuse_block(sermon_id, illus_id, None)
        if refused:
            return refused
    title = _clip(body.get("title"), 500) or row.get("title") or "Illustration"
    translation = _section_translation(body)
    section_id, _order = _insert_section(
        sermon_id,
        "illustration",
        title,
        as_html(row.get("content") or ""),
        _clip(body.get("scripture_reference"), 500) or "",
        row.get("source") or "",
        _clip(body.get("notes"), TEXT_CAP) or "",
        illus_id,
        translation or "",
    )
    return _section_log(sermon_id, section_id, title, "illustration")


def _add_verse_section(sermon_id: int, body: dict) -> dict:
    found = _load_verses(body.get("reference") or body.get("ref"), body.get("translation"))
    if not found.get("ok"):
        return found
    payload = found["data"]
    verses = payload["verses"]
    parts = [f"<p><strong>{html.escape(payload['reference'])}</strong></p>", "<blockquote>"]
    for verse in verses:
        parts.append(f"<p><sup>{int(verse['verse'])}</sup> {html.escape(verse['text'] or '')}</p>")
    parts.append("</blockquote>")
    title = payload["reference"]
    translation = _section_translation(body) or (payload.get("translation") or "")
    section_id, _order = _insert_section(
        sermon_id,
        "scripture",
        title,
        "".join(parts),
        title,
        translation or "",
        "",
        translation=translation or "",
    )
    result = _section_log(sermon_id, section_id, title, "scripture")
    result["data"]["verses"] = verses
    result["data"]["reference"] = title
    result["data"]["translation"] = payload.get("translation")
    return result


def _sermon_campus(sermon_id: int):
    cur = _db().cursor()
    cur.execute("SELECT campus_id FROM pastoral_sermons WHERE id=%s", (int(sermon_id),))
    row = cur.fetchone() or {}
    return row.get("campus_id")


def _reuse_block(sermon_id: int, illus_id: int, section_id: int | None):
    from app.models.pastoral.illustrations import illustration_usage
    used, last_used = illustration_usage(
        int(illus_id),
        campus_id=_sermon_campus(sermon_id),
        exclude_section_id=section_id,
    )
    if not used:
        return None
    return _fail(
        "This illustration was already used with this church.",
        409,
        data={"used_in": used[:20], "last_used": last_used, "illustration_id": int(illus_id)},
        code="already_used",
    )


def _link_fields(sermon_id: int, section_id: int, body: dict, actor_id: int | None = None):
    """Return illustration_id changes, or an error result. Absent means the link was not sent."""
    if truthy(body.get("unlink")) or str(body.get("illustration_id") or "").strip().lower() == "unlink":
        return {"illustration_id": None}, None
    if "illustration_id" not in body:
        return {}, None
    raw = body.get("illustration_id")
    if raw in (None, "", 0, "0"):
        return {"illustration_id": None}, None
    try:
        illus_id = int(raw)
    except (TypeError, ValueError):
        return None, _fail("illustration_id must be a number.", 400)
    cur = _db().cursor()
    sql = """
        SELECT il.id
        FROM illustration_library il
        WHERE il.id=%s AND il.removed_at IS NULL
    """
    params = [illus_id]
    if actor_id:
        frag, extra = illustration_visible_sql(int(actor_id))
        sql += frag
        params.extend(extra)
    cur.execute(sql, params)
    if not cur.fetchone():
        return None, _fail("That illustration is not in the library.", 404)
    if not truthy(body.get("confirm_reuse")):
        refused = _reuse_block(sermon_id, illus_id, section_id)
        if refused:
            return None, refused
    return {"illustration_id": illus_id}, None


def _update_section(sermon_id: int, body: dict, actor_id: int | None = None) -> dict:
    try:
        section_id = int(body.get("section_id"))
    except (TypeError, ValueError):
        return _fail("section_id must be a number.", 400)
    cur = _db().cursor()
    cur.execute(
        """
        SELECT id, section_type, title, content, scripture_reference, translation, source, notes, illustration_id
        FROM sermon_sections
        WHERE id=%s AND sermon_id=%s AND removed_at IS NULL
        """,
        (section_id, int(sermon_id)),
    )
    row = cur.fetchone()
    if not row:
        return _fail("That section is not on this sermon.", 404)
    changes, link_error = _link_fields(int(sermon_id), section_id, body, actor_id)
    if link_error:
        return link_error
    if "section_type" in body:
        section_type = str(body.get("section_type") or "").strip().lower()
        if section_type not in SECTION_TYPES:
            return _fail(
                "section_type must be introduction, point, scripture, application, illustration, conclusion, or other.",
                400,
            )
        changes["section_type"] = section_type
    if "title" in body:
        changes["title"] = _clip(body.get("title"), 500) or ""
    if "content" in body:
        changes["content"] = as_html(str(body.get("content") or ""))
    if "scripture_reference" in body:
        changes["scripture_reference"] = _clip(body.get("scripture_reference"), 500) or ""
    translation = _section_translation(body)
    if translation is not None:
        changes["translation"] = translation
        if "source" not in body and not str(row.get("source") or "").strip():
            changes["source"] = translation
    if "source" in body:
        changes["source"] = _clip(body.get("source"), 500) or ""
    if "notes" in body:
        changes["notes"] = _clip(body.get("notes"), TEXT_CAP) or ""
    if not changes:
        return _fail("Send the words to change on that section.", 400)
    before = {key: _jsonish(row.get(key)) for key in changes}
    after = {key: _jsonish(value) for key, value in changes.items()}
    snapshot = {"section_id": section_id, "sermon_id": int(sermon_id), "before": before, "after": after}
    if _too_big(snapshot):
        return _fail("That change is too large to undo, so it was not saved.", 400)
    _update_fields("sermon_sections", section_id, changes, SECTION_FIELDS)
    return _ok(
        {"sermon_id": int(sermon_id), "section_id": section_id, **after},
        {
            "action": "section.update",
            "target_type": "sermon_section",
            "target_id": section_id,
            "detail": str(after.get("title") or row.get("title") or "Section")[:180],
            "snapshot": snapshot,
        },
    )


def link_section(sermon_id: int, body: dict, actor_id: int | None = None) -> dict:
    """Link or unlink an illustration. This never inserts a section."""
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "section.update")
    body = body or {}
    if body.get("section_id") in (None, "", 0, "0"):
        return _fail(
            "Linking an illustration needs a section_id. This call does not add a section.",
            400,
        )
    _row, denied = _guard_sermon(sermon_id, actor_id, write=True)
    if denied:
        return denied
    if "illustration_id" not in body and not truthy(body.get("unlink")):
        return _fail("Send illustration_id to link, or unlink true to clear the link.", 400)
    slim = {"section_id": body.get("section_id")}
    if "illustration_id" in body:
        slim["illustration_id"] = body.get("illustration_id")
    if "unlink" in body:
        slim["unlink"] = body.get("unlink")
    if "confirm_reuse" in body:
        slim["confirm_reuse"] = body.get("confirm_reuse")
    return _update_section(int(sermon_id), slim, actor_id)


def save_section_as_illustration(sermon_id: int, body: dict, actor_id: int | None = None) -> dict:
    """Copy one section into the illustration library and link it."""
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "illustration.create")
    body = body or {}
    if body.get("section_id") in (None, "", 0, "0"):
        return _fail("Saving a section as an illustration needs a section_id.", 400)
    if not actor_id:
        return _fail("This key has no person assigned, so it cannot save an illustration.", 400)
    try:
        _row, denied = _guard_sermon(sermon_id, actor_id, write=True)
        if denied:
            return denied
        try:
            section_id = int(body.get("section_id"))
        except (TypeError, ValueError):
            return _fail("section_id must be a number.", 400)
        cur = _db().cursor()
        cur.execute(
            """
            SELECT id, title, content, scripture_reference, translation, source, notes
            FROM sermon_sections
            WHERE id=%s AND sermon_id=%s AND removed_at IS NULL
            """,
            (section_id, int(sermon_id)),
        )
        row = cur.fetchone()
        if not row:
            return _fail("That section is not on this sermon.", 404)
        content = str(row.get("content") or "").strip()
        title = str(body.get("title") or row.get("title") or "").strip()
        if not title or not content:
            return _fail("That section needs a title and some words to save as an illustration.", 400)
        created = create_illustration_item(int(actor_id), {
            "title": title,
            "content": content[:TEXT_CAP],
            "source": body.get("source") if "source" in body else row.get("source"),
            "notes": body.get("notes") if "notes" in body else row.get("notes"),
            "tags": body.get("tags"),
            "scripture_reference": body.get("scripture_reference") if "scripture_reference" in body else row.get("scripture_reference"),
            "translation": body.get("translation") if "translation" in body else row.get("translation"),
            "fact_check": body.get("fact_check") if "fact_check" in body else body.get("fact"),
            "kind": body.get("kind"),
            "visibility": body.get("visibility") or "private",
            "confirm_duplicate": body.get("confirm_duplicate"),
        })
        if not created.get("ok"):
            return created
        illus_id = int(created["data"]["illustration_id"])
        cur.execute(
            "UPDATE sermon_sections SET illustration_id=%s WHERE id=%s AND sermon_id=%s",
            (illus_id, section_id, int(sermon_id)),
        )
        created["data"]["section_id"] = section_id
        created["data"]["sermon_id"] = int(sermon_id)
        snapshot = (created.get("log") or {}).get("snapshot") or {}
        snapshot["section_id"] = section_id
        snapshot["sermon_id"] = int(sermon_id)
        snapshot["illustration_id"] = illus_id
        if created.get("log"):
            created["log"]["snapshot"] = snapshot
        return created
    except Exception as exc:
        print(f"bot save section illustration: {exc}")
        return _fail("That section could not be saved as an illustration.", 500, "illustration.create")


def hide_builder_sermon(sermon_id: int, actor_id: int | None) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "sermon.hide")
    try:
        row, denied = _guard_sermon(sermon_id, actor_id, write=True)
        if denied:
            return denied
        cur = _db().cursor()
        cur.execute(
            "UPDATE pastoral_sermons SET removed_at=NOW() WHERE id=%s AND removed_at IS NULL",
            (int(sermon_id),),
        )
        title = str(row.get("title") or "Sermon")[:180]
        return _ok(
            {"sermon_id": int(sermon_id), "hidden": True, "title": title},
            {
                "action": "sermon.hide",
                "target_type": "pastoral_sermon",
                "target_id": int(sermon_id),
                "detail": title,
                "snapshot": {"sermon_id": int(sermon_id)},
            },
        )
    except Exception as exc:
        print(f"bot sermon hide: {exc}")
        return _fail("That sermon could not be hidden.", 500, "sermon.hide")


def hide_section(sermon_id: int, body: dict, actor_id: int | None) -> dict:
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "section.hide")
    try:
        _row, denied = _guard_sermon(sermon_id, actor_id, write=True)
        if denied:
            return denied
        try:
            section_id = int((body or {}).get("section_id"))
        except (TypeError, ValueError):
            return _fail("section_id must be a number.", 400)
        cur = _db().cursor()
        cur.execute(
            """
            SELECT id, title, section_type
            FROM sermon_sections
            WHERE id=%s AND sermon_id=%s AND removed_at IS NULL
            """,
            (section_id, int(sermon_id)),
        )
        sec = cur.fetchone()
        if not sec:
            return _fail("That section is not on this sermon.", 404)
        cur.execute(
            "UPDATE sermon_sections SET removed_at=NOW() WHERE id=%s AND removed_at IS NULL",
            (section_id,),
        )
        title = str(sec.get("title") or sec.get("section_type") or "Section")[:180]
        return _ok(
            {"sermon_id": int(sermon_id), "section_id": section_id, "hidden": True},
            {
                "action": "section.hide",
                "target_type": "sermon_section",
                "target_id": section_id,
                "detail": title,
                "snapshot": {"section_id": section_id, "sermon_id": int(sermon_id)},
            },
        )
    except Exception as exc:
        print(f"bot section hide: {exc}")
        return _fail("That section could not be hidden.", 500, "section.hide")


def reorder_sections(sermon_id: int, body: dict, actor_id: int | None) -> dict:
    """Put every live section of a draft this person created into a new order."""
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, "section.reorder")
    try:
        _row, denied = _guard_sermon(sermon_id, actor_id, write=True)
        if denied:
            return denied
        raw_ids = (body or {}).get("ids")
        if raw_ids is None:
            raw_ids = (body or {}).get("section_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            return _fail("Send ids as a list of every section on this sermon.", 400)
        try:
            wanted = [int(item) for item in raw_ids]
        except (TypeError, ValueError):
            return _fail("Each section id must be a number.", 400)
        if len(wanted) != len(set(wanted)):
            return _fail("Each section id can appear only once.", 400)
        cur = _db().cursor()
        cur.execute(
            """
            SELECT id, sort_order
            FROM sermon_sections
            WHERE sermon_id=%s AND removed_at IS NULL
            ORDER BY sort_order, id
            """,
            (int(sermon_id),),
        )
        rows = cur.fetchall() or []
        current = [int(row["id"]) for row in rows]
        if sorted(wanted) != sorted(current):
            return _fail("Send every section id for this sermon, in the new order.", 400)
        before = [{"id": int(row["id"]), "sort_order": int(row.get("sort_order") or 0)} for row in rows]
        after = [{"id": section_id, "sort_order": index} for index, section_id in enumerate(wanted, start=1)]
        for item in after:
            cur.execute(
                "UPDATE sermon_sections SET sort_order=%s WHERE id=%s AND sermon_id=%s",
                (item["sort_order"], item["id"], int(sermon_id)),
            )
        return _ok(
            {"sermon_id": int(sermon_id), "ids": wanted},
            {
                "action": "section.reorder",
                "target_type": "pastoral_sermon",
                "target_id": int(sermon_id),
                "detail": "Reordered sections",
                "snapshot": {"sermon_id": int(sermon_id), "before": before, "after": after},
            },
        )
    except Exception as exc:
        print(f"bot section reorder: {exc}")
        return _fail("Those sections could not be reordered.", 500, "section.reorder")


def _apply_section_order(plan: str, snapshot: dict):
    side = snapshot.get("before") if plan == "restore" else snapshot.get("after")
    sermon_id = snapshot.get("sermon_id")
    if not sermon_id or not isinstance(side, list) or not side:
        return False, "That change has nothing to put back."
    cur = _db().cursor()
    for item in side:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        cur.execute(
            "UPDATE sermon_sections SET sort_order=%s WHERE id=%s AND sermon_id=%s",
            (int(item.get("sort_order") or 0), int(item["id"]), int(sermon_id)),
        )
    if plan == "restore":
        return True, "Put the previous order back."
    return True, "Applied that order again."


def _relink_saved_section(plan: str, snapshot: dict) -> None:
    section_id = snapshot.get("section_id")
    illus_id = snapshot.get("illustration_id")
    if not section_id or not illus_id:
        return
    cur = _db().cursor()
    if plan == "hide":
        cur.execute(
            "UPDATE sermon_sections SET illustration_id=NULL WHERE id=%s AND illustration_id=%s",
            (int(section_id), int(illus_id)),
        )
        return
    cur.execute(
        "UPDATE sermon_sections SET illustration_id=%s WHERE id=%s",
        (int(illus_id), int(section_id)),
    )


def _set_removed(table: str, row_id: int, hide: bool):
    cur = _db().cursor()
    cur.execute(f"SELECT id FROM {table} WHERE id=%s", (int(row_id),))
    if not cur.fetchone():
        return False, "That item is already gone."
    if hide:
        cur.execute(f"UPDATE {table} SET removed_at=NOW() WHERE id=%s", (int(row_id),))
        return True, "Hid that. The words are still saved."
    cur.execute(f"UPDATE {table} SET removed_at=NULL WHERE id=%s", (int(row_id),))
    return True, "Put that back."


def _restore_fields(table: str, row_id, snapshot: dict, plan: str, allowed: tuple[str, ...]):
    side = snapshot.get("before") if plan == "restore" else snapshot.get("after")
    if not row_id or not isinstance(side, dict):
        return False, "That change has nothing to put back."
    fields = {key: side.get(key) for key in allowed if key in side}
    if not fields:
        return False, "That change has nothing to put back."
    cur = _db().cursor()
    cur.execute(f"SELECT id FROM {table} WHERE id=%s", (int(row_id),))
    if not cur.fetchone():
        return False, "That item is already gone."
    _update_fields(table, int(row_id), fields, allowed)
    if plan == "restore":
        return True, "Put the previous words back."
    return True, "Applied that change again."


def apply_undo(plan: str, entry: dict):
    """Hide, restore, or put back one logged sermon-desk change."""
    problem = ensure_soft_columns()
    if problem:
        return False, problem
    action = (entry or {}).get("action") or ""
    snapshot = entry.get("snapshot") or {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    try:
        if action in HIDE_TABLES:
            row_id = entry.get("target_id") or snapshot.get(HIDE_SNAPSHOT_KEY.get(action) or "")
            if not row_id:
                return False, "That entry has nothing to hide or put back."
            ok, message = _set_removed(HIDE_TABLES[action], int(row_id), plan == "hide")
            if ok and action == "illustration.create" and snapshot.get("section_id"):
                _relink_saved_section(plan, snapshot)
            return ok, message
        if action == "illustration.tags":
            return _undo_illustration_tags(plan, snapshot)
        if action == "section.reorder":
            return _apply_section_order(plan, snapshot)
        if action == "sermon.update":
            return _restore_fields(
                "pastoral_sermons",
                snapshot.get("sermon_id") or entry.get("target_id"),
                snapshot,
                plan,
                SERMON_FIELDS,
            )
        if action == "section.update":
            return _restore_fields(
                "sermon_sections",
                snapshot.get("section_id") or entry.get("target_id"),
                snapshot,
                plan,
                SECTION_FIELDS,
            )
        if action == "illustration.update":
            return _restore_fields(
                "illustration_library",
                snapshot.get("illustration_id") or entry.get("target_id"),
                snapshot,
                plan,
                ILLUSTRATION_FIELDS,
            )
        if action == "vault.update":
            return _restore_fields(
                "pastoral_vault",
                snapshot.get("vault_id") or entry.get("target_id"),
                snapshot,
                plan,
                VAULT_FIELDS,
            )
        if action == "lineup.set":
            return _undo_lineup(plan, snapshot)
    except Exception as exc:
        print(f"bot sermon undo: {exc}")
        return False, "That change could not be undone."
    return False, "That entry cannot be reversed."
