"""Picture files the office account can place on the site.

The bot sends a multipart file. These calls use the same savers as the
pages: a study lesson, a church or member page, the sign-in background,
a ministry partner, a giving option, a song chart, and a wall photo.
Reverse does not delete the file.
"""

from __future__ import annotations

from app.utils.bot_sermon_common import _fail, _ok

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_VIDEO_EXT = {".mp4", ".webm", ".mov"}
_SONG_EXT = {".png", ".jpg", ".jpeg", ".pdf", ".doc", ".docx", ".txt"}
_PLACES = ("course", "page", "post", "login", "partner", "giving", "song")


def _app():
    from flask import current_app
    return current_app


def _ext(file_storage) -> str:
    name = (getattr(file_storage, "filename", None) or "").strip().lower()
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1]


def _named(file_storage) -> bool:
    return bool(file_storage is not None and (getattr(file_storage, "filename", None) or "").strip())


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _text(fields, *names, limit: int = 255) -> str:
    for name in names:
        raw = fields.get(name) if fields is not None else None
        if raw not in (None, ""):
            return str(raw).strip()[:limit]
    return ""


def _flag(fields, *names) -> bool:
    for name in names:
        raw = fields.get(name) if fields is not None else None
        if str(raw).strip().lower() in ("1", "true", "yes", "on"):
            return True
    return False


def _one(sql: str, args: tuple):
    from app.models.db import get_db
    cur = get_db().cursor()
    cur.execute(sql, args)
    return cur.fetchone()


def _cell(row, key: str):
    if not row:
        return None
    if isinstance(row, dict):
        return row.get(key)
    return None


def _words_blocked(text: str) -> bool:
    if not text:
        return False
    from app.utils.helpers import contains_censored_word
    return bool(contains_censored_word(text))


def save_upload(actor_id: int, place: str, file_storage, fields, voice: dict | None = None) -> dict:
    """Save one picture. fields is the multipart form."""
    where = (place or "").strip().lower()
    fields = fields if fields is not None else {}
    if where not in _PLACES:
        return _fail(
            "Place is course, page, post, login, partner, giving, or song."
        )
    if where == "course":
        return _course(int(actor_id), file_storage, fields)
    if where == "page":
        return _page(int(actor_id), file_storage, fields)
    if where == "post":
        return _post(file_storage, fields, voice or {})
    if where == "login":
        return _login(file_storage, fields)
    if where == "partner":
        return _partner(int(actor_id), file_storage, fields)
    if where == "giving":
        return _giving(file_storage, fields)
    return _song(int(actor_id), file_storage, fields)


def _course(actor_id: int, file_storage, fields) -> dict:
    lesson_id = _int(fields.get("lesson_id"))
    if not lesson_id:
        return _fail("A study picture needs lesson_id.")
    if not _named(file_storage):
        return _fail("Choose a picture.")
    ext = _ext(file_storage)
    if ext in _VIDEO_EXT:
        kind = "video"
        block_type = "video"
    elif ext in _IMAGE_EXT:
        kind = "image"
        block_type = "image"
    else:
        return _fail("Use png, jpg, gif, webp, or a video file (mp4, webm, mov).")
    title = _text(fields, "title", "caption")
    alt = _text(fields, "media_alt", "alt")
    if _words_blocked(f"{title} {alt}".strip()):
        return _fail("That caption contains a prohibited word.")
    try:
        lesson = _one(
            "SELECT id, series_id FROM curriculum_lessons WHERE id=%s",
            (lesson_id,),
        )
    except Exception as exc:
        print(f"bot upload lesson: {exc}")
        return _fail("That study picture did not save.", 500)
    if not lesson:
        return _fail("That lesson is not on a study course.")
    from app.models.pastoral import curriculum as lessons
    try:
        stored = lessons.save_curriculum_upload(file_storage, _app(), kind=kind)
    except ValueError as exc:
        return _fail(str(exc) or "That file is not a picture.")
    except Exception as exc:
        print(f"bot upload course file: {exc}")
        return _fail("That study picture did not save.", 500)
    if not stored:
        return _fail("Choose a picture.")
    block_id = _int(fields.get("block_id"))
    try:
        if block_id:
            block = lessons.get_block(block_id)
            if not block or int(block.get("lesson_id") or 0) != lesson_id:
                return _fail("That block is not on this lesson.")
            data = {"media_path": stored, "block_type": block_type}
            if title:
                data["title"] = title
            if alt:
                data["media_alt"] = alt
            lessons.update_block(block_id, data)
        else:
            block_id = int(lessons.create_block(lesson_id, {
                "block_type": block_type,
                "title": title or None,
                "media_path": stored,
                "media_alt": alt or None,
            }))
    except Exception as exc:
        print(f"bot upload course block: {exc}")
        return _fail("That study picture did not save.", 500)
    return _ok(
        {
            "place": "course",
            "series_id": _cell(lesson, "series_id"),
            "lesson_id": lesson_id,
            "block_id": block_id,
            "block_type": block_type,
            "file": stored,
        },
        {
            "action": "upload.course",
            "detail": f"Picture on lesson {lesson_id}",
            "target_type": "curriculum_blocks",
            "target_id": block_id,
            "snapshot": {"lesson_id": lesson_id, "block_id": block_id, "file": stored},
        },
    )


