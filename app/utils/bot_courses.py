"""Manage a study course after it is created.

Creating a course stays in bot_areas. This module edits the whole tree,
publishes, copies, enrolls, exports, and removes lessons. A real delete
needs the hard_delete switch and confirm DELETE <id> before any row is
removed. Reverse does not put a course back.
"""

from __future__ import annotations

from app.utils.bot_areas import (
    _COURSE_STATUS,
    _clip,
    _minutes,
    _plan_block,
    _sort,
    course_open,
    course_save,
)
from app.utils.bot_guard import confirm_delete
from app.utils.bot_illustration_fields import truthy
from app.utils.bot_sermon_common import _db, _fail, _ok

def _audit(action: str, target_type: str, target_id, detail: str, snapshot: dict) -> dict:
    return {
        "action": action,
        "detail": detail,
        "target_type": target_type,
        "target_id": int(target_id) if target_id else None,
        "snapshot": snapshot,
    }


def _int_id(value):
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 1:
        return None
    return number


def _given_id(raw, label: str):
    if raw in (None, ""):
        return None, None
    number = _int_id(raw)
    if not number:
        return None, _fail(f"A {label} id has to be a number.")
    return number, None


def _explicit_false(value) -> bool:
    if value is False or value == 0:
        return True
    return str(value if value is not None else "").strip().lower() in {"0", "false", "no", "off"}


def _hard_required(body, row_id: int, hard_on: bool, action: str):
    if not hard_on:
        out = _fail("Hard delete is turned off for this key.", 403, action)
        out["code"] = "hard_delete"
        out["missing"] = ["hard_delete"]
        return out
    wants, err = confirm_delete(body or {}, int(row_id))
    if not wants or err:
        return _fail(err or f'Send confirm as "DELETE {int(row_id)}".', 400, action)
    return None


def _series_row(series_id: int):
    cur = _db().cursor()
    cur.execute(
        "SELECT id, title, status FROM curriculum_series WHERE id=%s",
        (int(series_id),),
    )
    return cur.fetchone()


def _lesson_ids(series_id: int) -> list[int]:
    cur = _db().cursor()
    cur.execute(
        "SELECT id FROM curriculum_lessons WHERE series_id=%s ORDER BY sort_order, id",
        (int(series_id),),
    )
    return [int(row["id"]) for row in cur.fetchall() or []]


def _block_ids(lesson_id: int) -> list[int]:
    cur = _db().cursor()
    cur.execute(
        "SELECT id FROM curriculum_blocks WHERE lesson_id=%s ORDER BY sort_order, id",
        (int(lesson_id),),
    )
    return [int(row["id"]) for row in cur.fetchall() or []]


def _purge_series(series_id: int) -> None:
    cur = _db().cursor()
    sid = int(series_id)
    cur.execute(
        """
        DELETE c FROM curriculum_choices c
        JOIN curriculum_blocks b ON b.id = c.block_id
        JOIN curriculum_lessons l ON l.id = b.lesson_id
        WHERE l.series_id=%s
        """,
        (sid,),
    )
    cur.execute(
        """
        DELETE b FROM curriculum_blocks b
        JOIN curriculum_lessons l ON l.id = b.lesson_id
        WHERE l.series_id=%s
        """,
        (sid,),
    )
    cur.execute("DELETE FROM curriculum_lessons WHERE series_id=%s", (sid,))
    cur.execute("DELETE FROM curriculum_progress WHERE series_id=%s", (sid,))
    cur.execute("DELETE FROM curriculum_enrollments WHERE series_id=%s", (sid,))
    cur.execute("DELETE FROM curriculum_series WHERE id=%s", (sid,))


def _purge_lesson(series_id: int, lesson_id: int) -> bool:
    cur = _db().cursor()
    cur.execute(
        "SELECT id FROM curriculum_lessons WHERE id=%s AND series_id=%s",
        (int(lesson_id), int(series_id)),
    )
    if not cur.fetchone():
        return False
    cur.execute(
        """
        DELETE c FROM curriculum_choices c
        JOIN curriculum_blocks b ON b.id = c.block_id
        WHERE b.lesson_id=%s
        """,
        (int(lesson_id),),
    )
    cur.execute("DELETE FROM curriculum_blocks WHERE lesson_id=%s", (int(lesson_id),))
    cur.execute("DELETE FROM curriculum_progress WHERE lesson_id=%s", (int(lesson_id),))
    cur.execute(
        "DELETE FROM curriculum_lessons WHERE id=%s AND series_id=%s",
        (int(lesson_id), int(series_id)),
    )
    return True


