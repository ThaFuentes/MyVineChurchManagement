"""Named areas on top of the desks: courses, the apps menu, moderation, insights.

The desks already hold the rows. These calls are the shape a person uses
on the site: a whole study course, which apps are in the menu, the
moderation queue, and an insights report.
"""

from __future__ import annotations

from app.utils.bot_desks import secret_column
from app.utils.bot_sermon_common import _db, _fail, _jsonish, _limit, _ok

_COURSE_STATUS = {"draft", "published", "archived"}
_BLOCK_TYPES = {"text", "image", "video", "choice", "true_false", "fill", "scripture"}


def covers() -> dict:
    """The names on the church menu, and where the bot opens them."""
    return {
        "my_page": {
            "desks": ["member_spaces", "page_links", "page_photos", "page_pins", "page_photo_comments"],
            "about": "Open with user_id. An owner, or an admin the owner allowed, can update that page. POST /api/bot/upload place=page scope=member slot=photo|banner|avatar puts a picture on this account.",
        },
        "church_page": {
            "desks": ["church_pages", "church_page_editors", "page_photos", "community_posts"],
            "about": "Open with campus_id. 0 is the main church page. church_page_editors is who was allowed to edit or post. POST /api/bot/upload place=page scope=church slot=photo|banner|avatar puts a picture on it.",
        },
        "notes": {
            "desks": ["bible_notes", "pastoral_care_notes", "pastoral_vault", "worship_member_notes"],
            "about": "Bible notes stay on the account this bot acts as. Sermon research notes are the vault.",
        },
        "find_people": {
            "desks": ["users", "groups", "user_groups", "family_relations"],
            "about": "People search is the users desk with ?q=. GET /api/bot/groups and GET /api/bot/groups/<id> open a group. POST /api/bot/groups/<id>/members adds, changes, or removes a member. Family links are family_relations. Passwords, family PINs, and pickup codes are refused.",
        },
        "events": {
            "desks": ["events", "event_comments", "event_registrations", "potluck_signups"],
            "about": "GET /api/bot/desk/events lists events. ?id= opens one. POST updates the safe columns on that row. Registrations and potluck signups are their own desks. Comments are GET /api/bot/comments?area=event.",
        },
        "prayers": {
            "desks": ["prayers", "prayers_added"],
            "about": "GET /api/bot/desk/prayers lists prayer requests. ?id= opens one. POST updates the safe columns. prayers_added is the extra notes on a request. Comments are GET /api/bot/comments?area=prayer.",
        },
        "sermons": {
            "desks": ["sermons", "sermon_comments", "pastoral_sermons", "sermon_sections"],
            "about": "The public sermon library is sermons. The sermon builder drafts are pastoral_sermons and sermon_sections, opened with GET /api/bot/sermons when Sermon builder is on. Comments are GET /api/bot/comments?area=sermon. A sermon is hidden, not deleted.",
        },
        "announcements": {
            "desks": ["announcements", "announcement_comments"],
            "about": "GET /api/bot/desk/announcements lists announcements. ?id= opens one. POST updates the safe columns. Comments are GET /api/bot/comments?area=announcement.",
        },
        "dreams": {
            "desks": ["dreams", "dream_comments"],
            "about": "GET /api/bot/desk/dreams lists dreams the desk will show. Personal, pastor-only, and unaccepted journal entries stay off the short read. Comments are GET /api/bot/comments?area=dream.",
        },
        "prophecies": {
            "desks": ["prophecies", "prophecy_comments"],
            "about": "GET /api/bot/desk/prophecies lists prophecies the desk will show. Personal, pastor-only, and unaccepted journal entries stay off the short read. Comments are GET /api/bot/comments?area=prophecy.",
        },
        "bible": {
            "desks": ["bible_books", "bible_verses", "bible_translations", "bible_highlights", "bible_notes", "bible_favorites"],
            "about": "Scripture lookup for a sermon is GET /api/bot/verses?ref=John 3:16. Bible notes, highlights, and favorites are those desks. A Bible file import is not on this bot. Notes stay on the account the owner chose.",
        },
        "study_courses": {
            "path": "/api/bot/courses",
            "desks": [
                "curriculum_series", "curriculum_lessons", "curriculum_blocks",
                "curriculum_choices", "curriculum_enrollments", "curriculum_progress",
            ],
            "about": "GET /api/bot/courses lists them. GET /api/bot/courses/<id> opens lessons, blocks, and who is enrolled. POST /api/bot/upload place=course lesson_id puts a picture on a lesson.",
        },
        "members": {
            "desks": ["users", "member_roles", "groups", "user_groups", "user_permissions", "campuses", "campus_members"],
            "about": "GET /api/bot/read/members is the directory when that switch is on. The users desk is the full safe row. This bot cannot create a login, because a new login needs a password. Roles and campus membership are their own desks.",
        },
        "donations": {
            "desks": ["donations", "donation_recurring", "online_donation_options"],
            "about": "POST /api/bot/donations records a gift. The donations desk can update safe columns. Card numbers are refused. Reverse does not void a gift. A giving-option picture is POST /api/bot/upload place=giving with option_id.",
        },
        "bills": {
            "desks": ["recurring_bills", "bill_payment_history", "recurring_bill_assignments"],
            "about": "POST /api/bot/bills/<id> changes amount, status, due date, or notes. Status is pending, paid, overdue, or partial. Account numbers, site logins, and bank details are refused. Payment history is bill_payment_history.",
        },
        "accounting": {
            "desks": ["acct_accounts", "acct_vendors", "acct_journal_entries", "acct_journal_lines", "acct_expenses", "acct_budgets", "acct_budget_lines"],
            "about": "GET /api/bot/accounting lists accounts, recent expenses, and budgets. POST /api/bot/accounting/expenses records an expense. No payroll, bank details, or tax ids. Reverse does not void an expense.",
        },
        "inventory": {
            "desks": ["categories", "vendors", "locations", "items", "inventory_batches", "inventory_transactions", "item_kit_components"],
            "about": "GET /api/bot/inventory lists items, locations, and quantity on hand. POST /api/bot/inventory/adjust changes stock. Categories, vendors, batches, and kit parts are their own desks.",
        },
        "attendance": {
            "desks": ["attendance"],
            "about": "POST /api/bot/attendance checks a member in for a service date. This is member attendance, not the child check-in board. Undo puts that check-in back.",
        },
        "child_checkin": {
            "desks": ["child_classrooms", "child_profiles", "child_guardians", "child_checkins"],
            "about": "Rooms, children, guardians, and the live board. Family PINs and pickup codes are not returned and cannot be set.",
        },
        "volunteers": {
            "desks": ["vol_skills", "vol_teams", "vol_roles", "vol_events", "vol_team_members", "vol_assignments", "vol_rotations"],
            "about": "Skills, teams, roles, events, members, assignments, and rotations. GET /api/bot/desk/<area> opens each one. POST updates safe columns. remove=true drops a membership or assignment and reverse puts it back.",
        },
        "communications": {
            "desks": ["comm_campaigns", "comm_campaign_recipients", "comm_workflows", "comm_workflow_steps", "comm_workflow_enrollments", "comm_message_log"],
            "about": "Read only. The bot can see campaigns and workflows. It does not send email or texts.",
        },
        "pastoral": {
            "desks": ["pastoral_sermons", "pastoral_care_requests", "pastoral_care_notes", "service_plans", "illustration_library"],
            "about": "Sermon drafts, care requests, care notes, the service lineup, and the illustration library. Drafts and illustrations use the sermon-builder calls. Care rows are the pastoral desks. Nothing here is hard-deleted.",
        },
        "worship": {
            "desks": ["worship_songs", "worship_setlists", "worship_setlist_songs", "worship_weekly_templates", "worship_member_notes"],
            "about": "GET and POST /api/bot/worship/songs, /api/bot/worship/team, and /api/bot/worship/defaults. Setlists and the songs on them are worship_setlists and worship_setlist_songs. A chord chart is POST /api/bot/upload place=song with song_id. Songs are not deleted.",
        },
        "gathering": {
            "path": "/api/bot/moderation",
            "desks": ["community_posts", "community_post_comments", "content_flags", "moderation_actions"],
            "about": "The gathering monitor is the moderation queue: posts, reports, and the review ledger.",
        },
        "site_moderation": {
            "path": "/api/bot/moderation",
            "desks": ["content_flags", "moderation_actions", "community_posts"],
            "about": "Same queue as the gathering monitor. POST action=hide or restore needs kind and id. action=report needs kind, id, and decision hide, dismiss, or restore. The ledger is not undone by reverse.",
        },
        "mod_reviews": {"path": "/api/bot/moderation", "about": "POST action=review with decision reverse or uphold."},
        "ai_insights": {
            "path": "/api/bot/insights",
            "about": "Lists the reports. POST runs one on the church AI key. The key is not returned.",
        },
        "settings": {
            "desks": ["settings"],
            "about": "The settings row. API keys, mail passwords, and payment secrets are stripped.",
        },
        "church_apps_menu": {
            "path": "/api/bot/modules",
            "about": "Which apps show in the menu. POST sends the keys to turn on or off. Core apps stay on.",
        },
        "modules_and_apps": {
            "path": "/api/bot/modules",
            "desks": ["custom_module_types", "custom_modules", "custom_module_records"],
            "about": "The menu switches are POST /api/bot/modules. Custom church apps, their types, and their records are the custom_module desks. GET /api/bot/desk/custom_modules opens them.",
        },
        "help": {
            "desks": ["help_categories", "help_articles", "user_help_pins"],
            "about": "POST /api/bot/desk/help_articles with id, title, and body_md updates a help page. help_categories is the grouping.",
        },
        "still_closed": [
            "family PINs and child pickup codes",
            "passwords and new logins",
            "card numbers, bank details, and bill site logins",
            "sending email or texts",
            "payroll",
            "private messages",
            "API keys and the bot's own key",
        ],
    }


