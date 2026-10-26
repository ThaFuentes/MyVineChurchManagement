"""Sermon Builder calls the church bot was still missing.

Routes stay thin. This module checks the draft, writes a row, and returns
a log the bot access route stores. It does not turn a switch on.
"""

from __future__ import annotations

import json

from app.utils.bot_guard import confirm_delete
from app.utils.bot_sermon_common import (
    SECTION_BODY_CAP,
    TEXT_CAP,
    _clip,
    _db,
    _fail,
    _int_or_none,
    _jsonish,
    _limit,
    _ok,
    _person,
    _plain,
    ensure_soft_columns,
    normalize_section_list,
    section_html,
    user_role,
)
from app.utils.bot_illustration_fields import truthy
from app.utils.bot_sermons import (
    _DEFAULT_FOOTER,
    _DEFAULT_HEADER,
    _default_header_footer,
    _guard_sermon,
    create_builder_sermon,
    save_section,
    sermon_detail,
)

_AI_TOOLS = ("generate_outline", "expand_point", "suggest_questions")
_RESEARCH_STATUS = ("open", "assigned", "done")
_BULK_ACTIONS = ("hide", "unhide", "delete", "tag")


def _audit(action: str, target_type: str, target_id, detail: str, snapshot: dict) -> dict:
    return {
        "action": action[:40],
        "target_type": target_type,
        "target_id": int(target_id) if target_id else None,
        "detail": str(detail or "")[:180],
        "snapshot": snapshot,
    }


def _ready(action: str):
    problem = ensure_soft_columns()
    if problem:
        return _fail(problem, 500, action)
    return None


def _owns(sermon_id: int, actor_id: int, action: str):
    row, denied = _guard_sermon(sermon_id, actor_id, write=True)
    if denied:
        denied["action"] = action
        return None, denied
    return row, None


def _owns_any(sermon_id: int, actor_id: int, action: str):
    """Own a draft even after it was hidden, so unhide and hard delete can see it."""
    cur = _db().cursor()
    cur.execute(
        "SELECT id, created_by, removed_at FROM pastoral_sermons WHERE id=%s",
        (int(sermon_id),),
    )
    row = cur.fetchone()
    if not row:
        return None, _fail("That sermon is not in the builder.", 404, action)
    if int(row.get("created_by") or 0) != int(actor_id):
        return None, _fail(
            "That sermon belongs to someone else, so this person cannot change it.",
            403,
            action,
        )
    return row, None


def is_staff(user_id: int) -> bool:
    if user_role(int(user_id)) in ("Owner", "Admin"):
        return True
    cur = _db().cursor()
    cur.execute(
        """
        SELECT 1
        FROM user_groups ug
        JOIN groups g ON g.id = ug.group_id
        WHERE ug.user_id=%s AND (g.name='Pastoral Group' OR g.system_key='pastoral')
        LIMIT 1
        """,
        (int(user_id),),
    )
    return cur.fetchone() is not None


def list_collaborators(sermon_id: int, actor_id: int) -> dict:
    blocked = _ready("bot_sermon_collab_list")
    if blocked:
        return blocked
    _row, denied = _guard_sermon(sermon_id, actor_id, write=False)
    if denied:
        return denied
    from app.models.pastoral.sermons import get_collaborators
    rows = []
    for row in get_collaborators(int(sermon_id)) or []:
        rows.append({
            "user_id": _int_or_none(row.get("id")),
            "username": row.get("username"),
            "name": (row.get("full_name") or "").strip() or None,
        })
    return _ok({"sermon_id": int(sermon_id), "collaborators": rows, "count": len(rows)})


def add_collaborator(sermon_id: int, body: dict, actor_id: int) -> dict:
    action = "bot_sermon_collab_add"
    blocked = _ready(action)
    if blocked:
        return blocked
    _row, denied = _owns(sermon_id, actor_id, action)
    if denied:
        return denied
    user_id, err = _person((body or {}).get("user_id") or (body or {}).get("collaborator_id"))
    if err or not user_id:
        return _fail(err or "Send user_id for the collaborator.", 400, action)
    if int(user_id) == int(actor_id):
        return _fail("The author is already on this sermon.", 400, action)
    if not is_staff(int(user_id)):
        return _fail("A collaborator must be staff.", 400, action)
    from app.models.pastoral.sermons import add_collaborator as _add
    _add(int(sermon_id), int(user_id), int(actor_id))
    return _ok(
        {"sermon_id": int(sermon_id), "user_id": int(user_id)},
        _audit(action, "sermon_collaborator", user_id, f"sermon {sermon_id}", {
            "sermon_id": int(sermon_id), "user_id": int(user_id),
        }),
    )


def remove_collaborator(sermon_id: int, user_id: int, actor_id: int) -> dict:
    action = "bot_sermon_collab_remove"
    blocked = _ready(action)
    if blocked:
        return blocked
    _row, denied = _owns(sermon_id, actor_id, action)
    if denied:
        return denied
    from app.models.pastoral.sermons import remove_collaborator as _remove
    _remove(int(sermon_id), int(user_id))
    return _ok(
        {"sermon_id": int(sermon_id), "user_id": int(user_id), "removed": True},
        _audit(action, "sermon_collaborator", user_id, f"sermon {sermon_id}", {
            "sermon_id": int(sermon_id), "user_id": int(user_id),
        }),
    )


def sermon_defaults(actor_id: int, body: dict | None, write: bool) -> dict:
    action = "bot_sermon_defaults"
    blocked = _ready(action)
    if blocked:
        return blocked
    current = _default_header_footer(int(actor_id))
    if not write:
        return _ok({"header": current.get("header") or "", "footer": current.get("footer") or ""})
    body = body or {}
    if "header" not in body and "footer" not in body:
        return _fail("Send header, footer, or both. This is the only call that changes the defaults.", 400, action)
    saved = {}
    if "header" in body:
        saved["header"] = _save_default(actor_id, _DEFAULT_HEADER, body.get("header"))
    if "footer" in body:
        saved["footer"] = _save_default(actor_id, _DEFAULT_FOOTER, body.get("footer"))
    return _ok(
        saved,
        _audit(action, "sermon_defaults", actor_id, "header and footer", {"user_id": int(actor_id)}),
    )