def _purge_block(series_id: int, block_id: int) -> bool:
    cur = _db().cursor()
    cur.execute(
        """
        SELECT b.id
        FROM curriculum_blocks b
        JOIN curriculum_lessons l ON l.id = b.lesson_id
        WHERE b.id=%s AND l.series_id=%s
        """,
        (int(block_id), int(series_id)),
    )
    if not cur.fetchone():
        return False
    cur.execute("DELETE FROM curriculum_choices WHERE block_id=%s", (int(block_id),))
    cur.execute("DELETE FROM curriculum_progress WHERE block_id=%s", (int(block_id),))
    cur.execute("DELETE FROM curriculum_blocks WHERE id=%s", (int(block_id),))
    return True


def _series_changes(body: dict) -> dict:
    data = {}
    if "title" in body:
        data["title"] = _clip(body.get("title"), 255)
    if "subtitle" in body:
        data["subtitle"] = _clip(body.get("subtitle"), 500) or None
    if "description" in body:
        data["description"] = _clip(body.get("description"), 20000) or None
    if "cover_image" in body:
        data["cover_image"] = _clip(body.get("cover_image"), 500) or None
    if "audience" in body:
        data["audience"] = _clip(body.get("audience"), 40) or "everyone"
    if "status" in body:
        data["status"] = _clip(body.get("status"), 24).lower()
    if "visibility" in body:
        data["visibility"] = body.get("visibility")
    if "tags" in body:
        data["tags"] = _clip(body.get("tags"), 500) or None
    if "estimated_minutes" in body:
        data["estimated_minutes"] = _minutes(body.get("estimated_minutes"))
    if "sort_order" in body:
        data["sort_order"] = _sort(body.get("sort_order"))
    if "access_levels" in body:
        data["access_levels"] = body.get("access_levels")
    if "access_level" in body:
        data["access_level"] = body.get("access_level")
    return data


def _model_block(block: dict, index: int, *, create: bool) -> dict:
    planned = _plan_block(block, index) or {}
    data = {}
    if create or "block_type" in block:
        data["block_type"] = planned["block_type"]
    fields = (
        "title", "body", "media_url", "media_alt", "question_prompt",
        "explanation", "points", "is_required", "sort_order",
    )
    if create:
        for key in fields:
            data[key] = planned[key]
        data["correct_answers"] = planned["correct_answers"]
        data["settings"] = planned["settings"]
        data["choices"] = planned["choices"]
        return data
    for key in fields:
        if key in block:
            data[key] = planned[key]
    if "correct_answers" in block or "correct_answers_json" in block:
        data["correct_answers"] = planned["correct_answers"]
    if "settings" in block or "settings_json" in block or block.get("scripture_reference"):
        data["settings"] = planned["settings"]
    if "choices" in block:
        data["choices"] = planned["choices"]
    return data


def _tree_plan(series_id: int, body: dict):
    lessons = body.get("lessons")
    has_list = isinstance(lessons, list)
    replace = bool(truthy(body.get("replace")) and has_list)
    if has_list and len(lessons) > 40:
        return None, _fail("Send at most 40 lessons in one course.")
    existing = _lesson_ids(series_id)
    existing_set = set(existing)
    blocks_by_lesson = {lesson_id: set(_block_ids(lesson_id)) for lesson_id in existing}
    destructive = replace
    parsed = []
    if has_list:
        for lesson in lessons:
            if not isinstance(lesson, dict):
                return None, _fail("Each lesson needs to be an object.")
            lesson_id, err = _given_id(lesson.get("id"), "lesson")
            if err:
                return None, err
            if lesson_id and lesson_id not in existing_set:
                return None, _fail("That lesson is not on this course.")
            deleting = truthy(lesson.get("delete"))
            if deleting:
                if not lesson_id:
                    return None, _fail("Name the lesson to delete.")
                destructive = True
            if "title" in lesson and not deleting and not _clip(lesson.get("title"), 255):
                return None, _fail("A lesson needs a title.")
            raw_blocks = lesson.get("blocks")
            block_list = raw_blocks if isinstance(raw_blocks, list) else None
            if block_list is not None and len(block_list) > 40:
                return None, _fail("Send at most 40 blocks in one lesson.")
            known = blocks_by_lesson.get(lesson_id, set()) if lesson_id else set()
            if block_list is not None:
                for block in block_list:
                    if not isinstance(block, dict):
                        return None, _fail("Each block needs to be an object.")
                    block_id, err = _given_id(block.get("id"), "block")
                    if err:
                        return None, err
                    if block_id and block_id not in known:
                        return None, _fail("That block is not on this lesson.")
                    if truthy(block.get("delete")):
                        if not block_id:
                            return None, _fail("Name the block to delete.")
                        destructive = True
                if replace or truthy(lesson.get("replace")):
                    destructive = True
            parsed.append({
                "raw": lesson,
                "id": lesson_id,
                "delete": deleting,
                "has_blocks": block_list is not None,
                "replace_blocks": bool(block_list is not None and (replace or truthy(lesson.get("replace")))),
            })
    return {
        "existing": existing,
        "blocks_by_lesson": blocks_by_lesson,
        "lessons": parsed,
        "replace": replace,
        "destructive": destructive,
    }, None