def _cur():
    return _db().cursor()


def _rows(sql: str, params: tuple | list = ()) -> list[dict]:
    cur = _cur()
    cur.execute(sql, params)
    return list(cur.fetchall() or [])


def _clean_row(row: dict) -> dict:
    return {
        key: _jsonish(value)
        for key, value in (row or {}).items()
        if key and not secret_column(str(key))
    }


def course_list(args) -> dict:
    limit = _limit(args.get("limit"), 40)
    filters = []
    params: list = []
    status = (args.get("status") or "").strip().lower()
    if status:
        if status not in _COURSE_STATUS:
            return _fail("Status is draft, published, or archived.")
        filters.append("s.status=%s")
        params.append(status)
    query = (args.get("q") or "").strip()
    if query:
        from app.utils.bot_sermon_common import _like
        filters.append("(s.title LIKE %s OR s.subtitle LIKE %s)")
        like = _like(query)
        params.extend([like, like])
    where = (" WHERE " + " AND ".join(filters)) if filters else ""
    try:
        rows = _rows(
            f"""
            SELECT s.id, s.title, s.subtitle, s.status, s.visibility, s.audience,
                   s.sort_order, s.estimated_minutes, s.updated_at,
                   (SELECT COUNT(*) FROM curriculum_lessons l WHERE l.series_id=s.id) AS lessons,
                   (SELECT COUNT(*) FROM curriculum_enrollments e WHERE e.series_id=s.id) AS enrolled
            FROM curriculum_series s
            {where}
            ORDER BY s.sort_order, s.title
            LIMIT %s
            """,
            params + [limit],
        )
    except Exception as exc:
        print(f"bot courses: {exc}")
        return _fail("Study courses did not open.", 500)
    return _ok({"courses": [_clean_row(row) for row in rows], "count": len(rows)})