def _page(actor_id: int, file_storage, fields) -> dict:
    scope = (fields.get("scope") or "church").strip().lower()
    if scope in ("mypage", "my_page", "member_page"):
        scope = "member"
    if scope not in ("church", "member"):
        return _fail("Scope is church or member.")
    slot = (fields.get("slot") or "photo").strip().lower()
    if slot in ("portrait", "profile"):
        slot = "avatar"
    if slot in ("gallery", "picture"):
        slot = "photo"
    if slot not in ("photo", "banner", "avatar"):
        return _fail("Slot is photo, banner, or avatar.")
    asked = _int(fields.get("user_id"))
    if scope == "member" and asked and asked != int(actor_id):
        return _fail("Member pictures go on the account the owner chose for this bot.")
    focus = _focus(fields)
    if scope == "church":
        campus_id = _int(fields.get("campus_id"))
        try:
            from app.models.church_community import single_church_install
            if single_church_install():
                campus_id = 0
        except Exception:
            campus_id = 0
        owner_type = "campus" if campus_id else "church"
        owner_id = campus_id
    else:
        owner_type = "member"
        owner_id = int(actor_id)
    from app.models import social
    if not _named(file_storage):
        if not (focus and slot == "banner"):
            return _fail("Choose a picture.")
        try:
            social.set_banner_focus(
                "member" if scope == "member" else "church",
                int(owner_id),
                focus[0],
                focus[1],
            )
        except Exception as exc:
            print(f"bot upload banner: {exc}")
            return _fail("That banner position did not save.", 500)
        return _ok(
            {"place": "page", "scope": scope, "slot": "banner", "owner_id": int(owner_id)},
            _page_log(scope, "banner", None),
        )
    if _ext(file_storage) not in _IMAGE_EXT:
        return _fail("Use png, jpg, gif, or webp.")
    try:
        if slot == "photo":
            ok, msg = social.add_photo(
                owner_type, owner_id, file_storage,
                _text(fields, "caption", "title", "note"),
                int(actor_id),
            )
            if not ok:
                return _fail(msg or "That picture did not save.")
            row = _quiet(
                """
                SELECT id, filename FROM page_photos
                WHERE owner_type=%s AND owner_id=%s
                ORDER BY id DESC LIMIT 1
                """,
                (owner_type, int(owner_id)),
            )
            photo_id = _cell(row, "id")
            return _ok(
                {
                    "place": "page",
                    "scope": scope,
                    "slot": "photo",
                    "owner_type": owner_type,
                    "owner_id": int(owner_id),
                    "photo_id": photo_id,
                    "file": _cell(row, "filename"),
                },
                _page_log(scope, slot, photo_id),
            )
        if scope == "member":
            row = _one("SELECT user_id FROM member_spaces WHERE user_id=%s", (int(actor_id),))
            if not row:
                return _fail("That account has no member page yet.")
            ok, msg = social.set_member_identity(int(actor_id), slot, file_storage)
        else:
            ok, msg = social.set_church_identity(int(owner_id), slot, file_storage, int(actor_id))
        if not ok:
            return _fail(msg or "Use png, jpg, gif, or webp.")
        if focus and slot == "banner":
            social.set_banner_focus("member" if scope == "member" else "church", int(owner_id), focus[0], focus[1])
    except Exception as exc:
        print(f"bot upload page: {exc}")
        return _fail("That picture did not save.", 500)
    return _ok(
        {"place": "page", "scope": scope, "slot": slot, "owner_id": int(owner_id)},
        _page_log(scope, slot, None),
    )