def _useful(plan: dict, changes: dict) -> bool:
    if changes or plan["destructive"]:
        return True
    for item in plan["lessons"]:
        if item["delete"]:
            return True
        if item["id"] or _clip(item["raw"].get("title"), 255):
            return True
    return False


def course_update(actor_id: int, series_id: int, body: dict, *, hard_on: bool = False) -> dict:
    action = "course.update"
    if not isinstance(body, dict):
        return _fail("Send a JSON body.", 400, action)
    if "title" in body and not _clip(body.get("title"), 255):
        return _fail("A study course needs a title.", 400, action)
    if "status" in body and _clip(body.get("status"), 24).lower() not in _COURSE_STATUS:
        return _fail("Status is draft, published, or archived.", 400, action)
    changes = _series_changes(body)
    if not changes and not isinstance(body.get("lessons"), list):
        return _fail("Send a title, cover, status, or the lesson tree.", 400, action)
    if not _series_row(series_id):
        return _fail("That study course was not found.", 404, action)
    plan, err = _tree_plan(series_id, body)
    if err:
        return err
    if not _useful(plan, changes):
        return _fail("Send a title, cover, status, or the lesson tree.", 400, action)
    if plan["destructive"] and not truthy(body.get("dry_run")):
        blocked = _hard_required(body, series_id, hard_on, action)
        if blocked:
            return blocked
    if truthy(body.get("dry_run")):
        return _ok({
            "series_id": int(series_id),
            "dry_run": True,
            "wrote": 0,
            "would_delete": bool(plan["destructive"]),
        })
    try:
        _apply_tree(series_id, changes, plan)
    except Exception as exc:
        print(f"bot course update: {exc}")
        return _fail("That study course did not save.", 500, action)
    opened = course_open(series_id)
    if not opened.get("ok"):
        return opened
    snapshot = {"series_id": int(series_id), "user_id": int(actor_id)}
    if plan["destructive"]:
        snapshot["hard"] = True
    opened["log"] = _audit(action, "curriculum_series", series_id, f"Updated study course {series_id}", snapshot)
    return opened


def _apply_tree(series_id: int, changes: dict, plan: dict) -> None:
    from app.models.pastoral.curriculum import create_block, create_lesson, update_block, update_lesson, update_series
    if changes:
        update_series(int(series_id), changes)
    purged = set()
    if plan["replace"]:
        keep = {item["id"] for item in plan["lessons"] if item["id"] and not item["delete"]}
        for lesson_id in plan["existing"]:
            if lesson_id not in keep:
                _purge_lesson(series_id, lesson_id)
                purged.add(lesson_id)
    for item in plan["lessons"]:
        raw = item["raw"]
        if item["delete"]:
            if item["id"] not in purged:
                _purge_lesson(series_id, item["id"])
            continue
        if item["id"]:
            fields = _lesson_fields(raw)
            if fields:
                update_lesson(item["id"], fields)
            lesson_id = item["id"]
        else:
            title = _clip(raw.get("title"), 255)
            if not title:
                continue
            status = _clip(raw.get("status") or "draft", 24).lower()
            if status not in _COURSE_STATUS:
                status = "draft"
            lesson_id = int(create_lesson(int(series_id), {
                "title": title,
                "summary": _clip(raw.get("summary"), 8000) or None,
                "status": status,
                "estimated_minutes": _minutes(raw.get("estimated_minutes")),
                "sort_order": _sort(raw.get("sort_order"), len(plan["existing"])),
            }))
        if not item["has_blocks"]:
            continue
        known = plan["blocks_by_lesson"].get(item["id"], set()) if item["id"] else set()
        if item["replace_blocks"]:
            keep_blocks = set()
            for block in raw.get("blocks") or []:
                block_id = _int_id(block.get("id")) if isinstance(block, dict) else None
                if block_id and not truthy(block.get("delete")):
                    keep_blocks.add(block_id)
            for block_id in known:
                if block_id not in keep_blocks:
                    _purge_block(series_id, block_id)
        for index, block in enumerate(raw.get("blocks") or []):
            if not isinstance(block, dict):
                continue
            if truthy(block.get("delete")):
                _purge_block(series_id, _int_id(block.get("id")))
                continue
            block_id = _int_id(block.get("id"))
            payload = _model_block(block, index, create=not block_id)
            if block_id:
                if payload:
                    update_block(block_id, payload)
            else:
                create_block(lesson_id, payload)


