"""Google Drive message library calls for the church bot.

The public library at /sermons/ is a mirror of one or more Google Drive
folders. This module lets a bot do what the Owner and staff forms already
do: link a folder, refresh it, add one message from a Drive file link, and
set the site fields (title, speaker, date, series, description, who can
listen). The audio and video stay on Drive.

A folder is hidden with enabled=0. A message is hidden with hidden=1.
Neither is deleted, and the Drive file is never touched. Uploading a new
file into Drive is off unless DRIVE_WRITE_MODE says otherwise.
"""

from __future__ import annotations

from app.utils import drive_write
from app.utils import sermon_drive as drive
from app.utils.bot_sermon_common import _clip, _fail, _limit, _offset, _ok, _parse_date

TITLE_CAP = 255
SPEAKER_CAP = 160
SCRIPTURE_CAP = 255
SERIES_CAP = 160
SUMMARY_CAP = 4000
LABEL_CAP = 120

CREATE_FIELDS = frozenset({
    "title", "speaker", "speaker_id", "speaker_user", "preached_on", "date",
    "scripture", "series", "summary", "description", "visibility", "published",
    "hidden", "campus", "folder", "source_id", "drive_url", "drive_id",
})
PATCH_FIELDS = frozenset({
    "title", "speaker", "speaker_id", "speaker_user", "preached_on", "date",
    "scripture", "series", "summary", "description", "visibility", "published",
    "hidden",
})
UPLOAD_FIELDS = CREATE_FIELDS | {"file", "audio", "video", "media"}
SOURCE_FIELDS = frozenset({"folder", "label"})
SOURCE_PATCH_FIELDS = frozenset({"label", "enabled"})
SPEAKER_FIELDS = frozenset({"speaker", "name"})
LIST_QUERY = frozenset({
    "speaker", "from", "to", "q", "source_id", "visibility", "hidden",
    "limit", "offset", "sort", "dry_run",
})
UPLOAD_FILE_KEYS = ("file", "audio", "video", "media")
_EDITOR_ROLES = frozenset({"Staff", "Admin", "Owner"})
_UNDO_FIELDS = ("title", "speaker", "scripture", "series", "summary", "visibility", "hidden")
_MIME = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "wav": "audio/wav",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "mkv": "video/x-matroska",
}
# Drive file names allow most punctuation. A slash is a path, so it goes.
_BAD_NAME = str.maketrans({"/": " ", "\\": " "})


def _cur():
    from app.models.db import get_db
    return get_db().cursor()


def _int(value):
    text = str(value if value is not None else "").strip()
    return int(text) if text.isdigit() else None


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    text = str(value)[:10]
    return text or None