def _focus(fields):
    raw_x = fields.get("banner_x")
    raw_y = fields.get("banner_y")
    if raw_x in (None, "") or raw_y in (None, ""):
        return None
    try:
        return int(float(raw_x)), int(float(raw_y))
    except (TypeError, ValueError):
        return None


def _page_log(scope: str, slot: str, target_id) -> dict:
    return {
        "action": "upload.page",
        "detail": f"Picture on the {scope} page ({slot})",
        "target_type": "page_photos" if slot == "photo" else "church_pages",
        "target_id": target_id,
        "snapshot": {"scope": scope, "slot": slot},
    }


def _quiet(sql: str, args: tuple):
    try:
        return _one(sql, args)
    except Exception:
        return None


def _post(file_storage, fields, voice: dict) -> dict:
    user_id = _int((voice or {}).get("user_id"))
    if not user_id:
        return _fail("A wall picture uses the account the owner chose.")
    if not _named(file_storage):
        return _fail("Choose a picture.")
    if _ext(file_storage) not in _IMAGE_EXT:
        return _fail("Use png, jpg, gif, or webp.")
    title = _text(fields, "title", "caption") or "Photo"
    body = _text(fields, "body", limit=8000)
    visibility = (fields.get("visibility") or "public").strip().lower()
    if visibility not in ("public", "private", "personal", "followers"):
        visibility = "public"
    from app.models.social import create_post, save_identity_file
    stored = save_identity_file(file_storage, f"p{user_id}")
    if not stored:
        return _fail("Use png, jpg, gif, or webp.")
    post_id = create_post(user_id, "image", title, body, "", visibility, image_path=stored)
    if not post_id:
        return _fail("That picture post did not save.")
    posted_as = (voice or {}).get("posted_as") or "member"
    try:
        from app.models.church_community import record_posting
        record_posting("image", int(post_id), posted_as, int((voice or {}).get("campus_id") or 0), user_id)
    except Exception as exc:
        print(f"bot upload post stamp: {exc}")
    return _ok(
        {
            "place": "post",
            "post_id": int(post_id),
            "as": (voice or {}).get("as"),
            "file": stored,
        },
        {
            "action": "post.create",
            "detail": f"Picture post {post_id}",
            "target_type": "community_post",
            "target_id": int(post_id),
            "snapshot": {"post_id": int(post_id), "kind": "image", "file": stored},
        },
    )


def _login(file_storage, fields) -> dict:
    if (fields.get("surface") or "").strip().lower() == "welcome":
        return _fail("The welcome slideshow is not used. This saves a picture on the sign-in page.")
    if not _named(file_storage):
        return _fail("Choose a picture.")
    if _ext(file_storage) not in _IMAGE_EXT:
        return _fail("Use png, jpg, gif, or webp.")
    from app.utils.appearance import save_hero_image
    try:
        stored = save_hero_image("login", file_storage, _text(fields, "caption", "title"))
    except ValueError as exc:
        return _fail(str(exc) or "That picture did not save.")
    except Exception as exc:
        print(f"bot upload login: {exc}")
        return _fail("That picture did not save.", 500)
    return _ok(
        {"place": "login", "surface": "login", "file": stored},
        {
            "action": "upload.login",
            "detail": "Picture on the sign-in page",
            "target_type": "site_hero_images",
            "snapshot": {"surface": "login", "file": stored},
        },
    )