def _lesson_fields(raw: dict) -> dict:
    fields = {}
    if "title" in raw:
        fields["title"] = _clip(raw.get("title"), 255)
    if "summary" in raw:
        fields["summary"] = _clip(raw.get("summary"), 8000) or None
    if "status" in raw:
        status = _clip(raw.get("status") or "draft", 24).lower()
        fields["status"] = status if status in _COURSE_STATUS else "draft"
    if "estimated_minutes" in raw:
        fields["estimated_minutes"] = _minutes(raw.get("estimated_minutes"))
    if "sort_order" in raw:
        fields["sort_order"] = _sort(raw.get("sort_order"))
    return fields


def course_publish(actor_id: int, series_id: int, body: dict) -> dict:
    action = "course.publish"
    if not isinstance(body, dict):
        body = {}
    status = _clip(body.get("status") or "published", 24).lower()
    if status not in _COURSE_STATUS:
        return _fail("Status is draft, published, or archived.", 400, action)
    if not _series_row(series_id):
        return _fail("That study course was not found.", 404, action)
    if truthy(body.get("dry_run")):
        return _ok({
            "series_id": int(series_id),
            "dry_run": True,
            "wrote": 0,
            "status": status,
        })
    from app.models.pastoral.curriculum import update_series
    try:
        update_series(int(series_id), {"status": status})
        cur = _db().cursor()
        if status == "published" and not _explicit_false(body.get("lessons")):
            cur.execute(
                """
                UPDATE curriculum_lessons
                SET status='published'
                WHERE series_id=%s AND status<>'archived'
                """,
                (int(series_id),),
            )
        elif status == "archived" and truthy(body.get("lessons")):
            cur.execute(
                "UPDATE curriculum_lessons SET status='archived' WHERE series_id=%s",
                (int(series_id),),
            )
    except Exception as exc:
        print(f"bot course publish: {exc}")
        return _fail("That study course did not publish.", 500, action)
    opened = course_open(series_id)
    if not opened.get("ok"):
        return opened
    opened["log"] = _audit(
        action, "curriculum_series", series_id, f"Set study course {series_id} to {status}",
        {"series_id": int(series_id), "status": status, "user_id": int(actor_id)},
    )
    return opened


def course_duplicate(actor_id: int, series_id: int, body: dict) -> dict:
    action = "course.duplicate"
    if not isinstance(body, dict):
        body = {}
    from app.models.pastoral.curriculum import duplicate_series, update_series
    try:
        new_id = int(duplicate_series(int(series_id), int(actor_id)))
    except ValueError:
        return _fail("That study course was not found.", 404, action)
    except Exception as exc:
        print(f"bot course duplicate: {exc}")
        return _fail("That study course was not copied.", 500, action)
    title = _clip(body.get("title"), 255)
    if title:
        update_series(new_id, {"title": title})
    opened = course_open(new_id)
    if not opened.get("ok"):
        return opened
    opened["log"] = _audit(
        action, "curriculum_series", new_id, f"Copied study course {series_id}",
        {"series_id": new_id, "source_id": int(series_id), "user_id": int(actor_id)},
    )
    return opened


def course_delete(actor_id: int, series_id: int, body: dict, *, hard_on: bool = False) -> dict:
    action = "course.delete"
    if not _series_row(series_id):
        return _fail("That study course was not found.", 404, action)
    blocked = _hard_required(body or {}, series_id, hard_on, action)
    if blocked:
        return blocked
    try:
        _purge_series(series_id)
    except Exception as exc:
        print(f"bot course delete: {exc}")
        return _fail("That study course was not deleted.", 500, action)
    return _ok(
        {"series_id": int(series_id), "deleted": True},
        _audit(action, "curriculum_series", series_id, f"Deleted study course {series_id}", {
            "series_id": int(series_id), "hard": True, "user_id": int(actor_id),
        }),
    )