def course_open(series_id: int) -> dict:
    try:
        series_rows = _rows(
            """
            SELECT id, title, subtitle, description, audience, status, visibility,
                   access_levels, tags, estimated_minutes, sort_order, created_by,
                   published_at, created_at, updated_at
            FROM curriculum_series WHERE id=%s
            """,
            (int(series_id),),
        )
    except Exception as exc:
        print(f"bot course: {exc}")
        return _fail("That study course did not open.", 500)
    if not series_rows:
        return _fail("That study course was not found.", 404)
    lessons = _rows(
        """
        SELECT id, series_id, title, summary, status, estimated_minutes, sort_order
        FROM curriculum_lessons WHERE series_id=%s ORDER BY sort_order, id
        """,
        (int(series_id),),
    )
    lesson_ids = [int(row["id"]) for row in lessons]
    blocks = []
    if lesson_ids:
        marks = ",".join(["%s"] * len(lesson_ids))
        blocks = _rows(
            f"""
            SELECT id, lesson_id, block_type, title, body, media_url, media_alt,
                   question_prompt, correct_answers_json, explanation, points,
                   is_required, sort_order
            FROM curriculum_blocks WHERE lesson_id IN ({marks})
            ORDER BY sort_order, id
            """,
            lesson_ids,
        )
    block_ids = [int(row["id"]) for row in blocks]
    choices = []
    if block_ids:
        marks = ",".join(["%s"] * len(block_ids))
        choices = _rows(
            f"""
            SELECT id, block_id, label, is_correct, sort_order
            FROM curriculum_choices WHERE block_id IN ({marks})
            ORDER BY sort_order, id
            """,
            block_ids,
        )
    by_block: dict[int, list] = {}
    for choice in choices:
        by_block.setdefault(int(choice["block_id"]), []).append(_clean_row(choice))
    by_lesson: dict[int, list] = {}
    for block in blocks:
        item = _clean_row(block)
        item["choices"] = by_block.get(int(block["id"]), [])
        by_lesson.setdefault(int(block["lesson_id"]), []).append(item)
    lesson_out = []
    for lesson in lessons:
        item = _clean_row(lesson)
        item["blocks"] = by_lesson.get(int(lesson["id"]), [])
        lesson_out.append(item)
    enrolled = _rows(
        """
        SELECT user_id, status, progress_pct, last_lesson_id, started_at, completed_at
        FROM curriculum_enrollments WHERE series_id=%s ORDER BY started_at
        """,
        (int(series_id),),
    )
    return _ok({
        "course": _clean_row(series_rows[0]),
        "lessons": lesson_out,
        "enrolled": [_clean_row(row) for row in enrolled],
    })