def _save_default(actor_id: int, title: str, content) -> dict:
    text = section_html(str(content or ""))
    cur = _db().cursor()
    cur.execute(
        """
        SELECT id FROM illustration_library
        WHERE title=%s AND user_id=%s AND removed_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        (title, int(actor_id)),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE illustration_library SET content=%s WHERE id=%s AND title=%s",
            (text, int(row["id"]), title),
        )
        return {"illustration_id": int(row["id"]), "title": title, "updated": True}
    cur.execute(
        """
        INSERT INTO illustration_library (user_id, title, content, source, tags, notes)
        VALUES (%s, %s, %s, NULL, %s, NULL)
        """,
        (int(actor_id), title, text, "[]"),
    )
    return {"illustration_id": int(cur.lastrowid), "title": title, "created": True}


def _template_row(template_id: int, actor_id: int):
    cur = _db().cursor()
    cur.execute(
        "SELECT id, name, user_id, structure, created_at FROM sermon_templates WHERE id=%s",
        (int(template_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    owner = row.get("user_id")
    if owner not in (None, int(actor_id)) and int(owner or 0) != int(actor_id):
        return None
    return row


def list_templates(actor_id: int, template_id: int | None = None) -> dict:
    blocked = _ready("bot_sermon_template_list")
    if blocked:
        return blocked
    cur = _db().cursor()
    if template_id:
        row = _template_row(template_id, actor_id)
        if not row:
            return _fail("That sermon template was not found.", 404)
        sections, _err = normalize_section_list(row.get("structure"))
        item = _plain(row)
        item["sections"] = sections or []
        return _ok(item)
    cur.execute(
        """
        SELECT id, name, user_id, created_at
        FROM sermon_templates
        WHERE user_id=%s OR user_id IS NULL
        ORDER BY id DESC
        LIMIT 100
        """,
        (int(actor_id),),
    )
    rows = [_plain(row) for row in cur.fetchall() or []]
    return _ok({"templates": rows, "count": len(rows)})


def save_template(actor_id: int, body: dict, template_id: int | None = None) -> dict:
    action = "bot_sermon_template_save"
    blocked = _ready(action)
    if blocked:
        return blocked
    body = body or {}
    sections, err = normalize_section_list(body.get("sections") or body.get("structure") or [])
    if err:
        return _fail(err, 400, action)
    name = _clip(body.get("name") or body.get("title"), 200)
    if template_id:
        row = _template_row(template_id, actor_id)
        if not row:
            return _fail("That sermon template was not found.", 404, action)
        name = name or _clip(row.get("name"), 200) or "Sermon template"
        cur = _db().cursor()
        cur.execute(
            "UPDATE sermon_templates SET name=%s, structure=%s WHERE id=%s",
            (name, json.dumps(sections), int(template_id)),
        )
        saved_id = int(template_id)
    else:
        if not name:
            return _fail("A template needs a name.", 400, action)
        cur = _db().cursor()
        cur.execute(
            "INSERT INTO sermon_templates (name, user_id, structure) VALUES (%s, %s, %s)",
            (name, int(actor_id), json.dumps(sections)),
        )
        saved_id = int(cur.lastrowid)
    return _ok(
        {"template_id": saved_id, "name": name, "sections": len(sections)},
        _audit(action, "sermon_template", saved_id, name, {"template_id": saved_id}),
    )


def delete_template(actor_id: int, template_id: int, body: dict) -> dict:
    action = "bot_sermon_template_delete"
    blocked = _ready(action)
    if blocked:
        return blocked
    row = _template_row(template_id, actor_id)
    if not row:
        return _fail("That sermon template was not found.", 404, action)
    _wants, err = confirm_delete(body or {}, int(template_id))
    if err or not _wants:
        return _fail(err or f'Send confirm as "DELETE {int(template_id)}".', 400, action)
    cur = _db().cursor()
    cur.execute("DELETE FROM sermon_templates WHERE id=%s", (int(template_id),))
    return _ok(
        {"template_id": int(template_id), "deleted": True},
        _audit(action, "sermon_template", template_id, row.get("name") or "template", {
            "template_id": int(template_id), "name": row.get("name"),
        }),
    )


def refresh_template(actor_id: int, template_id: int, body: dict) -> dict:
    """Copy section types and titles from a sermon onto the template. Bodies stay on the sermon."""
    action = "bot_sermon_template_refresh"
    blocked = _ready(action)
    if blocked:
        return blocked
    row = _template_row(template_id, actor_id)
    if not row:
        return _fail("That sermon template was not found.", 404, action)
    sermon_id = _int_or_none((body or {}).get("sermon_id"))
    if not sermon_id:
        sections, _err = normalize_section_list(row.get("structure"))
        return _ok({"template_id": int(template_id), "sections": sections or [], "refreshed": False})
    _owned, denied = _owns(sermon_id, actor_id, action)
    if denied:
        return denied
    cur = _db().cursor()
    cur.execute(
        """
        SELECT section_type, title
        FROM sermon_sections
        WHERE sermon_id=%s AND removed_at IS NULL
        ORDER BY sort_order, id
        """,
        (int(sermon_id),),
    )
    sections = [
        {"section_type": item.get("section_type") or "point", "title": item.get("title") or "", "content": ""}
        for item in cur.fetchall() or []
    ]
    cur.execute(
        "UPDATE sermon_templates SET structure=%s WHERE id=%s",
        (json.dumps(sections), int(template_id)),
    )
    return _ok(
        {"template_id": int(template_id), "sermon_id": int(sermon_id), "sections": len(sections), "refreshed": True},
        _audit(action, "sermon_template", template_id, f"from sermon {sermon_id}", {
            "template_id": int(template_id), "sermon_id": int(sermon_id),
        }),
    )


def plan_assignments(plan_id: int, body: dict | None, write: bool) -> dict:
    action = "bot_sermon_assignment"
    blocked = _ready(action)
    if blocked:
        return blocked
    from app.models.pastoral.service_plans import get_service_plan_assignments, save_service_plan_assignments
    cur = _db().cursor()
    cur.execute("SELECT id FROM service_plans WHERE id=%s", (int(plan_id),))
    if not cur.fetchone():
        return _fail("That service plan was not found.", 404, action)
    if not write:
        rows = []
        for row in get_service_plan_assignments(int(plan_id)) or []:
            rows.append({
                "role_name": row.get("role_name"),
                "user_id": _int_or_none(row.get("user_id")),
                "guest_name": row.get("guest_name"),
                "name": (row.get("user_full_name") or "").strip() or None,
            })
        return _ok({"plan_id": int(plan_id), "assignments": rows})
    body = body or {}
    if truthy(body.get("clear")):
        incoming = []
    else:
        incoming = body.get("assignments")
        if not isinstance(incoming, list):
            return _fail("Send assignments as a list, or clear true.", 400, action)
    clean = []
    for item in incoming:
        if not isinstance(item, dict):
            return _fail("Each assignment needs a role_name.", 400, action)
        role = str(item.get("role_name") or "").strip()
        if not role:
            continue
        clean.append({
            "role_name": role[:80],
            "user_id": _int_or_none(item.get("user_id")),
            "guest_name": _clip(item.get("guest_name"), 120),
        })
    try:
        save_service_plan_assignments(int(plan_id), clean)
    except Exception as exc:
        print(f"bot assignments: {exc}")
        return _fail("Those assignments could not be saved.", 500, action)
    return _ok(
        {"plan_id": int(plan_id), "count": len(clean)},
        _audit(action, "service_plan", plan_id, f"{len(clean)} roles", {
            "table": "service_plans", "id": int(plan_id), "count": len(clean),
        }),
    )


def list_notes(actor_id: int, note_id: int | None = None) -> dict:
    blocked = _ready("bot_sermon_note_list")
    if blocked:
        return blocked
    cur = _db().cursor()
    if note_id:
        cur.execute(
            """
            SELECT id, user_id, sermon_id, body, created_at
            FROM sermon_prep_notes
            WHERE id=%s AND user_id=%s AND removed_at IS NULL
            """,
            (int(note_id), int(actor_id)),
        )
        row = cur.fetchone()
        if not row:
            return _fail("That prep note was not found.", 404)
        return _ok(_plain(row))
    cur.execute(
        """
        SELECT id, sermon_id, LEFT(body, 240) AS body, created_at
        FROM sermon_prep_notes
        WHERE user_id=%s AND removed_at IS NULL
        ORDER BY id DESC
        LIMIT 50
        """,
        (int(actor_id),),
    )
    rows = [_plain(row) for row in cur.fetchall() or []]
    return _ok({"notes": rows, "count": len(rows)})


def save_note(actor_id: int, body: dict, note_id: int | None = None) -> dict:
    action = "bot_sermon_note_save"
    blocked = _ready(action)
    if blocked:
        return blocked
    body = body or {}
    text = str(body.get("body") or body.get("content") or "")[:SECTION_BODY_CAP]
    if not text.strip():
        return _fail("A prep note needs some words.", 400, action)
    sermon_id = _int_or_none(body.get("sermon_id"))
    if sermon_id:
        _row, denied = _guard_sermon(sermon_id, actor_id, write=False)
        if denied:
            return denied
    cur = _db().cursor()
    if note_id:
        cur.execute(
            "SELECT id FROM sermon_prep_notes WHERE id=%s AND user_id=%s AND removed_at IS NULL",
            (int(note_id), int(actor_id)),
        )
        if not cur.fetchone():
            return _fail("That prep note was not found.", 404, action)
        cur.execute(
            "UPDATE sermon_prep_notes SET body=%s, sermon_id=%s WHERE id=%s AND user_id=%s",
            (text, sermon_id, int(note_id), int(actor_id)),
        )
        saved = int(note_id)
    else:
        cur.execute(
            "INSERT INTO sermon_prep_notes (user_id, sermon_id, body) VALUES (%s, %s, %s)",
            (int(actor_id), sermon_id, text),
        )
        saved = int(cur.lastrowid)
    return _ok(
        {"note_id": saved, "sermon_id": sermon_id},
        _audit(action, "sermon_prep_note", saved, "prep note", {"note_id": saved, "user_id": int(actor_id)}),
    )


def delete_note(actor_id: int, note_id: int) -> dict:
    action = "bot_sermon_note_delete"
    blocked = _ready(action)
    if blocked:
        return blocked
    cur = _db().cursor()
    cur.execute(
        "UPDATE sermon_prep_notes SET removed_at=NOW() WHERE id=%s AND user_id=%s AND removed_at IS NULL",
        (int(note_id), int(actor_id)),
    )
    if not cur.rowcount:
        return _fail("That prep note was not found.", 404, action)
    return _ok(
        {"note_id": int(note_id), "hidden": True},
        _audit(action, "sermon_prep_note", note_id, "hidden", {
            "table": "sermon_prep_notes", "id": int(note_id),
        }),
    )


def note_to_illustration(actor_id: int, note_id: int, body: dict) -> dict:
    action = "bot_sermon_note_illustration"
    blocked = _ready(action)
    if blocked:
        return blocked
    cur = _db().cursor()
    cur.execute(
        "SELECT id, body, sermon_id FROM sermon_prep_notes WHERE id=%s AND user_id=%s AND removed_at IS NULL",
        (int(note_id), int(actor_id)),
    )
    row = cur.fetchone()
    if not row:
        return _fail("That prep note was not found.", 404, action)
    from app.utils.bot_sermon_library import create_illustration_item
    payload = body or {}
    created = create_illustration_item(int(actor_id), {
        "title": payload.get("title") or f"Prep note {int(note_id)}",
        "content": row.get("body") or "",
        "source": payload.get("source"),
        "tags": payload.get("tags"),
        "notes": payload.get("notes"),
        "visibility": payload.get("visibility") or "private",
        "confirm_duplicate": payload.get("confirm_duplicate"),
    })
    if not created.get("ok"):
        return created
    illus_id = int(created["data"]["illustration_id"])
    if created.get("log"):
        created["log"]["action"] = action
        snap = created["log"].get("snapshot") or {}
        snap.update({"table": "illustration_library", "id": illus_id, "note_id": int(note_id)})
        created["log"]["snapshot"] = snap
    created["data"]["note_id"] = int(note_id)
    return created


def insert_into_sermon(sermon_id: int, body: dict, actor_id: int) -> dict:
    action = "bot_sermon_insert"
    blocked = _ready(action)
    if blocked:
        return blocked
    body = body or {}
    illus_id = _int_or_none(body.get("illustration_id"))
    note_id = _int_or_none(body.get("note_id"))
    if illus_id and note_id:
        return _fail("Send note_id or illustration_id, not both.", 400, action)
    if illus_id:
        result = save_section(sermon_id, {
            "illustration_id": illus_id,
            "insert": True,
            "confirm_reuse": body.get("confirm_reuse"),
            "title": body.get("title"),
        }, actor_id)
        if result.get("log"):
            result["log"]["action"] = action
        return result
    if not note_id:
        return _fail("Send note_id or illustration_id.", 400, action)
    cur = _db().cursor()
    cur.execute(
        "SELECT body FROM sermon_prep_notes WHERE id=%s AND user_id=%s AND removed_at IS NULL",
        (int(note_id), int(actor_id)),
    )
    row = cur.fetchone()
    if not row:
        return _fail("That prep note was not found.", 404, action)
    result = save_section(sermon_id, {
        "section_type": body.get("section_type") or "point",
        "title": body.get("title") or "Prep note",
        "content": row.get("body") or "",
    }, actor_id)
    if result.get("log"):
        result["log"]["action"] = action
        result["log"]["snapshot"] = {
            **(result["log"].get("snapshot") or {}),
            "note_id": int(note_id),
        }
    return result


def import_sermon(actor_id: int, body: dict, raw: bytes, filename: str) -> dict:
    action = "bot_sermon_import"
    blocked = _ready(action)
    if blocked:
        return blocked
    mode = str((body or {}).get("parse_mode") or "rules").strip().lower()
    if mode not in ("rules", "auto", "ai"):
        return _fail("parse_mode must be rules, auto, or ai.", 400, action)
    if not raw:
        return _fail("Send the sermon as text or a docx file.", 400, action)
    from app.models.pastoral.sermon_import import parse_sermon_document
    try:
        parsed = parse_sermon_document(raw, filename=filename or "sermon.txt", use_ai=mode)
    except Exception as exc:
        print(f"bot sermon import: {exc}")
        return _fail("That file could not be read.", 400, action)
    created = create_builder_sermon(int(actor_id), {
        "title": (body or {}).get("title") or parsed.get("title") or "Imported sermon",
        "primary_passage": parsed.get("primary_passage"),
        "service_date": parsed.get("service_date"),
        "notes": parsed.get("notes"),
        "sections": parsed.get("sections") or [],
        "visibility": (body or {}).get("visibility") or "private",
        "dry_run": (body or {}).get("dry_run"),
    })
    if created.get("ok") and created.get("data") is not None:
        created["data"]["imported"] = True
        created["data"]["parse_mode"] = parsed.get("parse_mode") or mode
    if created.get("log"):
        sermon_id = (created.get("data") or {}).get("sermon_id")
        created["log"]["action"] = action
        snap = created["log"].get("snapshot") or {}
        snap.update({"table": "pastoral_sermons", "id": sermon_id, "sermon_id": sermon_id})
        created["log"]["snapshot"] = snap
    return created


def _sermon_text(data: dict) -> str:
    lines = [str(data.get("title") or "Sermon"), ""]
    if data.get("primary_passage"):
        lines.append(str(data.get("primary_passage")))
    if data.get("service_date"):
        lines.append(str(data.get("service_date"))[:10])
    lines.append("")
    for sec in data.get("sections") or []:
        lines.append(str(sec.get("title") or sec.get("section_type") or "Section"))
        if sec.get("scripture_reference"):
            lines.append(str(sec.get("scripture_reference")))
        content = str(sec.get("content") or "")
        content = content.replace("<br>", "\n").replace("</p>", "\n")
        plain = []
        skip = False
        for char in content:
            if char == "<":
                skip = True
                continue
            if char == ">":
                skip = False
                continue
            if not skip:
                plain.append(char)
        lines.append("".join(plain).strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _pdf_escape(line: str) -> str:
    safe = line.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_bytes(text: str) -> bytes:
    rows = []
    for raw in (text or "").splitlines() or [""]:
        chunk = raw.replace("\t", "    ")
        if not chunk:
            rows.append("")
            continue
        while len(chunk) > 90:
            rows.append(chunk[:90])
            chunk = chunk[90:]
        rows.append(chunk)
    pages = [rows[index:index + 46] for index in range(0, len(rows), 46)] or [[""]]
    page_objs = []
    content_objs = []
    next_id = 3
    kids = []
    for lines in pages:
        content_id = next_id
        page_id = next_id + 1
        next_id += 2
        commands = ["BT", "/F1 11 Tf", "54 750 Td", "14 TL"]
        for line in lines:
            commands.append(f"({_pdf_escape(line)}) Tj")
            commands.append("T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1", "replace")
        content_objs.append((content_id, stream))
        kids.append(page_id)
        page_objs.append(page_id)
    font_id = next_id
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Count {len(kids)} /Kids [{' '.join(f'{kid} 0 R' for kid in kids)}] >>".encode(),
    }
    for content_id, stream in content_objs:
        objects[content_id] = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    for page_id, content_id in zip(page_objs, [item[0] for item in content_objs]):
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        ).encode()
    objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number in range(1, font_id + 1):
        offsets.append(len(out))
        out.extend(f"{number} 0 obj\n".encode())
        out.extend(objects[number])
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {font_id + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(
        f"trailer\n<< /Size {font_id + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def export_sermon(sermon_id: int, actor_id: int, fmt: str) -> dict:
    action = "bot_sermon_export"
    blocked = _ready(action)
    if blocked:
        return blocked
    kind = (fmt or "txt").strip().lower()
    if kind not in ("txt", "docx", "pdf"):
        return _fail("format must be txt, docx, or pdf.", 400, action)
    detail = sermon_detail(int(sermon_id), int(actor_id))
    if not detail.get("ok"):
        return detail
    data = detail["data"]
    title = str(data.get("title") or f"sermon_{sermon_id}")
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in title)[:60] or "sermon"
    text = _sermon_text(data)
    if kind == "txt":
        payload = text.encode("utf-8")
        mime = "text/plain; charset=utf-8"
        filename = f"{safe}.txt"
    elif kind == "docx":
        from app.models.pastoral.content_export import docx_bytes
        from app.routes.pastoral.sermons_export import _generate_sermon_docx
        doc = _generate_sermon_docx(data, data.get("sections") or [])
        payload = docx_bytes(doc).getvalue()
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        filename = f"{safe}.docx"
    else:
        payload = _pdf_bytes(text)
        mime = "application/pdf"
        filename = f"{safe}.pdf"
    result = _ok(
        {"sermon_id": int(sermon_id), "format": kind, "filename": filename},
        _audit(action, "pastoral_sermon", sermon_id, filename, {"sermon_id": int(sermon_id), "format": kind}),
    )
    result["download"] = {
        "bytes": payload,
        "mimetype": mime,
        "disposition": f'attachment; filename="{filename}"',
    }
    return result


def sermon_brief(sermon_id: int, actor_id: int) -> dict:
    detail = sermon_detail(int(sermon_id), int(actor_id))
    if not detail.get("ok"):
        return detail
    data = detail["data"]
    sections = []
    for sec in data.get("sections") or []:
        content = str(sec.get("content") or "")
        sections.append({
            "id": sec.get("id"),
            "section_type": sec.get("section_type"),
            "title": sec.get("title"),
            "scripture_reference": sec.get("scripture_reference"),
            "content_length": len(content),
            "excerpt": content[:240],
        })
    return _ok({
        "sermon_id": int(sermon_id),
        "title": data.get("title"),
        "primary_passage": data.get("primary_passage"),
        "service_date": data.get("service_date"),
        "sections": sections,
    })


def _bulk_ids(body: dict):
    raw = (body or {}).get("ids")
    if isinstance(raw, (int, str)):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        return None, "Send ids as a list of sermon ids."
    if len(raw) > 40:
        return None, "Send 40 sermons or fewer."
    ids = []
    for item in raw:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            return None, "Each sermon id must be a number."
    return ids, None


def bulk_sermons(actor_id: int, body: dict, *, hard_on: bool) -> dict:
    action = "bot_sermon_bulk"
    body = body or {}
    kind = str(body.get("action") or "").strip().lower()
    if kind not in _BULK_ACTIONS:
        return _fail("action must be hide, unhide, delete, or tag.", 400, action)
    ids, err = _bulk_ids(body)
    if err:
        return _fail(err, 400, action)
    wants_hard = kind == "delete" and (
        truthy(body.get("hard")) or str(body.get("confirm") or "").upper().startswith("DELETE")
    )
    if wants_hard and not hard_on:
        out = _fail("Hard delete is turned off for this key.", 403, action)
        out["code"] = "hard_delete"
        out["missing"] = ["hard_delete"]
        return out
    if wants_hard:
        for sermon_id in ids:
            phrase = body.get("confirm")
            confirms = body.get("confirms")
            if isinstance(confirms, dict):
                phrase = confirms.get(str(sermon_id)) or confirms.get(sermon_id)
            _wants, confirm_err = confirm_delete({"confirm": phrase, "hard": True}, sermon_id)
            if confirm_err or not _wants:
                return _fail(confirm_err or f'Send confirm as "DELETE {sermon_id}".', 400, action)
    blocked = _ready(action)
    if blocked:
        return blocked
    from app.utils.bot_content import delete_content, hide_content
    done = []
    for sermon_id in ids:
        if kind in ("unhide", "delete"):
            _row, denied = _owns_any(sermon_id, actor_id, action)
        else:
            _row, denied = _owns(sermon_id, actor_id, action)
        if denied:
            return denied
        if kind == "tag":
            tag = _clip(body.get("tag"), 80)
            if not tag:
                return _fail("Send tag for a tag action.", 400, action)
            cur = _db().cursor()
            cur.execute("SELECT series_tags FROM pastoral_sermons WHERE id=%s", (int(sermon_id),))
            current = str((cur.fetchone() or {}).get("series_tags") or "")
            parts = [part.strip() for part in current.split(",") if part.strip()]
            if tag not in parts:
                parts.append(tag)
            cur.execute(
                "UPDATE pastoral_sermons SET series_tags=%s WHERE id=%s",
                (", ".join(parts)[:500], int(sermon_id)),
            )
            done.append(int(sermon_id))
            continue
        if kind == "delete" and wants_hard:
            phrase = body.get("confirm")
            confirms = body.get("confirms")
            if isinstance(confirms, dict):
                phrase = confirms.get(str(sermon_id)) or confirms.get(sermon_id)
            result = delete_content(
                "pastoral_sermons", sermon_id, {"confirm": phrase, "hard": True}, True,
            )
        else:
            result = hide_content(
                "pastoral_sermons", sermon_id, hide=(kind != "unhide"), action=action,
            )
        if not result.get("ok"):
            return result
        done.append(int(sermon_id))
    logged = f"bot_sermon_bulk_{kind}"
    return _ok(
        {"action": kind, "ids": done, "count": len(done)},
        _audit(logged, "pastoral_sermon", done[0] if len(done) == 1 else None, kind, {
            "ids": done, "action": kind,
        }),
    )


def sermon_ai(sermon_id: int, tool: str, body: dict, actor_id: int) -> dict:
    """Return a suggestion. This does not save the sermon and does not write the change log."""
    name = (tool or "").strip().lower()
    if name not in _AI_TOOLS:
        return _fail("tool must be generate_outline, expand_point, or suggest_questions.", 400, "bot_sermon_ai")
    detail = sermon_detail(int(sermon_id), int(actor_id))
    if not detail.get("ok"):
        return detail
    data = detail["data"]
    pieces = [str(data.get("title") or ""), str(data.get("primary_passage") or "")]
    for sec in data.get("sections") or []:
        pieces.append(str(sec.get("title") or ""))
        pieces.append(str(sec.get("content") or "")[:2000])
    material = "\n".join(part for part in pieces if part).strip()[:12000]
    point = str((body or {}).get("point") or (body or {}).get("content") or "").strip()[:4000]
    if name == "expand_point" and not point:
        return _fail("Send point with the words to expand.", 400, "bot_sermon_ai")
    if name == "generate_outline":
        prompt = (
            "You are a preaching teammate. Use everyday English. "
            "Return only a JSON array of sections with title, type, and content. "
            f"Sermon:\n{material}"
        )
    elif name == "suggest_questions":
        prompt = (
            "Suggest 5 to 8 small-group questions from this sermon. "
            "Return a numbered list only.\n"
            f"{material}"
        )
    else:
        prompt = (
            "Expand this sermon point into 3 to 5 short paragraphs a pastor could adapt. "
            f"Point:\n{point}\n\nSermon:\n{material}"
        )
    try:
        from app.utils.helpers import contains_censored_word
        if contains_censored_word(prompt):
            return _fail("That sermon uses a word the church blocks.", 400, "bot_sermon_ai")
    except Exception:
        pass
    try:
        from app.routes.pastoral.ai_assistant import call_ai
        output, error = call_ai(prompt)
    except Exception as exc:
        print(f"bot sermon ai: {exc}")
        return _fail("Sermon AI is not available right now.", 503, "bot_sermon_ai")
    if error:
        low = str(error).lower()
        status = 503 if any(word in low for word in ("key", "config", "disabled", "not set", "missing")) else 502
        return _fail(str(error), status, "bot_sermon_ai")
    suggestion = output
    try:
        from app.utils.helpers import contains_censored_word
        if contains_censored_word(str(output or "")):
            suggestion = "The suggestion was held back because it used a blocked word."
    except Exception:
        pass
    return _ok({
        "sermon_id": int(sermon_id),
        "tool": name,
        "suggestion": suggestion,
        "saved": False,
    })


def list_series(actor_id: int, series_id: int | None = None) -> dict:
    blocked = _ready("bot_sermon_series_list")
    if blocked:
        return blocked
    from app.models.pastoral.curriculum import get_series, list_series as _list
    if series_id:
        row = get_series(int(series_id))
        if not row:
            return _fail("That series was not found.", 404)
        cur = _db().cursor()
        cur.execute(
            "SELECT sermon_id FROM sermon_series_links WHERE series_id=%s ORDER BY sermon_id",
            (int(series_id),),
        )
        linked = [int(item["sermon_id"]) for item in cur.fetchall() or []]
        return _ok({
            "id": int(row["id"]),
            "title": row.get("title"),
            "status": row.get("status"),
            "sermon_ids": linked,
        })
    rows = []
    for row in _list(limit=50) or []:
        rows.append({
            "id": int(row["id"]),
            "title": row.get("title"),
            "status": row.get("status"),
            "lesson_count": int(row.get("lesson_count") or 0),
        })
    return _ok({"series": rows, "count": len(rows), "user_id": int(actor_id)})


def save_series(actor_id: int, body: dict, series_id: int | None = None) -> dict:
    action = "bot_sermon_series_save"
    blocked = _ready(action)
    if blocked:
        return blocked
    body = body or {}
    from app.models.pastoral.curriculum import create_series, get_series, update_series
    sermon_id = _int_or_none(body.get("sermon_id"))
    if series_id and sermon_id and "title" not in body:
        return link_sermon_series(actor_id, int(series_id), sermon_id, unlink=truthy(body.get("unlink")))
    if series_id:
        if not get_series(int(series_id)):
            return _fail("That series was not found.", 404, action)
        update_series(int(series_id), body)
        saved = int(series_id)
        if sermon_id:
            linked = link_sermon_series(actor_id, saved, sermon_id, unlink=truthy(body.get("unlink")))
            if not linked.get("ok"):
                return linked
    else:
        title = _clip(body.get("title"), 255)
        if not title:
            return _fail("A series needs a title.", 400, action)
        saved = int(create_series({
            "title": title,
            "subtitle": body.get("subtitle"),
            "description": body.get("description"),
            "status": "draft",
            "tags": body.get("tags"),
        }, int(actor_id)))
        if sermon_id:
            linked = link_sermon_series(actor_id, saved, sermon_id, unlink=False)
            if not linked.get("ok"):
                return linked
    return _ok(
        {"series_id": saved, "sermon_id": sermon_id},
        _audit(action, "curriculum_series", saved, _clip(body.get("title"), 180) or "series", {
            "series_id": saved, "sermon_id": sermon_id,
        }),
    )


def link_sermon_series(actor_id: int, series_id: int, sermon_id: int, *, unlink: bool) -> dict:
    action = "bot_sermon_series_link"
    _row, denied = _owns(sermon_id, actor_id, action)
    if denied:
        return denied
    from app.models.pastoral.curriculum import get_series
    if not get_series(int(series_id)):
        return _fail("That series was not found.", 404, action)
    cur = _db().cursor()
    if unlink:
        cur.execute(
            "DELETE FROM sermon_series_links WHERE sermon_id=%s AND series_id=%s",
            (int(sermon_id), int(series_id)),
        )
    else:
        cur.execute(
            """
            INSERT IGNORE INTO sermon_series_links (sermon_id, series_id, created_by)
            VALUES (%s, %s, %s)
            """,
            (int(sermon_id), int(series_id), int(actor_id)),
        )
    return _ok(
        {"series_id": int(series_id), "sermon_id": int(sermon_id), "linked": not unlink},
        _audit(action, "sermon_series_link", sermon_id, f"series {series_id}", {
            "sermon_id": int(sermon_id), "series_id": int(series_id), "linked": not unlink,
        }),
    )


def series_lessons(series_id: int, body: dict | None, write: bool) -> dict:
    action = "bot_sermon_lesson"
    blocked = _ready(action)
    if blocked:
        return blocked
    from app.models.pastoral.curriculum import create_lesson, get_series, list_lessons
    if not get_series(int(series_id)):
        return _fail("That series was not found.", 404, action)
    if not write:
        rows = []
        for row in list_lessons(int(series_id)) or []:
            rows.append({
                "id": int(row["id"]),
                "title": row.get("title"),
                "status": row.get("status"),
                "sort_order": row.get("sort_order"),
            })
        return _ok({"series_id": int(series_id), "lessons": rows})
    body = body or {}
    title = _clip(body.get("title"), 255)
    if not title:
        return _fail("A lesson needs a title.", 400, action)
    lesson_id = int(create_lesson(int(series_id), {
        "title": title,
        "summary": _clip(body.get("summary"), TEXT_CAP),
        "status": "draft",
    }))
    return _ok(
        {"series_id": int(series_id), "lesson_id": lesson_id, "title": title},
        _audit(action, "curriculum_lesson", lesson_id, title, {
            "series_id": int(series_id), "lesson_id": lesson_id,
        }),
    )


def reorder_series_lessons(series_id: int, body: dict) -> dict:
    action = "bot_sermon_lesson_reorder"
    blocked = _ready(action)
    if blocked:
        return blocked
    raw = (body or {}).get("ids") or (body or {}).get("lesson_ids")
    if not isinstance(raw, list) or not raw:
        return _fail("Send ids as the lesson order.", 400, action)
    try:
        ordered = [int(item) for item in raw]
    except (TypeError, ValueError):
        return _fail("Each lesson id must be a number.", 400, action)
    from app.models.pastoral.curriculum import reorder_lessons
    reorder_lessons(int(series_id), ordered)
    return _ok(
        {"series_id": int(series_id), "ids": ordered},
        _audit(action, "curriculum_series", series_id, "reorder", {"series_id": int(series_id), "ids": ordered}),
    )


def research_requests(actor_id: int, body: dict | None, request_id: int | None, write: bool, *, hard_on: bool = False) -> dict:
    action = "bot_sermon_research"
    blocked = _ready(action)
    if blocked:
        return blocked
    cur = _db().cursor()
    if request_id and not write:
        cur.execute(
            """
            SELECT id, title, body, notes, status, assigned_to, sermon_id, created_by, created_at
            FROM bot_research_requests
            WHERE id=%s AND removed_at IS NULL
            """,
            (int(request_id),),
        )
        row = cur.fetchone()
        if not row:
            return _fail("That research request was not found.", 404, action)
        return _ok(_plain(row))
    if not write:
        cur.execute(
            """
            SELECT id, title, status, assigned_to, sermon_id, created_at
            FROM bot_research_requests
            WHERE removed_at IS NULL
            ORDER BY id DESC
            LIMIT %s
            """,
            (_limit((body or {}).get("limit") if isinstance(body, dict) else None),),
        )
        return _ok({"requests": [_plain(row) for row in cur.fetchall() or []]})
    body = body or {}
    if request_id and (truthy(body.get("delete")) or body.get("status") == "delete"):
        return delete_research(actor_id, int(request_id), body, hard_on=hard_on)
    title = _clip(body.get("title"), 255)
    status = str(body.get("status") or "open").strip().lower()
    if status not in _RESEARCH_STATUS:
        return _fail("status must be open, assigned, or done.", 400, action)
    assigned = None
    if body.get("assigned_to") not in (None, ""):
        assigned, err = _person(body.get("assigned_to"))
        if err:
            return _fail(err, 400, action)
    sermon_id = _int_or_none(body.get("sermon_id"))
    notes = _clip(body.get("notes"), TEXT_CAP)
    text = _clip(body.get("body") or body.get("content"), TEXT_CAP)
    if request_id:
        cur.execute(
            "SELECT id, title FROM bot_research_requests WHERE id=%s AND removed_at IS NULL",
            (int(request_id),),
        )
        current = cur.fetchone()
        if not current:
            return _fail("That research request was not found.", 404, action)
        cur.execute(
            """
            UPDATE bot_research_requests
            SET title=COALESCE(%s, title), body=COALESCE(%s, body), notes=COALESCE(%s, notes),
                status=%s, assigned_to=%s, sermon_id=%s
            WHERE id=%s
            """,
            (title, text, notes, status, assigned, sermon_id, int(request_id)),
        )
        saved = int(request_id)
        label = title or current.get("title")
    else:
        if not title:
            return _fail("A research request needs a title.", 400, action)
        cur.execute(
            """
            INSERT INTO bot_research_requests
                (title, body, notes, status, assigned_to, sermon_id, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (title, text, notes, status, assigned, sermon_id, int(actor_id)),
        )
        saved = int(cur.lastrowid)
        label = title
    return _ok(
        {"request_id": saved, "status": status, "assigned_to": assigned},
        _audit(action, "research_request", saved, label or "research", {"request_id": saved}),
    )


def delete_research(actor_id: int, request_id: int, body: dict, *, hard_on: bool = False) -> dict:
    action = "bot_sermon_research_delete"
    wants, err = confirm_delete(body or {}, int(request_id))
    cur = _db().cursor()
    if wants and not hard_on:
        out = _fail("Hard delete is turned off for this key.", 403, action)
        out["code"] = "hard_delete"
        out["missing"] = ["hard_delete"]
        return out
    if wants and err:
        return _fail(err, 400, action)
    if wants:
        cur.execute("DELETE FROM bot_research_requests WHERE id=%s", (int(request_id),))
        if not cur.rowcount:
            return _fail("That research request was not found.", 404, action)
        return _ok(
            {"request_id": int(request_id), "deleted": True},
            _audit(action, "research_request", request_id, "hard delete", {"id": int(request_id), "hard": True}),
        )
    cur.execute(
        "UPDATE bot_research_requests SET removed_at=NOW() WHERE id=%s AND removed_at IS NULL",
        (int(request_id),),
    )
    if not cur.rowcount:
        return _fail("That research request was not found.", 404, action)
    return _ok(
        {"request_id": int(request_id), "hidden": True},
        _audit(action, "research_request", request_id, "hidden", {
            "table": "bot_research_requests", "id": int(request_id),
        }),
    )


def rites(actor_id: int, body: dict | None, rite_id: int | None, write: bool, *, hard_on: bool = False) -> dict:
    action = "bot_sermon_rite"
    from app.models.pastoral.care import delete_rite, get_rite, list_rites, save_rite
    if rite_id and write and (truthy((body or {}).get("delete"))):
        wants, err = confirm_delete(body or {}, int(rite_id))
        if not wants or err:
            return _fail(err or f'Send confirm as "DELETE {int(rite_id)}".', 400, action)
        if not hard_on:
            out = _fail("Hard delete is turned off for this key.", 403, action)
            out["code"] = "hard_delete"
            out["missing"] = ["hard_delete"]
            return out
        if not delete_rite(int(rite_id)):
            return _fail("That rite was not found.", 404, action)
        return _ok(
            {"rite_id": int(rite_id), "deleted": True},
            _audit("bot_sermon_rite_delete", "pastoral_rite", rite_id, "hard delete", {
                "id": int(rite_id), "hard": True,
            }),
        )
    if rite_id and not write:
        row = get_rite(int(rite_id))
        if not row:
            return _fail("That rite was not found.", 404, action)
        return _ok(_plain(row))
    if not write:
        kind = (body or {}).get("kind") if isinstance(body, dict) else None
        rows = []
        for row in list_rites(kind=kind, limit=50) or []:
            rows.append({
                "id": int(row["id"]),
                "kind": row.get("kind"),
                "headline": row.get("headline"),
                "rite_date": _jsonish(row.get("rite_date")),
            })
        return _ok({"rites": rows, "count": len(rows)})
    try:
        saved = int(save_rite(body or {}, int(actor_id), int(rite_id) if rite_id else None))
    except ValueError as exc:
        return _fail(str(exc), 400, action)
    except Exception as exc:
        print(f"bot rite: {exc}")
        return _fail("That rite could not be saved.", 500, action)
    return _ok(
        {"rite_id": saved},
        _audit(action, "pastoral_rite", saved, str((body or {}).get("party_a") or "rite")[:180], {
            "rite_id": saved,
        }),
    )


def bible_chapter(book: str, chapter, translation: str | None) -> dict:
    from app.models.pastoral.bible import normalize_book_name
    name = normalize_book_name(book) or str(book or "").strip()
    if not name:
        return _fail("Send book, as in John.", 400, "bot_bible_chapter")
    try:
        number = int(chapter)
    except (TypeError, ValueError):
        return _fail("chapter must be a number.", 400, "bot_bible_chapter")
    cur = _db().cursor()
    sql = """
        SELECT translation, book, chapter, verse, text
        FROM bible_verses
        WHERE book=%s AND chapter=%s
    """
    params = [name, number]
    trans = str(translation or "").strip()
    if trans:
        sql += " AND translation=%s"
        params.append(trans)
    else:
        sql += " AND translation=(SELECT code FROM bible_translations WHERE is_default=1 LIMIT 1)"
    sql += " ORDER BY verse LIMIT 200"
    try:
        cur.execute(sql, params)
        fetched = cur.fetchall() or []
    except Exception as exc:
        print(f"bot bible chapter: {exc}")
        return _fail("That chapter could not be read.", 500, "bot_bible_chapter")
    rows = [
        {"verse": int(row["verse"]), "text": row.get("text") or ""}
        for row in cur.fetchall() or []
    ]
    if not rows:
        return _fail("That chapter is not in the Bible loaded on this church.", 404, "bot_bible_chapter")
    return _ok({
        "book": name,
        "chapter": number,
        "translation": trans or None,
        "verses": rows,
        "count": len(rows),
    })


def bible_strongs(query: str) -> dict:
    text = str(query or "").strip()
    if not text:
        return _fail("Send q as a Strong's number or a word.", 400, "bot_bible_strongs")
    from app.models.pastoral.bible import get_strongs_entry, search_strongs_lexicon
    if text[:1].upper() in ("G", "H") and text[1:].isdigit():
        row = get_strongs_entry(text)
        if not row:
            return _fail("That Strong's number was not found.", 404, "bot_bible_strongs")
        return _ok(_plain(row))
    rows = [_plain(row) for row in search_strongs_lexicon(text, limit=20) or []]
    return _ok({"matches": rows, "count": len(rows)})


def bible_mark(actor_id: int, body: dict, kind: str) -> dict:
    """Highlights and favorites stay on the account the owner chose."""
    action = "bot_bible_mark"
    body = body or {}
    from app.models.pastoral.bible import normalize_book_name
    book = normalize_book_name(body.get("book")) or str(body.get("book") or "").strip()
    if not book:
        return _fail("Send book.", 400, action)
    try:
        if kind == "highlight":
            from app.models.pastoral.bible_online import save_highlight
            saved = save_highlight(
                int(actor_id),
                str(body.get("translation") or ""),
                book,
                int(body.get("chapter") or 0),
                int(body.get("verse") or body.get("verse_start") or 0),
                int(body.get("verse_end") or body.get("verse") or body.get("verse_start") or 0),
                str(body.get("color") or "yellow"),
            )
        else:
            from app.models.pastoral.bible_online import toggle_favorite
            saved = toggle_favorite(
                int(actor_id),
                str(body.get("scope") or "verse"),
                book,
                int(body.get("chapter") or 0),
                int(body.get("verse") or 0),
                str(body.get("translation") or ""),
                _clip(body.get("text") or body.get("scripture_text"), 500),
            )
    except ValueError as exc:
        return _fail(str(exc), 400, action)
    except Exception as exc:
        print(f"bot bible mark: {exc}")
        return _fail("That Bible mark could not be saved.", 500, action)
    if isinstance(saved, dict):
        saved.pop("user_id", None)
    return _ok(
        {"kind": kind, "user_id": int(actor_id), "saved": _jsonish(saved) if not isinstance(saved, dict) else saved},
        _audit(action, "bible_mark", actor_id, kind, {"user_id": int(actor_id), "kind": kind, "book": book}),
    )


def bible_translation(actor_id: int, body: dict | None, write: bool) -> dict:
    from app.models.pastoral.bible_online import get_user_preferred_translation, set_user_preferred_translation
    if not write:
        return _ok({"translation": get_user_preferred_translation(int(actor_id)), "user_id": int(actor_id)})
    code = _clip((body or {}).get("translation") or (body or {}).get("code"), 40)
    if not code:
        return _fail("Send translation.", 400, "bot_bible_translation")
    saved = set_user_preferred_translation(int(actor_id), code)
    return _ok(
        {"translation": saved, "user_id": int(actor_id)},
        _audit("bot_bible_translation", "user", actor_id, code or "", {"user_id": int(actor_id)}),
    )


def sermon_history(sermon_id: int, actor_id: int, key_id: int) -> dict:
    blocked = _ready("bot_sermon_history")
    if blocked:
        return blocked
    _row, denied = _guard_sermon(sermon_id, actor_id, write=False)
    if denied:
        return denied
    cur = _db().cursor()
    cur.execute(
        """
        SELECT id, user_id, timestamp, change_description
        FROM sermon_edits
        WHERE sermon_id=%s
        ORDER BY id DESC
        LIMIT 40
        """,
        (int(sermon_id),),
    )
    edits = [_plain(row) for row in cur.fetchall() or []]
    cur.execute(
        """
        SELECT id, action, detail, created_at, target_type, target_id
        FROM bot_access_log
        WHERE key_id=%s AND ok=1 AND (
            (target_type='pastoral_sermon' AND target_id=%s)
            OR snapshot_json LIKE %s
        )
        ORDER BY id DESC
        LIMIT 40
        """,
        (int(key_id), int(sermon_id), f'%"sermon_id": {int(sermon_id)}%'),
    )
    logs = [_plain(row) for row in cur.fetchall() or []]
    return _ok({"sermon_id": int(sermon_id), "edits": edits, "log": logs})


def restore_sermon(sermon_id: int, body: dict, actor_id: int, key_id: int) -> dict:
    action = "bot_sermon_restore"
    blocked = _ready(action)
    if blocked:
        return blocked
    _row, denied = _owns(sermon_id, actor_id, action)
    if denied:
        return denied
    log_id = _int_or_none((body or {}).get("log_id"))
    if not log_id:
        return _fail("Send log_id from the sermon history.", 400, action)
    from app.utils import bot_store as store
    from app.utils.bot_policy import undo_plan
    entry = store.get_log(int(log_id))
    if not entry or int(entry.get("key_id") or 0) != int(key_id):
        return _fail("That log entry is not on this key.", 404, action)
    snapshot = entry.get("snapshot") or {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    linked = snapshot.get("sermon_id") or entry.get("target_id")
    try:
        linked = int(linked or 0)
    except (TypeError, ValueError):
        linked = 0
    if linked != int(sermon_id) and int(entry.get("target_id") or 0) != int(sermon_id):
        return _fail("That log entry is for a different sermon.", 400, action)
    plan = undo_plan(entry.get("action") or "", bool(entry.get("reversed")))
    if not plan:
        return _fail("That entry has no saved copy to restore.", 400, action)
    name = entry.get("action") or ""
    if name.startswith("bot_"):
        from app.utils.bot_content import apply_undo
    else:
        from app.utils.bot_sermons import apply_undo
    ok, message = apply_undo(plan, entry)
    if not ok:
        return _fail(message or "That sermon could not be restored.", 400, action)
    store.mark_reversed(int(log_id), str(actor_id), clear=plan in ("show", "reapply"))
    return _ok(
        {"sermon_id": int(sermon_id), "log_id": int(log_id), "restored": True, "message": message},
        _audit(action, "pastoral_sermon", sermon_id, message or "restore", {
            "sermon_id": int(sermon_id), "log_id": int(log_id),
        }),
    )


def unhide_sections(sermon_id: int, body: dict, actor_id: int) -> dict:
    action = "bot_sermon_section_unhide"
    blocked = _ready(action)
    if blocked:
        return blocked
    _row, denied = _owns(sermon_id, actor_id, action)
    if denied:
        return denied
    body = body or {}
    cur = _db().cursor()
    if truthy(body.get("all")):
        cur.execute(
            """
            SELECT id FROM sermon_sections
            WHERE sermon_id=%s AND removed_at IS NOT NULL
            """,
            (int(sermon_id),),
        )
        ids = [int(row["id"]) for row in cur.fetchall() or []]
    else:
        raw = body.get("ids") or body.get("section_ids")
        if raw in (None, "") and body.get("section_id") not in (None, ""):
            raw = [body.get("section_id")]
        if isinstance(raw, (int, str)):
            raw = [raw]
        if not isinstance(raw, list) or not raw:
            return _fail("Send section_id, ids, or all true.", 400, action)
        try:
            ids = [int(item) for item in raw]
        except (TypeError, ValueError):
            return _fail("Each section id must be a number.", 400, action)
    if not ids:
        return _ok({"sermon_id": int(sermon_id), "ids": [], "count": 0})
    marks = ", ".join(["%s"] * len(ids))
    cur.execute(
        f"""
        UPDATE sermon_sections
        SET removed_at=NULL
        WHERE sermon_id=%s AND id IN ({marks})
        """,
        [int(sermon_id), *ids],
    )
    snapshot = {"sermon_id": int(sermon_id), "ids": ids}
    if len(ids) == 1:
        snapshot.update({"table": "sermon_sections", "id": ids[0], "section_id": ids[0]})
    return _ok(
        {"sermon_id": int(sermon_id), "ids": ids, "count": len(ids)},
        _audit(action, "sermon_section", ids[0], "unhide", snapshot),
    )


def notifications_for(actor_id: int, body: dict | None, write: bool) -> dict:
    from app.models.notifications import list_for, mark_all_read, mark_read, unread_count
    if not write:
        rows = []
        for row in list_for(int(actor_id), limit=30) or []:
            item = {
                "id": row.get("id"),
                "type": row.get("type"),
                "actor": row.get("actor"),
                "text": row.get("text"),
                "body": row.get("body"),
                "url": row.get("url") if str(row.get("url") or "").startswith(("/", "http")) else "",
                "unread": row.get("unread"),
                "when": row.get("when"),
            }
            rows.append(item)
        return _ok({"notifications": rows, "unread": unread_count(int(actor_id)), "user_id": int(actor_id)})
    body = body or {}
    if truthy(body.get("all")):
        mark_all_read(int(actor_id))
        return _ok(
            {"user_id": int(actor_id), "read": "all"},
            _audit("bot_notify_read", "notification", actor_id, "all", {"user_id": int(actor_id)}),
        )
    note_id = _int_or_none(body.get("id"))
    if not note_id:
        return _fail("Send id, or all true.", 400, "bot_notify_read")
    mark_read(int(actor_id), int(note_id))
    return _ok(
        {"id": int(note_id), "user_id": int(actor_id), "read": True},
        _audit("bot_notify_read", "notification", note_id, "read", {"id": int(note_id), "user_id": int(actor_id)}),
    )


def media_list(actor_id: int, role: str) -> dict:
    cur = _db().cursor()
    try:
        cur.execute(
            """
            SELECT id, caption, owner_type, owner_id
            FROM page_photos
            ORDER BY id DESC
            LIMIT 100
            """
        )
        fetched = cur.fetchall() or []
    except Exception as exc:
        print(f"bot media: {exc}")
        return _fail("The media list could not be read.", 500, "bot_media_list")
    staff = role in ("Owner", "Admin")
    rows = []
    for row in fetched:
        owner_type = str(row.get("owner_type") or "")
        owner_id = _int_or_none(row.get("owner_id"))
        if owner_type == "member" and owner_id != int(actor_id):
            continue
        if owner_type != "member" and not staff:
            continue
        rows.append({
            "id": int(row["id"]),
            "caption": row.get("caption") or "",
            "owner_type": owner_type,
            "url": f"/church/photos/{int(row['id'])}",
        })
    return _ok({"media": rows, "count": len(rows)})


def add_sermon_comment(sermon_id: int, body: dict, actor_id: int, actor_name: str) -> dict:
    cur = _db().cursor()
    cur.execute("SELECT id, title FROM sermons WHERE id=%s", (int(sermon_id),))
    row = cur.fetchone()
    if not row:
        return _fail(
            "That public sermon was not found. Prep notes for a builder draft use /api/bot/sermon-notes.",
            404,
            "bot_comment_reply",
        )
    cur.execute(
        """
        SELECT TRIM(CONCAT(IFNULL(first_name, ''), ' ', IFNULL(last_name, ''))) AS name
        FROM users WHERE id=%s
        """,
        (int(actor_id),),
    )
    named = ((cur.fetchone() or {}).get("name") or "").strip() or actor_name or "Member"
    from app.utils.bot_comments import reply_comment
    return reply_comment(
        "sermon",
        int(sermon_id),
        str((body or {}).get("body") or (body or {}).get("comment") or ""),
        {"user_id": int(actor_id), "name": named},
    )