def lesson_delete(actor_id: int, series_id: int, lesson_id: int, body: dict, *, hard_on: bool = False) -> dict:
    action = "course.lesson_delete"
    if not _series_row(series_id):
        return _fail("That study course was not found.", 404, action)
    if lesson_id not in set(_lesson_ids(series_id)):
        return _fail("That lesson is not on this course.", 404, action)
    blocked = _hard_required(body or {}, lesson_id, hard_on, action)
    if blocked:
        return blocked
    try:
        if not _purge_lesson(series_id, lesson_id):
            return _fail("That lesson is not on this course.", 404, action)
    except Exception as exc:
        print(f"bot lesson delete: {exc}")
        return _fail("That lesson was not deleted.", 500, action)
    return _ok(
        {"series_id": int(series_id), "lesson_id": int(lesson_id), "deleted": True},
        _audit(action, "curriculum_lessons", lesson_id, f"Deleted lesson {lesson_id}", {
            "series_id": int(series_id), "lesson_id": int(lesson_id), "hard": True,
            "user_id": int(actor_id),
        }),
    )


def block_delete(actor_id: int, series_id: int, block_id: int, body: dict, *, hard_on: bool = False) -> dict:
    action = "course.block_delete"
    if not _series_row(series_id):
        return _fail("That study course was not found.", 404, action)
    cur = _db().cursor()
    cur.execute(
        """
        SELECT b.id
        FROM curriculum_blocks b
        JOIN curriculum_lessons l ON l.id = b.lesson_id
        WHERE b.id=%s AND l.series_id=%s
        """,
        (int(block_id), int(series_id)),
    )
    if not cur.fetchone():
        return _fail("That block is not on this course.", 404, action)
    blocked = _hard_required(body or {}, block_id, hard_on, action)
    if blocked:
        return blocked
    try:
        if not _purge_block(series_id, block_id):
            return _fail("That block is not on this course.", 404, action)
    except Exception as exc:
        print(f"bot block delete: {exc}")
        return _fail("That block was not deleted.", 500, action)
    return _ok(
        {"series_id": int(series_id), "block_id": int(block_id), "deleted": True},
        _audit(action, "curriculum_blocks", block_id, f"Deleted block {block_id}", {
            "series_id": int(series_id), "block_id": int(block_id), "hard": True,
            "user_id": int(actor_id),
        }),
    )


def _id_list(body: dict):
    raw = body.get("ids") if isinstance(body, dict) else None
    if not isinstance(raw, list) or not raw:
        return [], _fail("Send ids for the new order.")
    ids = []
    for item in raw:
        number = _int_id(item)
        if not number:
            return [], _fail("Each id has to be a number.")
        ids.append(number)
    if len(ids) != len(set(ids)):
        return [], _fail("Send each id once.")
    return ids, None


def lessons_reorder(actor_id: int, series_id: int, body: dict) -> dict:
    action = "course.reorder"
    if not _series_row(series_id):
        return _fail("That study course was not found.", 404, action)
    ids, err = _id_list(body or {})
    if err:
        return err
    current = _lesson_ids(series_id)
    if sorted(ids) != sorted(current):
        return _fail("Send every lesson id on this course, once each.", 400, action)
    from app.models.pastoral.curriculum import reorder_lessons
    try:
        reorder_lessons(int(series_id), ids)
    except Exception as exc:
        print(f"bot lesson reorder: {exc}")
        return _fail("Those lessons were not reordered.", 500, action)
    return _ok(
        {"series_id": int(series_id), "ids": ids},
        _audit(action, "curriculum_series", series_id, f"Reordered lessons on {series_id}", {
            "series_id": int(series_id), "ids": ids, "user_id": int(actor_id),
        }),
    )


def blocks_reorder(actor_id: int, series_id: int, lesson_id: int, body: dict) -> dict:
    action = "course.reorder_blocks"
    if lesson_id not in set(_lesson_ids(series_id)):
        return _fail("That lesson is not on this course.", 404, action)
    ids, err = _id_list(body or {})
    if err:
        return err
    current = _block_ids(lesson_id)
    if sorted(ids) != sorted(current):
        return _fail("Send every block id on this lesson, once each.", 400, action)
    from app.models.pastoral.curriculum import reorder_blocks
    try:
        reorder_blocks(int(lesson_id), ids)
    except Exception as exc:
        print(f"bot block reorder: {exc}")
        return _fail("Those blocks were not reordered.", 500, action)
    return _ok(
        {"series_id": int(series_id), "lesson_id": int(lesson_id), "ids": ids},
        _audit(action, "curriculum_lessons", lesson_id, f"Reordered blocks on lesson {lesson_id}", {
            "series_id": int(series_id), "lesson_id": int(lesson_id), "ids": ids,
            "user_id": int(actor_id),
        }),
    )