def _clip(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def course_save(actor_id: int, body: dict) -> dict:
    if not isinstance(body, dict):
        return _fail("Send a JSON body.")
    title = _clip(body.get("title"), 255)
    if not title:
        return _fail("A study course needs a title.")
    status = _clip(body.get("status") or "draft", 24).lower()
    if status not in _COURSE_STATUS:
        return _fail("Status is draft, published, or archived.")
    lessons = body.get("lessons") if isinstance(body.get("lessons"), list) else []
    if len(lessons) > 40:
        return _fail("Send at most 40 lessons in one course.")
    try:
        cur = _cur()
        cur.execute(
            """
            INSERT INTO curriculum_series
                (title, subtitle, description, audience, status, visibility, tags,
                 estimated_minutes, sort_order, created_by, published_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s='published' THEN NOW() ELSE NULL END)
            """,
            (
                title,
                _clip(body.get("subtitle"), 500) or None,
                _clip(body.get("description"), 20000) or None,
                _clip(body.get("audience") or "everyone", 40) or "everyone",
                status,
                _clip(body.get("visibility") or "pastoral", 24) or "pastoral",
                _clip(body.get("tags"), 500) or None,
                _minutes(body.get("estimated_minutes")),
                _sort(body.get("sort_order")),
                int(actor_id),
                status,
            ),
        )
        series_id = int(cur.lastrowid)
        lesson_ids = []
        for index, lesson in enumerate(lessons):
            if not isinstance(lesson, dict):
                continue
            lesson_title = _clip(lesson.get("title"), 255)
            if not lesson_title:
                continue
            lesson_status = _clip(lesson.get("status") or "draft", 24).lower()
            if lesson_status not in _COURSE_STATUS:
                lesson_status = "draft"
            cur.execute(
                """
                INSERT INTO curriculum_lessons
                    (series_id, title, summary, status, estimated_minutes, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    series_id,
                    lesson_title,
                    _clip(lesson.get("summary"), 8000) or None,
                    lesson_status,
                    _minutes(lesson.get("estimated_minutes")),
                    _sort(lesson.get("sort_order"), index),
                ),
            )
            lesson_id = int(cur.lastrowid)
            lesson_ids.append(lesson_id)
            _save_blocks(cur, lesson_id, lesson.get("blocks"))
    except Exception as exc:
        print(f"bot course save: {exc}")
        return _fail("That study course did not save.", 500)
    opened = course_open(series_id)
    if not opened.get("ok"):
        return opened
    opened["log"] = {
        "action": "course.create",
        "detail": f"Created study course {series_id}",
        "target_type": "curriculum_series",
        "target_id": series_id,
        "snapshot": {"table": "curriculum_series", "id": series_id, "created": True},
    }
    opened["data"]["lesson_ids"] = lesson_ids
    return opened


def _minutes(value):
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number > 10000:
        return None
    return number


def _sort(value, fallback: int = 0) -> int:
    if value in (None, ""):
        return fallback
    try:
        return max(0, min(int(value), 10000))
    except (TypeError, ValueError):
        return fallback


def _save_blocks(cur, lesson_id: int, blocks) -> None:
    if not isinstance(blocks, list):
        return
    for index, block in enumerate(blocks[:40]):
        if not isinstance(block, dict):
            continue
        block_type = _clip(block.get("block_type") or "text", 32).lower()
        if block_type not in _BLOCK_TYPES:
            block_type = "text"
        cur.execute(
            """
            INSERT INTO curriculum_blocks
                (lesson_id, block_type, title, body, media_url, media_alt,
                 question_prompt, explanation, points, is_required, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                lesson_id,
                block_type,
                _clip(block.get("title"), 255) or None,
                _clip(block.get("body"), 100000) or None,
                _clip(block.get("media_url"), 1000) or None,
                _clip(block.get("media_alt"), 255) or None,
                _clip(block.get("question_prompt"), 4000) or None,
                _clip(block.get("explanation"), 4000) or None,
                _sort(block.get("points"), 1),
                0 if block.get("is_required") in (False, 0, "0", "false") else 1,
                _sort(block.get("sort_order"), index),
            ),
        )
        block_id = int(cur.lastrowid)
        choices = block.get("choices") if isinstance(block.get("choices"), list) else []
        for choice_index, choice in enumerate(choices[:12]):
            if not isinstance(choice, dict):
                continue
            label = _clip(choice.get("label"), 500)
            if not label:
                continue
            cur.execute(
                """
                INSERT INTO curriculum_choices (block_id, label, is_correct, sort_order)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    block_id,
                    label,
                    1 if choice.get("is_correct") in (True, 1, "1", "true") else 0,
                    _sort(choice.get("sort_order"), choice_index),
                ),
            )


def modules_view() -> dict:
    from app.models.module_toggles import CORE_ALWAYS_ON, OPTIONAL_MODULES, get_module_toggles
    try:
        toggles = get_module_toggles()
    except Exception as exc:
        print(f"bot modules: {exc}")
        return _fail("The apps menu did not open.", 500)
    modules = []
    for row in OPTIONAL_MODULES:
        modules.append({
            "key": row["key"],
            "label": row["label"],
            "description": row["description"],
            "category": row["category"],
            "on": bool(toggles.get(row["key"])),
        })
    return _ok({
        "modules": modules,
        "always_on": [{"key": key, "label": label, "on": True} for key, label in CORE_ALWAYS_ON],
        "custom_apps": "GET or POST /api/bot/desk/custom_modules",
    })


def modules_save(body: dict) -> dict:
    from app.models.module_toggles import OPTIONAL_MODULES, get_module_toggles, save_module_toggles
    if not isinstance(body, dict):
        return _fail("Send a JSON body.")
    sent = body.get("modules") if isinstance(body.get("modules"), dict) else {
        key: value for key, value in body.items() if key != "modules"
    }
    known = {row["key"] for row in OPTIONAL_MODULES}
    changes = {key: bool(value) for key, value in sent.items() if key in known}
    if not changes:
        return _fail("Send module keys to turn on or off, such as {\"curriculum\": true}.")
    try:
        current = get_module_toggles()
        current.update(changes)
        saved = save_module_toggles(current)
    except Exception as exc:
        print(f"bot modules save: {exc}")
        return _fail("The apps menu did not save.", 500)
    ignored = [key for key in sent if key not in known]
    return _ok(
        {"modules": saved, "changed": changes, "ignored": ignored},
        {
            "action": "modules.update",
            "detail": "Updated the church apps menu",
            "target_type": "settings",
            "target_id": 1,
        },
    )


def moderation_board(args) -> dict:
    from app.models import flags
    from app.models import moderation as mod
    status = (args.get("status") or "active").strip().lower()
    if status not in ("active", "reversed", "upheld", "all"):
        status = "active"
    flag_status = (args.get("flags") or "open").strip().lower()
    if flag_status not in ("open", "hidden", "dismissed", "restored"):
        flag_status = "open"
    try:
        mod.ensure_tables()
        actions = [_clean_row(row) for row in (mod.list_actions(status=status, limit=40) or [])]
        reports = [_clean_row(row) for row in (flags.list_targets(status=flag_status) or [])]
    except Exception as exc:
        print(f"bot moderation: {exc}")
        return _fail("The moderation queue did not open.", 500)
    return _ok({
        "reviews": actions,
        "reports": reports[:40],
        "status": status,
        "flags": flag_status,
    })


def moderation_act(actor_id: int, actor_role: str | None, body: dict) -> dict:
    if not isinstance(body, dict):
        return _fail("Send a JSON body.")
    action = (body.get("action") or "").strip().lower()
    note = _clip(body.get("note") or body.get("reason") or "", 400)
    try:
        if action == "hide":
            return _mod_hide(actor_id, body, note)
        if action == "restore":
            return _mod_restore(actor_id, body, note)
        if action == "review":
            return _mod_review(actor_id, body, note)
        if action == "report":
            return _mod_report(actor_id, body, note)
        if action == "warn":
            return _mod_warn(actor_id, actor_role, body, note)
        if action == "shadow":
            return _mod_shadow(actor_id, actor_role, body, True)
        if action == "unshadow":
            return _mod_shadow(actor_id, actor_role, body, False)
    except ValueError as exc:
        return _fail(str(exc))
    except Exception as exc:
        print(f"bot moderation act: {exc}")
        return _fail("That moderation action did not finish.", 500)
    return _fail("Action is hide, restore, review, report, warn, shadow, or unshadow.")


def _mod_log(action: str, detail: str, target_id: int | None) -> dict:
    return {
        "action": action,
        "detail": detail[:500],
        "target_type": "moderation",
        "target_id": target_id,
    }


def _number(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _mod_hide(actor_id, body, note) -> dict:
    from app.models import moderation as mod
    kind = (body.get("kind") or "").strip()
    item_id = _number(body.get("id") or body.get("item_id"))
    if not kind or not item_id:
        return _fail("Send kind and id to hide.")
    ok, message = mod.hide_content(kind, item_id, int(actor_id), note or "Hidden from the bot")
    if not ok:
        return _fail(message or "That item was not hidden.")
    return _ok({"message": message, "kind": kind, "id": item_id}, _mod_log("moderation.hide", message, item_id))


def _mod_restore(actor_id, body, note) -> dict:
    from app.models import moderation as mod
    kind = (body.get("kind") or "").strip()
    item_id = _number(body.get("id") or body.get("item_id"))
    if not kind or not item_id:
        return _fail("Send kind and id to restore.")
    ok, message = mod.restore_target(kind, item_id, int(actor_id), note or "Restored")
    if not ok:
        return _fail(message or "That item was not restored.")
    return _ok({"message": message, "kind": kind, "id": item_id}, _mod_log("moderation.restore", message, item_id))


def _mod_review(actor_id, body, note) -> dict:
    from app.models import moderation as mod
    action_id = _number(body.get("action_id") or body.get("id"))
    decision = (body.get("decision") or "").strip().lower()
    if not action_id:
        return _fail("Send action_id for the review.")
    if decision == "reverse":
        message = mod.reverse_action(action_id, int(actor_id), note)
    elif decision == "uphold":
        message = mod.uphold_action(action_id, int(actor_id))
    else:
        return _fail("Decision is reverse or uphold.")
    return _ok(
        {"message": message, "action_id": action_id, "decision": decision},
        _mod_log("moderation.review", message, action_id),
    )


def _mod_report(actor_id, body, note) -> dict:
    from app.models import flags
    kind = (body.get("kind") or "").strip()
    item_id = _number(body.get("id") or body.get("item_id"))
    decision = (body.get("decision") or "").strip().lower()
    if decision not in ("hide", "dismiss", "restore"):
        return _fail("A report decision is hide, dismiss, or restore.")
    if not kind or not item_id:
        return _fail("Send kind and id for the report.")
    ok, message = flags.resolve(
        kind, item_id, decision, int(actor_id),
        table=(body.get("table") or "").strip() or None,
        comment_type=(body.get("comment_type") or "").strip() or None,
        note=note,
    )
    if not ok:
        return _fail(message or "That report was not updated.")
    return _ok({"message": message, "kind": kind, "id": item_id}, _mod_log("moderation.report", message, item_id))


def _target_user(user_id: int, actor_id: int, actor_role: str | None):
    row = _rows(
        "SELECT id, username, role FROM users WHERE id=%s",
        (int(user_id),),
    )
    if not row:
        return None, _fail("That member was not found.", 404)
    person = row[0]
    role = (person.get("role") or "").strip()
    if int(person.get("id") or 0) == int(actor_id):
        return None, _fail("This bot cannot do that to its own account.")
    if role in ("Owner", "Admin") and (actor_role or "") != "Owner":
        return None, _fail("An admin bot cannot do that to an owner or admin account.", 403)
    return person, None


def _mod_warn(actor_id, actor_role, body, note) -> dict:
    from app.models import moderation as mod
    user_id = _number(body.get("user_id"))
    if not user_id or not note:
        return _fail("Send user_id and a short warning note.")
    person, err = _target_user(user_id, actor_id, actor_role)
    if err:
        return err
    mod.warn_user(int(person["id"]), int(actor_id), note)
    message = f"Warning noted for @{person.get('username') or person['id']}."
    return _ok({"message": message, "user_id": int(person["id"])}, _mod_log("moderation.warn", message, int(person["id"])))


def _mod_shadow(actor_id, actor_role, body, shadow: bool) -> dict:
    from app.models.users import set_shadow_ban
    user_id = _number(body.get("user_id"))
    if not user_id:
        return _fail("Send user_id.")
    person, err = _target_user(user_id, actor_id, actor_role)
    if err:
        return err
    set_shadow_ban(int(person["id"]), shadow, int(actor_id))
    message = (
        f"@{person.get('username') or person['id']} is shadowed."
        if shadow else
        f"@{person.get('username') or person['id']} is no longer shadowed."
    )
    return _ok(
        {"message": message, "user_id": int(person["id"]), "shadow": shadow},
        _mod_log("moderation.shadow", message, int(person["id"])),
    )


def insights_view() -> dict:
    from app.routes.ai_insights.views import REPORTS
    try:
        from app.utils.ai_client import ai_status
        status = ai_status()
    except Exception as exc:
        print(f"bot insights status: {exc}")
        status = {"configured": False}
    safe_status = {
        "configured": bool(status.get("configured")),
        "default_provider": status.get("default_provider"),
        "default_model": status.get("default_model"),
    }
    reports = [
        {"id": row["id"], "title": row["title"], "about": row["desc"]}
        for row in REPORTS
    ]
    return _ok({"reports": reports, "ai": safe_status})


def insights_run(actor_id: int, body: dict) -> dict:
    if not isinstance(body, dict):
        return _fail("Send a JSON body.")
    from app.routes.ai_insights.data import dataset_for, prompt_for
    from app.routes.ai_insights.views import REPORTS
    from app.utils.ai_client import run_insight
    report_type = (body.get("report") or body.get("report_type") or "").strip().lower()
    known = {row["id"] for row in REPORTS}
    if report_type not in known:
        return _fail("Report is overview, donations, attendance, security, or tickets.")
    question = _clip(body.get("question") or "", 500)
    try:
        dataset = dataset_for(report_type, ip_detail="prefix")
        system, prompt = prompt_for(report_type, dataset, question)
        text, err, meta = run_insight(f"insights_{report_type}", system, prompt)
    except Exception as exc:
        print(f"bot insights: {exc}")
        return _fail("That insight did not run.", 500)
    if not text:
        return _fail(err or "That insight did not run.")
    return _ok(
        {
            "report": report_type,
            "text": text,
            "provider": (meta or {}).get("provider"),
            "model": (meta or {}).get("model"),
        },
        {
            "action": "insights.run",
            "detail": f"AI insight {report_type}",
            "target_type": "ai_insights",
            "target_id": int(actor_id),
        },
    )