def _flag(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 1 if value else 0


def _truthy(value) -> bool:
    return str(value if value is not None else "").strip().lower() in ("1", "true", "yes", "on")


def is_editor(role) -> bool:
    return (role or "") in _EDITOR_ROLES


def unknown(body, allowed) -> str | None:
    """Refuse any field the call does not document. dry_run is always allowed."""
    for key in body or {}:
        if key == "dry_run":
            continue
        if key not in allowed:
            return f"Unknown field: {key}."
    return None


def _alias(body, primary: str, alias: str):
    one = body.get(primary)
    two = body.get(alias)
    one_set = one not in (None, "")
    two_set = two not in (None, "")
    if one_set and two_set and str(one).strip() != str(two).strip():
        return None, f"Send {primary} or {alias}, not both with different values."
    return (one if one_set else two), None


def _hidden(body):
    """Explicit hidden wins. published true shows it, false hides it. Blank keeps it."""
    if body.get("hidden") not in (None, ""):
        return (1 if _truthy(body.get("hidden")) else 0), None
    published = body.get("published")
    if published in (None, ""):
        return None, None
    text = str(published).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return 0, None
    if text in ("0", "false", "no", "off"):
        return 1, None
    return None, "Send published as true or false."


def clean_fields(body, *, creating: bool):
    """Check the site fields for one message. Does not write. Returns (fields, problem)."""
    body = body or {}
    problem = unknown(body, CREATE_FIELDS if creating else PATCH_FIELDS)
    if problem:
        return None, _fail(problem, 400, code="unknown_field")
    fields: dict = {}
    errors: list[str] = []
    if "title" in body:
        title = _clip(body.get("title"), TITLE_CAP)
        if not title:
            errors.append("A title is required.")
        else:
            fields["title"] = title
    elif creating:
        errors.append("A title is required.")
    for key, cap, column in (("scripture", SCRIPTURE_CAP, "scripture"),
                             ("series", SERIES_CAP, "series")):
        if key in body:
            fields[column] = _clip(body.get(key), cap)
    raw_date, date_err = _alias(body, "preached_on", "date")
    if date_err:
        errors.append(date_err)
    elif raw_date is not None:
        parsed, parse_err = _parse_date(raw_date)
        if parse_err:
            errors.append(parse_err)
        else:
            fields["preached_on"] = parsed
    raw_summary, summary_err = _alias(body, "summary", "description")
    if summary_err:
        errors.append(summary_err)
    elif raw_summary is not None:
        fields["summary"] = _clip(raw_summary, SUMMARY_CAP)
    if "visibility" in body and body.get("visibility") not in (None, ""):
        visibility = str(body.get("visibility")).strip().lower()
        if visibility not in drive.VISIBILITIES:
            errors.append("visibility must be public, members, or leaders.")
        else:
            fields["visibility"] = visibility
    hidden, hidden_err = _hidden(body)
    if hidden_err:
        errors.append(hidden_err)
    elif hidden is not None:
        fields["hidden"] = hidden
    if any(key in body for key in ("speaker", "speaker_id", "speaker_user")):
        fields["speaker"] = _clip(body.get("speaker"), SPEAKER_CAP)
        raw_speaker = str(body.get("speaker_id") if body.get("speaker_id") is not None else "").strip()
        if raw_speaker and not raw_speaker.isdigit():
            errors.append("Choose a speaker from the list.")
        fields["speaker_id"] = int(raw_speaker) if raw_speaker.isdigit() else None
        raw_user = str(body.get("speaker_user") if body.get("speaker_user") is not None else "").strip()
        if raw_user and not raw_user.isdigit():
            errors.append("Choose a member from the list.")
        fields["speaker_user"] = int(raw_user) if raw_user.isdigit() else None
    if errors:
        return None, _fail(errors[0], 400, code="invalid_field")
    return fields, None


def drive_filename(fields: dict, ext: str | None) -> str:
    """The mirrored file name. Reuses the 2026-11-08 - Speaker - Title pattern."""
    parts = [str(fields.get("preached_on") or "").strip(),
             str(fields.get("speaker") or "").strip(),
             str(fields.get("title") or "Message").strip()]
    name = " - ".join(part for part in parts if part)
    note = str(fields.get("summary") or "").strip()
    if note and len(note) <= 60 and "\n" not in note:
        name = f"{name} ({note})"
    name = " ".join(name.translate(_BAD_NAME).split())[:180].strip()
    return f"{name}.{ext}" if ext else name


def _item_url(item_id) -> str:
    try:
        from flask import url_for
        return url_for("sermons.library_listen", item_id=int(item_id), _external=True)
    except Exception:
        return f"https://myvinechurch.online/sermons/library/{int(item_id)}"


def view(row: dict | None) -> dict:
    """One library row for a Staff, Admin, or Owner bot. No local copy path."""
    row = row or {}
    try:
        item_id = int(row.get("id"))
    except (TypeError, ValueError):
        item_id = None
    try:
        speaker_id = int(row.get("speaker_id")) if row.get("speaker_id") else None
    except (TypeError, ValueError):
        speaker_id = None
    return {
        "id": item_id,
        "title": row.get("title") or "",
        "speaker": row.get("speaker_label") or row.get("speaker") or "",
        "speaker_id": speaker_id,
        "scripture": row.get("scripture") or "",
        "summary": row.get("summary") or "",
        "series": row.get("series") or "",
        "preached_on": _iso(row.get("preached_on")),
        "visibility": row.get("visibility") or "public",
        "hidden": bool(_flag(row.get("hidden"))),
        "kind": row.get("kind") or "audio",
        "source_id": _int(row.get("source_id")),
        "source_label": row.get("source_label") or "",
        "drive_file_id": row.get("drive_file_id"),
        "drive_name": row.get("drive_name") or "",
        "missing_on_drive": bool(_flag(row.get("missing_on_drive"))),
        "site_edited": bool(_flag(row.get("site_edited"))),
        "has_copy": drive.local_copy_name(row) is not None,
        "url": _item_url(item_id) if item_id else None,
    }


def _undo_fields(row: dict | None) -> dict:
    row = row or {}
    return {
        "title": row.get("title"),
        "speaker": row.get("speaker"),
        "scripture": row.get("scripture"),
        "series": row.get("series"),
        "summary": row.get("summary"),
        "visibility": row.get("visibility") or "public",
        "hidden": _flag(row.get("hidden")),
    }


# ── Folders ──────────────────────────────────────────────────────────────────


def sources():
    try:
        drive.ensure_schema()
        cur = _cur()
        cur.execute(
            """
            SELECT s.id, s.label, s.enabled, s.folder_id, s.default_visibility,
                   (SELECT COUNT(*) FROM sermon_drive_items i WHERE i.source_id = s.id) AS messages
              FROM sermon_drive_sources s
             ORDER BY s.label, s.id
            """
        )
        rows = []
        for row in cur.fetchall() or []:
            rows.append({
                "id": int(row["id"]),
                "label": row.get("label") or "Messages",
                "enabled": bool(_flag(row.get("enabled"))),
                "messages": int(row.get("messages") or 0),
                "folder_id": row.get("folder_id"),
                "default_visibility": drive.normalize_visibility(row.get("default_visibility")),
            })
        return _ok({"sources": rows, "count": len(rows)})
    except Exception as exc:
        print(f"bot drive sources: {type(exc).__name__}")
        return _fail("The message folders could not be read.", 500, "bot_drive_source_list")


def _source_by_folder(folder_id: str):
    try:
        cur = _cur()
        cur.execute(
            """
            SELECT id, label, enabled, folder_id, default_visibility
              FROM sermon_drive_sources WHERE folder_id=%s LIMIT 1
            """,
            (folder_id,),
        )
        return cur.fetchone()
    except Exception:
        return None


def add_source(body: dict, actor_id) -> dict:
    body = body or {}
    problem = unknown(body, SOURCE_FIELDS)
    if problem:
        return _fail(problem, 400, code="unknown_field")
    raw = body.get("folder")
    folder_id = drive.extract_folder_id(raw)
    if not folder_id:
        return _fail("Paste a Google Drive folder link or folder id.", 400, "bot_drive_source_create")
    label = _clip(body.get("label"), LABEL_CAP)
    before = _source_by_folder(folder_id)
    if body.get("dry_run"):
        return _ok({"would_add": {"folder_id": folder_id, "label": label or None},
                    "note": "Nothing was saved."})
    if not drive.save_folder_id(raw, label):
        return _fail("That folder could not be saved just now.", 500, "bot_drive_source_create")
    after = _source_by_folder(folder_id)
    if not after:
        return _fail("That folder could not be saved just now.", 500, "bot_drive_source_create")
    source_id = int(after["id"])
    return _ok(
        {
            "source": {
                "id": source_id,
                "label": after.get("label") or "Messages",
                "enabled": bool(_flag(after.get("enabled"))),
                "folder_id": after.get("folder_id"),
                "messages": _message_count(source_id),
            },
            "refresh": "POST /api/bot/sermons/library/refresh",
            "note": "Message folder saved. Refresh the library to read it.",
        },
        {
            "action": "bot_drive_source_create",
            "target_type": "sermon_drive_source",
            "target_id": source_id,
            "detail": (after.get("label") or "Messages")[:180],
            "snapshot": {
                "source_id": source_id,
                "before": before,
                "created": before is None,
                "as": actor_id,
            },
        },
    )


def _message_count(source_id: int) -> int:
    try:
        cur = _cur()
        cur.execute("SELECT COUNT(*) AS n FROM sermon_drive_items WHERE source_id=%s", (int(source_id),))
        row = cur.fetchone() or {}
        return int(row.get("n") or 0)
    except Exception:
        return 0


def update_source(source_id, body: dict, actor_id) -> dict:
    body = body or {}
    problem = unknown(body, SOURCE_PATCH_FIELDS)
    if problem:
        return _fail(problem, 400, code="unknown_field")
    try:
        row_id = int(source_id)
    except (TypeError, ValueError):
        return _fail("That folder is not on this site.", 404, "bot_drive_source_update")
    if body.get("label") is None and body.get("enabled") is None:
        return _fail("Send label or enabled.", 400, "bot_drive_source_update")
    try:
        drive.ensure_schema()
        cur = _cur()
        cur.execute(
            "SELECT id, label, enabled, folder_id FROM sermon_drive_sources WHERE id=%s",
            (row_id,),
        )
        current = cur.fetchone()
        if not current:
            return _fail("That folder is not on this site.", 404, "bot_drive_source_update")
    except Exception as exc:
        print(f"bot drive source read: {type(exc).__name__}")
        return _fail("That folder could not be read just now.", 500, "bot_drive_source_update")
    before = {"label": current.get("label"), "enabled": bool(_flag(current.get("enabled")))}
    label = _clip(body.get("label"), LABEL_CAP) or current.get("label")
    enabled = before["enabled"]
    if body.get("enabled") is not None:
        text = str(body.get("enabled")).strip().lower()
        if text in ("1", "true", "yes", "on"):
            enabled = True
        elif text in ("0", "false", "no", "off"):
            enabled = False
        else:
            return _fail("Send enabled as true or false.", 400, "bot_drive_source_update")
    after = {"label": label, "enabled": enabled}
    if body.get("dry_run"):
        return _ok({"source_id": row_id, "would_change": after, "note": "Nothing was saved."})
    status = drive.save_source(row_id, label, "1" if enabled else "0")
    if status == "missing":
        return _fail("That folder is not on this site.", 404, "bot_drive_source_update")
    if status == "bad":
        return _fail("Choose a folder and a name.", 400, "bot_drive_source_update")
    if status != "ok":
        return _fail("That folder could not be updated just now.", 500, "bot_drive_source_update")
    return _ok(
        {
            "source": {
                "id": row_id,
                "label": label,
                "enabled": enabled,
                "folder_id": current.get("folder_id"),
                "messages": _message_count(row_id),
            }
        },
        {
            "action": "bot_drive_source_update",
            "target_type": "sermon_drive_source",
            "target_id": row_id,
            "detail": label[:180],
            "snapshot": {"source_id": row_id, "before": before, "after": after, "as": actor_id},
        },
    )


# ── Refresh ──────────────────────────────────────────────────────────────────


def refresh(actor_id) -> dict:
    result = drive.sync_now()
    if result.get("busy"):
        return _fail("The library is already refreshing. Retry in a moment.", 409, code="busy")
    if not result.get("ok"):
        return _fail("A Drive folder could not be read just now.", 502, "bot_drive_refresh")
    count = result.get("count") or 0
    return _ok(
        {"count": count},
        {
            "action": "bot_drive_refresh",
            "target_type": "sermon_drive",
            "detail": f"Read the linked Drive folders. {count} files.",
            "snapshot": {"as": actor_id, "count": count},
        },
    )


# ── One message ──────────────────────────────────────────────────────────────


def _source_row(body: dict):
    """Which linked folder this message belongs to. Returns (row, problem)."""
    raw_folder = body.get("folder")
    raw_id = str(body.get("source_id") if body.get("source_id") is not None else "").strip()
    try:
        cur = _cur()
        if raw_id:
            if not raw_id.isdigit():
                return None, _fail("Send source_id as a number.", 400, code="invalid_field")
            cur.execute(
                """
                SELECT id, label, enabled, folder_id, default_visibility
                  FROM sermon_drive_sources WHERE id=%s
                """,
                (int(raw_id),),
            )
            row = cur.fetchone()
            if not row:
                return None, _fail("That folder is not on this site.", 404, code="source_missing")
            return row, None
        if raw_folder not in (None, ""):
            folder_id = drive.extract_folder_id(raw_folder)
            if not folder_id:
                return None, _fail("Paste a Google Drive folder link or folder id.", 400, code="invalid_folder")
            cur.execute(
                """
                SELECT id, label, enabled, folder_id, default_visibility
                  FROM sermon_drive_sources WHERE folder_id=%s LIMIT 1
                """,
                (folder_id,),
            )
            row = cur.fetchone()
            if not row:
                return None, _fail("That folder is not linked on this site yet.", 404, code="source_missing")
            return row, None
        cur.execute(
            """
            SELECT id, label, enabled, folder_id, default_visibility
              FROM sermon_drive_sources WHERE enabled=1 ORDER BY id
            """
        )
        rows = list(cur.fetchall() or [])
        if len(rows) == 1:
            return rows[0], None
        if not rows:
            return None, _fail("No Drive folder is linked yet.", 404, code="source_missing")
        return None, _fail("Send source_id to choose which folder this file belongs to.", 400,
                           code="source_required")
    except Exception as exc:
        print(f"bot drive source pick: {type(exc).__name__}")
        return None, _fail("The linked folder could not be read.", 500)


def _apply_speaker(cur, fields: dict):
    """Resolve the speaker name or id to a speaker row. A guest needs no account."""
    if not any(key in fields for key in ("speaker", "speaker_id", "speaker_user")):
        return None, None, None
    form = {
        "speaker": fields.get("speaker"),
        "speaker_id": fields.get("speaker_id"),
        "speaker_user": fields.get("speaker_user"),
    }
    speaker_id, display, errors, _changed = drive._apply_form_speaker(cur, form)
    if errors:
        return None, None, errors[0]
    return speaker_id, display, None


def _insert_item(cur, source_id, file_id, drive_name, kind, mime, fields, actor_id) -> int:
    cur.execute(
        """
        INSERT INTO sermon_drive_items
            (source_id, drive_file_id, drive_name, mime_type, kind, title, speaker,
             speaker_id, scripture, summary, series, preached_on, visibility, hidden,
             site_edited, missing_on_drive, synced_at, updated_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 0, NULL, %s)
        """,
        (
            int(source_id), file_id, drive_name[:500], mime, kind or "audio",
            fields.get("title"), fields.get("speaker"), fields.get("speaker_id"),
            fields.get("scripture"), fields.get("summary"), fields.get("series"),
            fields.get("preached_on"), fields.get("visibility") or "public",
            1 if fields.get("hidden") else 0, actor_id,
        ),
    )
    return int(cur.lastrowid)


def _drive_target(body: dict):
    raw, err = _alias(body, "drive_url", "drive_id")
    if err:
        return None, _fail(err, 400)
    file_id = drive.extract_file_id(raw)
    if not file_id:
        return None, _fail(
            "Paste a Google Drive file link or file id. A folder link is not a file.",
            400, code="invalid_file",
        )
    return file_id, None


def create_item(body: dict, actor_id) -> dict:
    body = body or {}
    fields, problem = clean_fields(body, creating=True)
    if problem:
        return problem
    if body.get("campus") not in (None, ""):
        return _fail("campus is not on this library yet.", 400, code="invalid_field")
    file_id, problem = _drive_target(body)
    if problem:
        return problem
    try:
        drive.ensure_schema()
        cur = _cur()
        source, problem = _source_row(body)
        if problem:
            return problem
        if not _flag(source.get("enabled")):
            return _fail("That Drive folder is turned off.", 400, code="source_off")
        cur.execute("SELECT id FROM sermon_drive_items WHERE drive_file_id=%s", (file_id,))
        existing = cur.fetchone()
        if existing:
            item_id = int(existing["id"])
            out = _fail("That Drive file is already in the library.", 409, code="exists")
            out["data"] = {"id": item_id, "url": _item_url(item_id)}
            return out
        fields.setdefault("visibility", drive.normalize_visibility(source.get("default_visibility")))
        speaker_id, display, speaker_err = _apply_speaker(cur, fields)
        if speaker_err:
            return _fail(speaker_err, 400, code="invalid_field")
        if speaker_id:
            fields["speaker"] = display
            fields["speaker_id"] = speaker_id
        if body.get("dry_run"):
            return _ok({"would_create": {"title": fields.get("title"),
                                         "source_id": int(source["id"]),
                                         "drive_file_id": file_id},
                        "note": "Nothing was saved."})
        drive_name = drive_filename(fields, None)
        item_id = _insert_item(
            cur, source["id"], file_id, drive_name, "audio", None, fields, actor_id,
        )
    except Exception as exc:
        print(f"bot drive item create: {type(exc).__name__}")
        return _fail("That message could not be saved just now.", 500, "bot_drive_item_create")
    row = drive.get_item(item_id)
    return _ok(
        {
            "item": view(row),
            "refresh": "POST /api/bot/sermons/library/refresh",
            "note": "The message is in the library now. A refresh keeps its Drive file current.",
        },
        {
            "action": "bot_drive_item_create",
            "target_type": "sermon_drive_item",
            "target_id": item_id,
            "detail": str(fields.get("title") or "")[:180],
            "snapshot": {"item_id": item_id, "before": None, "after": _undo_fields(row),
                         "as": actor_id},
        },
    )


def _current_row(item_id):
    try:
        return drive.get_item(int(item_id))
    except (TypeError, ValueError):
        return None


def update_item(item_id, body: dict, actor_id) -> dict:
    body = body or {}
    fields, problem = clean_fields(body, creating=False)
    if problem:
        return problem
    current = _current_row(item_id)
    if not current:
        return _fail("That message is not in the library.", 404, "bot_drive_item_update")
    if not fields:
        return _fail("Send the fields to change.", 400, "bot_drive_item_update")
    if body.get("campus") not in (None, ""):
        return _fail("campus is not on this library yet.", 400, code="invalid_field")
    form = {
        "title": fields.get("title", current.get("title")),
        "scripture": fields.get("scripture", current.get("scripture")),
        "series": fields.get("series", current.get("series")),
        "summary": fields.get("summary", current.get("summary")),
        "preached_on": _iso(fields.get("preached_on", current.get("preached_on"))) or "",
        "visibility": fields.get("visibility", current.get("visibility")),
        "hidden": str(fields.get("hidden", _flag(current.get("hidden")))),
    }
    if any(key in fields for key in ("speaker", "speaker_id", "speaker_user")):
        form["speaker"] = fields.get("speaker")
        form["speaker_id"] = fields.get("speaker_id")
        form["speaker_user"] = fields.get("speaker_user")
    if body.get("dry_run"):
        return _ok({"item_id": int(current["id"]), "would_change": form,
                    "note": "Nothing was saved."})
    before = _undo_fields(current)
    ok, errors = drive.save_item_details(int(current["id"]), form, actor_id)
    if not ok:
        return _fail((errors or ["Those details could not be saved just now."])[0], 400,
                     "bot_drive_item_update")
    row = drive.get_item(int(current["id"]))
    only_hidden = set(fields) == {"hidden"} and _flag(fields.get("hidden")) == 1
    return _ok(
        {"item": view(row)},
        {
            "action": "bot_drive_item_hide" if only_hidden else "bot_drive_item_update",
            "target_type": "sermon_drive_item",
            "target_id": int(current["id"]),
            "detail": str(row.get("title") or "")[:180],
            "snapshot": {"item_id": int(current["id"]), "before": before,
                         "after": _undo_fields(row), "as": actor_id},
        },
    )


def item(item_id) -> dict:
    row = _current_row(item_id)
    if not row:
        return _fail("That message is not in the library.", 404, "bot_drive_item_get")
    return _ok({"item": view(row)})


def items(query: dict) -> dict:
    """Messages for a staff bot. Filters match the public /sermons/ page."""
    query = query or {}
    problem = unknown(query, LIST_QUERY)
    if problem:
        return _fail(problem, 400, code="unknown_field")
    hidden = str(query.get("hidden") if query.get("hidden") is not None else "0").strip().lower()
    if hidden not in ("0", "1", "all"):
        return _fail("hidden must be 0, 1, or all.", 400, code="invalid_field")
    visibility = ""
    if query.get("visibility") not in (None, ""):
        visibility = str(query.get("visibility")).strip().lower()
        if visibility not in drive.VISIBILITIES:
            return _fail("visibility must be public, members, or leaders.", 400, code="invalid_field")
    start, start_err = _parse_date(query.get("from"))
    if start_err:
        return _fail("Send from as YYYY-MM-DD.", 400, code="invalid_field")
    end, end_err = _parse_date(query.get("to"))
    if end_err:
        return _fail("Send to as YYYY-MM-DD.", 400, code="invalid_field")
    source_id = None
    if query.get("source_id") not in (None, ""):
        source_id = _int(query.get("source_id"))
        if not source_id:
            return _fail("Send source_id as a number.", 400, code="invalid_field")
    raw_speaker = str(query.get("speaker") if query.get("speaker") is not None else "").strip()
    who = "" if raw_speaker.isdigit() and raw_speaker else drive.parse_who(raw_speaker)
    speaker_id = int(raw_speaker) if raw_speaker.isdigit() and raw_speaker else None
    search = drive.parse_search(query.get("q"))
    sort = drive.parse_sort(query.get("sort"))
    try:
        rows = drive.list_items(sort)
    except Exception as exc:
        print(f"bot drive item list: {type(exc).__name__}")
        return _fail("The message library could not be read.", 500, "bot_drive_item_list")
    matched = []
    for row in rows or []:
        if _flag(row.get("hidden")) and hidden != "all" and hidden != "1":
            continue
        if hidden == "1" and not _flag(row.get("hidden")):
            continue
        if visibility and (row.get("visibility") or "public").lower() != visibility:
            continue
        if source_id and _int(row.get("source_id")) != source_id:
            continue
        if speaker_id and _int(row.get("speaker_id")) != speaker_id:
            continue
        when = _iso(row.get("preached_on")) or ""
        if start and when < start:
            continue
        if end and when > end:
            continue
        if not drive.row_matches_library(row, who=who, query=search):
            continue
        matched.append(row)
    total = len(matched)
    page = matched[_offset(query.get("offset")):][: _limit(query.get("limit"))]
    return _ok({
        "items": [view(row) for row in page],
        "count": total,
        "limit": _limit(query.get("limit")),
        "offset": _offset(query.get("offset")),
        "sort": sort,
    })


# ── Speakers ─────────────────────────────────────────────────────────────────


def speakers() -> dict:
    try:
        people = drive.list_speakers()
    except Exception as exc:
        print(f"bot drive speakers: {type(exc).__name__}")
        return _fail("The speakers could not be read.", 500, "bot_drive_speaker_list")
    rows = []
    for person in people or []:
        rows.append({
            "id": person.get("id"),
            "display_name": person.get("display_name") or "",
            "names": person.get("names") or [],
            "messages": person.get("messages") or 0,
            "linked": bool(person.get("linked")),
            "listen_rule": person.get("listen_rule") or "",
        })
    return _ok({"speakers": rows, "count": len(rows)})


def _speaker_view(cur, speaker_id: int, created: bool) -> dict:
    cur.execute(
        "SELECT id, display_name, user_id, listen_rule FROM sermon_speakers WHERE id=%s",
        (int(speaker_id),),
    )
    row = cur.fetchone() or {}
    cur.execute(
        "SELECT name FROM sermon_speaker_names WHERE speaker_id=%s ORDER BY name",
        (int(speaker_id),),
    )
    names = [entry.get("name") for entry in cur.fetchall() or [] if entry.get("name")]
    cur.execute(
        "SELECT COUNT(*) AS n FROM sermon_drive_items WHERE speaker_id=%s",
        (int(speaker_id),),
    )
    counted = cur.fetchone() or {}
    return {
        "speaker": {
            "id": int(speaker_id),
            "display_name": row.get("display_name") or "",
            "names": names,
            "messages": int(counted.get("n") or 0),
            "linked": bool(row.get("user_id")),
            "listen_rule": drive._stored_listen_rule(row.get("listen_rule")) or "",
        },
        "created": created,
    }


def add_speaker(body: dict, actor_id) -> dict:
    body = body or {}
    problem = unknown(body, SPEAKER_FIELDS)
    if problem:
        return _fail(problem, 400, code="unknown_field")
    raw, err = _alias(body, "speaker", "name")
    if err:
        return _fail(err, 400, code="invalid_field")
    name = _clip(raw, SPEAKER_CAP)
    key = drive.speaker_key(name)
    if not key:
        return _fail("Type a name.", 400, code="invalid_field")
    try:
        drive.ensure_schema()
        cur = _cur()
        cur.execute("SELECT speaker_id FROM sermon_speaker_names WHERE name_key=%s", (key,))
        found = cur.fetchone()
        if found:
            payload = _speaker_view(cur, int(found["speaker_id"]), created=False)
            return _ok(payload, {
                "action": "bot_drive_speaker_create",
                "target_type": "sermon_speaker",
                "target_id": payload["speaker"]["id"],
                "detail": f"{payload['speaker']['display_name']} (already saved)",
                "snapshot": {"speaker_id": payload["speaker"]["id"], "created": False,
                             "as": actor_id},
            })
        if body.get("dry_run"):
            return _ok({"would_create": {"display_name": name}, "note": "Nothing was saved."})
        status = drive.create_speaker(name)
        if status:
            code = "invalid_field" if status in ("Type a name.",) else "save_failed"
            return _fail(status if code == "invalid_field" else "That speaker could not be saved.",
                         400 if code == "invalid_field" else 500, "bot_drive_speaker_create",
                         code=code)
        cur.execute("SELECT speaker_id FROM sermon_speaker_names WHERE name_key=%s", (key,))
        found = cur.fetchone()
        if not found:
            return _fail("That speaker could not be saved just now.", 500, "bot_drive_speaker_create")
        speaker_id = int(found["speaker_id"])
    except Exception as exc:
        print(f"bot drive speaker create: {type(exc).__name__}")
        return _fail("That speaker could not be saved just now.", 500, "bot_drive_speaker_create")
    payload = _speaker_view(cur, speaker_id, created=True)
    return _ok(payload, {
        "action": "bot_drive_speaker_create",
        "target_type": "sermon_speaker",
        "target_id": speaker_id,
        "detail": name[:180],
        "snapshot": {"speaker_id": speaker_id, "created": True, "as": actor_id},
    })


# ── Upload into Drive (Phase 2) ──────────────────────────────────────────────


def _pick_file(files):
    for key in UPLOAD_FILE_KEYS:
        handle = files.get(key) if files else None
        if handle is not None and getattr(handle, "filename", ""):
            return handle
    return None


def upload(body: dict, files, actor_id) -> dict:
    mode = drive_write.mode()
    if mode == "off":
        return _fail(
            "Drive uploads are not turned on. The owner still needs to choose a Google account for the site.",
            503, code="drive_writes_off",
        )
    body = body or {}
    problem = unknown(body, UPLOAD_FIELDS)
    if problem:
        return _fail(problem, 400, code="unknown_field")
    handle = _pick_file(files)
    if handle is None:
        return _fail("Send the audio or video file as file=.", 400, code="missing_file")
    ext = drive.media_extension(handle.filename)
    if not ext:
        return _fail("Send an mp3, m4a, wav, aac, ogg, mp4, webm, mov, or mkv file.",
                     400, code="bad_file")
    fields, problem = clean_fields(body, creating=True)
    if problem:
        return problem
    if body.get("campus") not in (None, ""):
        return _fail("campus is not on this library yet.", 400, code="invalid_field")
    try:
        payload = handle.read()
    except Exception:
        return _fail("That file could not be read.", 400, code="bad_file")
    if not payload:
        return _fail("That file is empty.", 400, code="bad_file")
    if len(payload) > drive.MAX_COPY_BYTES:
        return _fail("That file is larger than 200 MB.", 413, code="too_large")
    try:
        drive.ensure_schema()
        cur = _cur()
        source, problem = _source_row(body)
        if problem:
            return problem
        if not _flag(source.get("enabled")):
            return _fail("That Drive folder is turned off.", 400, code="source_off")
        fields.setdefault("visibility", drive.normalize_visibility(source.get("default_visibility")))
        speaker_id, display, speaker_err = _apply_speaker(cur, fields)
        if speaker_err:
            return _fail(speaker_err, 400, code="invalid_field")
        if speaker_id:
            fields["speaker"] = display
            fields["speaker_id"] = speaker_id
        filename = drive_filename(fields, ext)
        if body.get("dry_run"):
            return _ok({"would_upload": {"filename": filename, "folder_id": source.get("folder_id")},
                        "note": "Nothing was uploaded."})
        file_id = drive_write.upload_media(
            source.get("folder_id"), filename, payload, _MIME.get(ext) or "application/octet-stream",
        )
        cur.execute("SELECT id FROM sermon_drive_items WHERE drive_file_id=%s", (file_id,))
        existing = cur.fetchone()
        if existing:
            item_id = int(existing["id"])
            cur.execute(
                """
                UPDATE sermon_drive_items
                   SET title=%s, speaker=%s, speaker_id=%s, scripture=%s, summary=%s,
                       series=%s, preached_on=%s, visibility=%s, hidden=%s, site_edited=1,
                       missing_on_drive=0, updated_by=%s
                 WHERE id=%s
                """,
                (
                    fields.get("title"), fields.get("speaker"), fields.get("speaker_id"),
                    fields.get("scripture"), fields.get("summary"), fields.get("series"),
                    fields.get("preached_on"), fields.get("visibility") or "public",
                    1 if fields.get("hidden") else 0, actor_id, item_id,
                ),
            )
        else:
            item_id = _insert_item(
                cur, source["id"], file_id, filename, drive.media_kind(filename),
                _MIME.get(ext), fields, actor_id,
            )
    except drive_write.DriveWriteOff as exc:
        return _fail(str(exc), 503, code="drive_writes_off")
    except drive_write.DriveWriteError as exc:
        return _fail(str(exc), 502, code="drive_write_failed")
    except Exception as exc:
        print(f"bot drive upload: {type(exc).__name__}")
        return _fail("That file could not be added to the library just now.", 500, "bot_drive_upload")
    row = drive.get_item(item_id)
    return _ok(
        {"item": view(row)},
        {
            "action": "bot_drive_upload",
            "target_type": "sermon_drive_item",
            "target_id": item_id,
            "detail": filename[:180],
            "snapshot": {"item_id": item_id, "before": None, "after": _undo_fields(row),
                         "as": actor_id},
        },
    )


# ── Undo ─────────────────────────────────────────────────────────────────────


def _restore_fields(cur, item_id: int, side: dict) -> None:
    chosen = {key: side.get(key) for key in _UNDO_FIELDS if key in (side or {})}
    if not chosen:
        return
    sets = ", ".join(f"{key}=%s" for key in chosen)
    cur.execute(
        f"UPDATE sermon_drive_items SET {sets}, site_edited=1 WHERE id=%s",
        tuple(chosen[key] for key in chosen) + (int(item_id),),
    )


def apply_undo(plan: str, entry: dict) -> tuple[bool, str]:
    """Undo one logged library change. A Drive file is never deleted."""
    action = (entry or {}).get("action") or ""
    snapshot = (entry or {}).get("snapshot") or {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    try:
        cur = _cur()
        if action in ("bot_drive_source_create", "bot_drive_source_update"):
            source_id = snapshot.get("source_id") or entry.get("target_id")
            if not source_id:
                return False, "That entry has no folder to change."
            if action == "bot_drive_source_create":
                enabled = 0 if plan == "hide" else 1
                cur.execute(
                    "UPDATE sermon_drive_sources SET enabled=%s WHERE id=%s",
                    (enabled, int(source_id)),
                )
                return True, (
                    "Hid that folder. Its messages stay saved." if enabled == 0
                    else "Turned that folder back on."
                )
            side = snapshot.get("before" if plan == "restore" else "after") or {}
            if not side:
                return False, "That folder change has nothing to put back."
            cur.execute(
                "UPDATE sermon_drive_sources SET label=%s, enabled=%s WHERE id=%s",
                (side.get("label"), 1 if side.get("enabled") else 0, int(source_id)),
            )
            return True, (
                "Put the previous folder settings back." if plan == "restore"
                else "Applied that folder change again."
            )
        item_id = snapshot.get("item_id") or entry.get("target_id")
        if not item_id:
            return False, "That entry has no message to change."
        if action in ("bot_drive_item_create", "bot_drive_upload"):
            hidden = 1 if plan == "hide" else 0
            cur.execute(
                "UPDATE sermon_drive_items SET hidden=%s WHERE id=%s",
                (hidden, int(item_id)),
            )
            return True, (
                "Hid that message. The Drive file is still there." if hidden
                else "Put that message back in the library."
            )
        if action == "bot_drive_item_hide":
            hidden = 0 if plan == "show" else 1
            cur.execute(
                "UPDATE sermon_drive_items SET hidden=%s WHERE id=%s",
                (hidden, int(item_id)),
            )
            return True, "Put that message back." if hidden == 0 else "Hid that message again."
        if action == "bot_drive_item_update":
            side = snapshot.get("before" if plan == "restore" else "after") or {}
            if not side:
                return False, "That message change has nothing to put back."
            _restore_fields(cur, int(item_id), side)
            return True, (
                "Put the previous message details back." if plan == "restore"
                else "Applied that message change again."
            )
        return False, "That library change cannot be put back."
    except Exception as exc:
        print(f"bot drive undo: {type(exc).__name__}")
        return False, "That library change could not be put back just now."