def _people(body: dict):
    if not isinstance(body, dict):
        return [], _fail("Send a JSON body.")
    explicit = []
    if body.get("user_id") not in (None, ""):
        explicit.append(body.get("user_id"))
    extra = body.get("user_ids")
    if isinstance(extra, list):
        explicit.extend(extra)
    elif extra not in (None, ""):
        explicit.append(extra)
    group_raw = body.get("group_id")
    if not explicit and group_raw in (None, ""):
        return [], _fail("Send user_id, user_ids, or group_id.")
    ids = []
    seen = set()
    for item in explicit:
        number = _int_id(item)
        if not number:
            return [], _fail("Each user_id has to be a number.")
        if number not in seen:
            seen.add(number)
            ids.append(number)
    cur = _db().cursor()
    if group_raw not in (None, ""):
        group_id = _int_id(group_raw)
        if not group_id:
            return [], _fail("group_id has to be a number.")
        cur.execute("SELECT id FROM `groups` WHERE id=%s", (group_id,))
        if not cur.fetchone():
            return [], _fail("That group was not found.", 404)
        cur.execute("SELECT user_id FROM user_groups WHERE group_id=%s", (group_id,))
        for row in cur.fetchall() or []:
            number = _int_id(row.get("user_id"))
            if number and number not in seen:
                seen.add(number)
                ids.append(number)
    if len(ids) > 200:
        return [], _fail("Send at most 200 people.")
    if ids:
        marks = ",".join(["%s"] * len(ids))
        cur.execute(f"SELECT id FROM users WHERE id IN ({marks})", ids)
        found = {int(row["id"]) for row in cur.fetchall() or []}
        explicit_ids = []
        seen_explicit = set()
        for item in explicit:
            number = _int_id(item)
            if number and number not in seen_explicit:
                seen_explicit.add(number)
                explicit_ids.append(number)
        if any(number not in found for number in explicit_ids):
            return [], _fail("That person was not found.", 404)
        ids = [number for number in ids if number in found]
    return ids, None


def course_enroll(actor_id: int, series_id: int, body: dict) -> dict:
    action = "course.enroll"
    if not _series_row(series_id):
        return _fail("That study course was not found.", 404, action)
    ids, err = _people(body or {})
    if err:
        return err
    from app.models.pastoral.curriculum import ensure_enrollment
    try:
        for user_id in ids:
            ensure_enrollment(int(user_id), int(series_id))
    except Exception as exc:
        print(f"bot course enroll: {exc}")
        return _fail("Those people were not enrolled.", 500, action)
    return _ok(
        {"series_id": int(series_id), "enrolled": len(ids), "user_ids": ids},
        _audit(action, "curriculum_series", series_id, f"Enrolled {len(ids)} on course {series_id}", {
            "series_id": int(series_id), "user_ids": ids, "user_id": int(actor_id),
        }),
    )


def course_unenroll(actor_id: int, series_id: int, body: dict) -> dict:
    action = "course.unenroll"
    if not _series_row(series_id):
        return _fail("That study course was not found.", 404, action)
    ids, err = _people(body or {})
    if err:
        return err
    removed = 0
    try:
        if ids:
            cur = _db().cursor()
            marks = ",".join(["%s"] * len(ids))
            cur.execute(
                f"DELETE FROM curriculum_enrollments WHERE series_id=%s AND user_id IN ({marks})",
                [int(series_id), *ids],
            )
            removed = int(cur.rowcount or 0)
    except Exception as exc:
        print(f"bot course unenroll: {exc}")
        return _fail("Those people were not removed.", 500, action)
    return _ok(
        {"series_id": int(series_id), "removed": removed, "user_ids": ids},
        _audit(action, "curriculum_series", series_id, f"Unenrolled {removed} on course {series_id}", {
            "series_id": int(series_id), "user_ids": ids, "user_id": int(actor_id),
        }),
    )