def _partner(actor_id: int, file_storage, fields) -> dict:
    if not _named(file_storage):
        return _fail("Choose a picture.")
    if _ext(file_storage) not in _IMAGE_EXT:
        return _fail("Use png, jpg, gif, or webp.")
    partner_id = _int(fields.get("partner_id") or fields.get("id"))
    title = _text(fields, "title", limit=200)
    if not partner_id and not title:
        return _fail("Send partner_id, or a title to add a ministry partner.")
    from app.models import promotions as promo
    try:
        stored = promo.save_image(file_storage, _app())
    except ValueError as exc:
        return _fail(str(exc) or "That picture did not save.")
    except Exception as exc:
        print(f"bot upload partner file: {exc}")
        return _fail("That picture did not save.", 500)
    if not stored:
        return _fail("Choose a picture.")
    try:
        if partner_id:
            if not promo.get_promotion(partner_id):
                return _fail("That ministry partner is not on this church.")
            data = {"image_path": stored}
            if title:
                data["title"] = title
            if "published" in fields or "is_published" in fields:
                data["is_published"] = _flag(fields, "published", "is_published")
            promo.update_promotion(partner_id, data, int(actor_id))
        else:
            partner_id = int(promo.create_promotion({
                "title": title,
                "subtitle": _text(fields, "subtitle"),
                "body_text": _text(fields, "body", "body_text", limit=8000),
                "image_path": stored,
                "link_url": _text(fields, "link_url", "url", limit=500),
                "link_label": _text(fields, "link_label", limit=120),
                "badge": _text(fields, "badge", limit=80),
                "is_published": _flag(fields, "published", "is_published"),
            }, int(actor_id)))
    except Exception as exc:
        print(f"bot upload partner: {exc}")
        return _fail("That picture did not save.", 500)
    return _ok(
        {"place": "partner", "partner_id": partner_id, "file": stored},
        {
            "action": "upload.partner",
            "detail": f"Picture on ministry partner {partner_id}",
            "target_type": "church_promotions",
            "target_id": partner_id,
            "snapshot": {"partner_id": partner_id, "file": stored},
        },
    )


def _giving(file_storage, fields) -> dict:
    option_id = _int(fields.get("option_id") or fields.get("id"))
    if not option_id:
        return _fail("A giving picture needs option_id.")
    if not _named(file_storage):
        return _fail("Choose a picture.")
    if _ext(file_storage) not in _IMAGE_EXT:
        return _fail("Use png, jpg, gif, or webp.")
    try:
        row = _one("SELECT id FROM online_donation_options WHERE id=%s", (option_id,))
    except Exception as exc:
        print(f"bot upload giving: {exc}")
        return _fail("That picture did not save.", 500)
    if not row:
        return _fail("That giving option is not on this church.")
    stored = _save_giving_file(file_storage)
    if not stored:
        return _fail("That picture did not save.", 500)
    try:
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            "UPDATE online_donation_options SET image_path=%s WHERE id=%s",
            (stored, option_id),
        )
    except Exception as exc:
        print(f"bot upload giving save: {exc}")
        return _fail("That picture did not save.", 500)
    return _ok(
        {"place": "giving", "option_id": option_id, "file": stored},
        {
            "action": "upload.giving",
            "detail": f"Picture on giving option {option_id}",
            "target_type": "online_donation_options",
            "target_id": option_id,
            "snapshot": {"option_id": option_id, "file": stored},
        },
    )


def _save_giving_file(file_storage) -> str | None:
    import os
    import uuid
    from werkzeug.utils import secure_filename
    folder = os.path.join(_app().static_folder, "uploads", "donations")
    os.makedirs(folder, exist_ok=True)
    original = secure_filename(file_storage.filename or "")
    ext = _ext(file_storage)
    stored = f"{uuid.uuid4().hex[:12]}_{original[:40] or 'image'}{ext}"
    file_storage.save(os.path.join(folder, stored))
    return stored


def _song(actor_id: int, file_storage, fields) -> dict:
    song_id = _int(fields.get("song_id") or fields.get("id"))
    if not song_id:
        return _fail("A song chart needs song_id.")
    if not _named(file_storage):
        return _fail("Choose a picture.")
    if _ext(file_storage) not in _SONG_EXT:
        return _fail("Use png, jpg, pdf, doc, docx, or txt.")
    try:
        row = _one("SELECT id FROM worship_songs WHERE id=%s", (song_id,))
    except Exception as exc:
        print(f"bot upload song: {exc}")
        return _fail("That chart did not save.", 500)
    if not row:
        return _fail("That song is not on this church.")
    from app.routes.worship.utils import save_chord_upload
    stored = save_chord_upload(file_storage, _app())
    if not stored:
        return _fail("Use png, jpg, pdf, doc, docx, or txt.")
    try:
        from app.models.db import get_db
        cur = get_db().cursor()
        cur.execute(
            "UPDATE worship_songs SET chords_filename=%s, updated_by=%s WHERE id=%s",
            (stored, int(actor_id), song_id),
        )
    except Exception as exc:
        print(f"bot upload song save: {exc}")
        return _fail("That chart did not save.", 500)
    return _ok(
        {"place": "song", "song_id": song_id, "file": stored},
        {
            "action": "upload.song",
            "detail": f"Chart on song {song_id}",
            "target_type": "worship_songs",
            "target_id": song_id,
            "snapshot": {"song_id": song_id, "file": stored},
        },
    )