def course_progress(series_id: int) -> dict:
    if not _series_row(series_id):
        return _fail("That study course was not found.", 404)
    cur = _db().cursor()
    cur.execute(
        """
        SELECT e.user_id, e.status, e.progress_pct, u.first_name, u.last_name
        FROM curriculum_enrollments e
        JOIN users u ON u.id = e.user_id
        WHERE e.series_id=%s
        ORDER BY u.last_name, u.first_name, e.user_id
        LIMIT 200
        """,
        (int(series_id),),
    )
    people = list(cur.fetchall() or [])
    cur.execute(
        """
        SELECT user_id,
               SUM(CASE WHEN status='answered' THEN 1 ELSE 0 END) AS answered,
               SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) AS correct
        FROM curriculum_progress
        WHERE series_id=%s
        GROUP BY user_id
        """,
        (int(series_id),),
    )
    by_user = {int(row["user_id"]): row for row in cur.fetchall() or [] if row.get("user_id")}
    rows = []
    for person in people:
        user_id = int(person["user_id"])
        got = by_user.get(user_id) or {}
        name = " ".join(
            part for part in (_clip(person.get("first_name"), 80), _clip(person.get("last_name"), 80)) if part
        ).strip()
        try:
            percent = float(person.get("progress_pct") or 0)
        except (TypeError, ValueError):
            percent = 0.0
        rows.append({
            "user_id": user_id,
            "name": name or f"Member {user_id}",
            "status": person.get("status"),
            "progress_pct": percent,
            "answered": int(got.get("answered") or 0),
            "correct": int(got.get("correct") or 0),
        })
    from app.models.pastoral.curriculum import series_stats
    return _ok({
        "series_id": int(series_id),
        "people": rows,
        "count": len(rows),
        "series_stats": series_stats(int(series_id)),
    })


def _filename(title: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (title or "course"))[:60]
    safe = safe.strip("_") or "course"
    return f"{safe}.md"


def _download(title: str, text: str, action: str, target_type: str, target_id, detail: str, data: dict) -> dict:
    filename = _filename(title)
    data = dict(data)
    data["filename"] = filename
    result = _ok(data, _audit(action, target_type, target_id, detail, {"filename": filename}))
    result["download"] = {
        "bytes": text.encode("utf-8"),
        "mimetype": "text/markdown; charset=utf-8",
        "disposition": f'attachment; filename="{filename}"',
    }
    return result


def course_export(series_id: int) -> dict:
    from app.models.pastoral.content_export import format_curriculum_series_markdown
    from app.models.pastoral.curriculum import get_series, list_blocks, list_lessons
    series = get_series(int(series_id))
    if not series:
        return _fail("That study course was not found.", 404, "course.export")
    lessons = list_lessons(int(series_id))
    for lesson in lessons:
        lesson["blocks"] = list_blocks(int(lesson["id"]))
    text = format_curriculum_series_markdown(series, lessons)
    return _download(
        series.get("title") or "course",
        text,
        "course.export",
        "curriculum_series",
        series_id,
        f"Exported study course {series_id}",
        {"series_id": int(series_id)},
    )


def lesson_export(series_id: int, lesson_id: int) -> dict:
    from app.models.pastoral.content_export import format_curriculum_lesson_markdown
    from app.models.pastoral.curriculum import get_lesson, get_series, list_blocks
    series = get_series(int(series_id))
    lesson = get_lesson(int(lesson_id))
    if not series or not lesson or int(lesson.get("series_id") or 0) != int(series_id):
        return _fail("That lesson is not on this course.", 404, "course.lesson_export")
    blocks = list_blocks(int(lesson_id))
    text = format_curriculum_lesson_markdown(series, lesson, blocks)
    return _download(
        lesson.get("title") or series.get("title") or "lesson",
        text,
        "course.lesson_export",
        "curriculum_lessons",
        lesson_id,
        f"Exported lesson {lesson_id}",
        {"series_id": int(series_id), "lesson_id": int(lesson_id)},
    )


def _sermon_row(sermon_id: int):
    cur = _db().cursor()
    cur.execute(
        """
        SELECT id, title, primary_passage, notes
        FROM pastoral_sermons
        WHERE id=%s AND removed_at IS NULL
        """,
        (int(sermon_id),),
    )
    return cur.fetchone()


def _sermon_lesson(sermon: dict):
    cur = _db().cursor()
    cur.execute(
        """
        SELECT title, content, scripture_reference, sort_order
        FROM sermon_sections
        WHERE sermon_id=%s AND removed_at IS NULL
        ORDER BY sort_order, id
        """,
        (int(sermon["id"]),),
    )
    sections = list(cur.fetchall() or [])
    if len(sections) > 40:
        return None, _fail("That sermon has more than 40 sections.")
    blocks = []
    if sections:
        for section in sections:
            reference = _clip(section.get("scripture_reference"), 255)
            blocks.append({
                "block_type": "scripture" if reference else "text",
                "title": _clip(section.get("title"), 255) or None,
                "body": _clip(section.get("content"), 100000) or None,
                "scripture_reference": reference or None,
                "sort_order": int(section.get("sort_order") or 0),
            })
    else:
        blocks.append({
            "block_type": "text",
            "body": _clip(sermon.get("notes"), 100000) or None,
        })
    return {
        "title": _clip(sermon.get("title"), 255) or "Sermon",
        "summary": _clip(sermon.get("primary_passage"), 8000) or None,
        "status": "draft",
        "blocks": blocks,
    }, None


def course_from_sermons(actor_id: int, body: dict) -> dict:
    action = "course.from_sermons"
    if not isinstance(body, dict):
        return _fail("Send a JSON body.", 400, action)
    ordered = []
    seen = set()
    raw_ids = body.get("sermon_ids")
    raw_list = raw_ids if isinstance(raw_ids, list) else ([] if raw_ids in (None, "") else [raw_ids])
    source = None
    source_id, err = _given_id(body.get("series_id"), "series")
    if err:
        return err
    if source_id:
        from app.models.pastoral.curriculum import get_series
        source = get_series(source_id)
        if not source:
            return _fail("That series was not found.", 404, action)
        cur = _db().cursor()
        cur.execute(
            "SELECT sermon_id FROM sermon_series_links WHERE series_id=%s ORDER BY sermon_id",
            (source_id,),
        )
        for row in cur.fetchall() or []:
            number = _int_id(row.get("sermon_id"))
            if number and number not in seen:
                seen.add(number)
                ordered.append(number)
    for item in raw_list:
        number, err = _given_id(item, "sermon")
        if err:
            return err
        if number and number not in seen:
            seen.add(number)
            ordered.append(number)
    if not ordered:
        return _fail("Send sermon_ids or a series_id with sermons linked to it.", 400, action)
    if len(ordered) > 40:
        return _fail("Send at most 40 sermons.", 400, action)
    lessons = []
    for sermon_id in ordered:
        sermon = _sermon_row(sermon_id)
        if not sermon:
            return _fail("That sermon was not found.", 404, action)
        lesson, err = _sermon_lesson(sermon)
        if err:
            return err
        lessons.append(lesson)
    course_id, err = _given_id(body.get("course_id"), "course")
    if err:
        return err
    if course_id:
        if not _series_row(course_id):
            return _fail("That study course was not found.", 404, action)
        if len(_lesson_ids(course_id)) + len(lessons) > 40:
            return _fail("Send at most 40 lessons in one course.", 400, action)
        if truthy(body.get("dry_run")):
            return _ok({
                "series_id": int(course_id),
                "dry_run": True,
                "wrote": 0,
                "lessons": lessons,
            })
        return _append_sermon_lessons(actor_id, course_id, lessons, action)
    title = _clip(body.get("title"), 255)
    if not title and source:
        title = _clip(source.get("title"), 255)
    if not title:
        title = "Sermon course"
    payload = {"title": title, "status": "draft", "lessons": lessons}
    if truthy(body.get("dry_run")):
        payload["dry_run"] = True
    saved = course_save(int(actor_id), payload)
    if not saved.get("ok") or truthy(body.get("dry_run")):
        return saved
    series_id = int((saved.get("data") or {}).get("course", {}).get("id") or 0)
    saved["log"] = _audit(
        action, "curriculum_series", series_id, f"Turned sermons into course {series_id}",
        {"series_id": series_id, "sermon_ids": ordered, "user_id": int(actor_id)},
    )
    return saved


def _append_sermon_lessons(actor_id: int, series_id: int, lessons: list, action: str) -> dict:
    from app.models.pastoral.curriculum import create_block, create_lesson
    start = len(_lesson_ids(series_id))
    lesson_ids = []
    try:
        for index, lesson in enumerate(lessons):
            lesson_id = int(create_lesson(int(series_id), {
                "title": lesson["title"],
                "summary": lesson["summary"],
                "status": "draft",
                "sort_order": start + index,
            }))
            lesson_ids.append(lesson_id)
            for block_index, block in enumerate(lesson["blocks"]):
                reference = block.get("scripture_reference")
                create_block(lesson_id, {
                    "block_type": block.get("block_type") or "text",
                    "title": block.get("title"),
                    "body": block.get("body"),
                    "sort_order": block.get("sort_order", block_index),
                    "settings": {"reference": reference} if reference else {},
                    "correct_answers": [],
                })
    except Exception as exc:
        print(f"bot course from sermons: {exc}")
        return _fail("Those sermons were not added.", 500, action)
    opened = course_open(series_id)
    if not opened.get("ok"):
        return opened
    opened["data"]["lesson_ids"] = lesson_ids
    opened["log"] = _audit(
        action, "curriculum_series", series_id, f"Added sermons to course {series_id}",
        {"series_id": int(series_id), "lesson_ids": lesson_ids, "user_id": int(actor_id)},
    )
    return opened
