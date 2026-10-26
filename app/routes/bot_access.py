"""Owner Bot Access dashboard and the /api/bot session.

The owner names a bot, gives it two inboxes, and turns each switch on or off.
The API key is emailed and does not expire. The 2FA key is emailed to the
other inbox and expires. A bot can hold several sessions. Work calls use
one of those sessions. Reset accepts the API key or a live session, and
the previous key keeps working for 15 minutes.
"""

from flask import Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, session, url_for

from app.models.users import get_user_by_id
from app.utils import bot_areas as areas
from app.utils import bot_comments as comments
from app.utils import bot_content as content
from app.utils import bot_desks as desks
from app.utils import bot_events as events_api
from app.utils import bot_guard as guard
from app.utils import bot_login as login
from app.utils import bot_members as members_api
from app.utils import bot_office as office
from app.utils import bot_policy as policy
from app.utils import bot_sermons as sermons
from app.utils import bot_store as store
from app.utils.decorators import login_required

bot_access_bp = Blueprint("bot_access", __name__)


def _json(ok: bool, data=None, error: str | None = None, status: int = 200, code: str | None = None,
          missing=None, surface: dict | None = None):
    body = {"ok": ok, "greeting": policy.GREETING}
    if error:
        body["error"] = error
    if code:
        body["code"] = code
    elif error == policy.ADMIN_NOT_GRANTED:
        body["code"] = "admin_not_granted"
    elif error == "The owner turned this key off.":
        body["code"] = "key_off"
    if missing:
        body["missing"] = list(missing)
    if data is not None:
        body["data"] = data
    if surface:
        for key, val in surface.items():
            if key not in ("ok", "greeting", "data"):
                body[key] = val
    return jsonify(body), status


def _bearer() -> str:
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return (request.headers.get("X-Bot-Key") or "").strip()


def _owner_user():
    uid = session.get("user_id")
    if not uid:
        return None
    user = get_user_by_id(uid)
    if not user or (user.get("role") or "") != "Owner":
        return None
    return user


def _require_session():
    """A live session. This does not apply the admin-grant stop or the master switch."""
    raw = _bearer()
    if not raw:
        return None, _json(
            False,
            error=(
                "Send the session as Authorization: Bearer mvos_s_…. "
                "POST /api/bot/login with the API key, then POST /api/bot/login/exchange with X-Bot-2FA."
            ),
            status=401,
            code="session_unknown",
        )
    kind = store.bearer_kind(raw)
    if kind == "live_session":
        row = store.find_session(raw)
        if not row:
            return None, _json(False, error="That session is not open. Sign in again.", status=401, code="session_unknown")
        if not row.get("active"):
            return None, _json(False, error="The owner turned this key off.", status=403, code="key_off")
        return row, None
    if kind == "expired_session":
        return None, _json(False, error="That session expired. Sign in again.", status=401, code="session_expired")
    if kind == "key_off":
        return None, _json(False, error="The owner turned this key off.", status=403, code="key_off")
    if kind in ("live_key", "grace_key"):
        return None, _json(
            False,
            error=(
                "That is the API key. It does not open the work calls. "
                "POST /api/bot/login, then exchange the 2FA key."
            ),
            status=401,
        )
    if raw.startswith("mvos_2fa_"):
        return None, _json(
            False,
            error=(
                "That is the 2FA key. Send it as X-Bot-2FA to POST /api/bot/login/exchange, "
                "with the API key as Authorization: Bearer."
            ),
            status=401,
        )
    if raw.startswith("mvos_s_"):
        return None, _json(False, error="That session is not open. Sign in again.", status=401, code="session_unknown")
    return None, _json(False, error="That API key is not recognized.", status=401, code="key_unknown")


def _require_key():
    """Work calls take a live session, not the permanent API key."""
    row, err = _require_session()
    if err:
        return None, err
    blocked = _acting_block(row)
    if blocked:
        return None, blocked
    if request.method != "GET" and policy.writes_blocked(row.get("controls")):
        return None, _json(
            False,
            error="The owner turned bot writes off.",
            status=423,
            code="bot_writes_off",
            missing=["bot_writes_off"],
        )
    return row, None


def _require_reset():
    """A live session or the current API key, including the 15-minute previous key."""
    raw = _bearer()
    if not raw:
        return None, _json(
            False,
            error="Send the API key or a live session as Authorization: Bearer.",
            status=401,
            code="key_unknown",
        )
    kind = store.bearer_kind(raw)
    if kind == "live_session":
        row = store.find_session(raw)
    elif kind in ("live_key", "grace_key"):
        row = store.find_key(raw)
    elif kind == "expired_session":
        return None, _json(
            False,
            error="That session expired. Sign in again, or send the API key.",
            status=401,
            code="session_expired",
        )
    elif kind == "key_off":
        return None, _json(False, error="The owner turned this key off.", status=403, code="key_off")
    elif raw.startswith("mvos_s_"):
        return None, _json(False, error="That session is not open. Sign in again.", status=401, code="session_unknown")
    else:
        return None, _json(False, error="That API key is not recognized.", status=401, code="key_unknown")
    if not row or not row.get("active"):
        code = "key_off" if row and not row.get("active") else "key_unknown"
        error = "The owner turned this key off." if code == "key_off" else "That API key is not recognized."
        status = 403 if code == "key_off" else 401
        return None, _json(False, error=error, status=status, code=code)
    return row, None


def _acting_name(row: dict, facts: dict) -> str:
    uid = facts.get("user_id")
    for voice in row.get("voices") or []:
        try:
            if int(voice.get("user_id") or 0) == int(uid or 0):
                return policy.person_label(voice)
        except (TypeError, ValueError):
            continue
    return "this admin"


def _block_info(row: dict) -> dict | None:
    """An admin uses a bot only after the owner allows that admin."""
    people = policy.assigned_people(row.get("voices") or [])
    if len(people) != 1:
        return None
    facts = store.account_facts(people[0])
    row["acting"] = facts
    if facts.get("role") == "Admin" and not facts.get("admin_granted"):
        uid = facts.get("user_id")
        name = _acting_name(row, facts)
        return {
            "code": "admin_not_granted",
            "error": policy.ADMIN_NOT_GRANTED,
            "missing": [f"admin_grant:{uid}"],
            "fix": f"Owner: Settings → Bot Access → tick 'Allow bot' for {name}",
        }
    return None


def _acting_block(row: dict):
    info = _block_info(row)
    if not info:
        return None
    return _json(
        False,
        error=info["error"],
        status=403,
        code=info["code"],
        missing=info["missing"],
        surface={"fix": info["fix"]},
    )


def _need(row: dict, switch_id: str):
    if policy.switch_on(row.get("controls"), switch_id):
        return None
    label = (policy.switch_by_id(switch_id) or {}).get("label") or switch_id
    store.write_log(int(row["id"]), "denied", ok=False, detail=f"{switch_id} is off", target_type="switch")
    return _json(
        False,
        error=f"The owner has {label} turned off for this key.",
        status=403,
        code="switch_off",
        missing=[switch_id],
    )


def _need_any(row: dict, *switch_ids: str):
    for switch_id in switch_ids:
        if policy.switch_on(row.get("controls"), switch_id):
            return None
    return _need(row, switch_ids[0])


def _payload():
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if isinstance(data, dict):
            return data
    return request.form


def _security_payload() -> dict:
    summary = {}
    events = []
    total = 0
    newest = None
    recording = False
    try:
        from app.routes.security.queries import list_security_events, summary_stats
        summary = summary_stats() or {}
        events, total = list_security_events(limit=30)
        recording = True
    except Exception as exc:
        print(f"bot security: {exc}")
        events, total = [], 0
    clean = []
    for row in events or []:
        item = {}
        for key, val in (row or {}).items():
            item[key] = store._cell(val)
        if item.get("timestamp") and not newest:
            newest = item["timestamp"]
        clean.append(item)
    for key, val in list(summary.items()):
        summary[key] = store._cell(val)
    return {
        "summary": summary,
        "events": clean,
        "events_total": total,
        "events_newest_at": newest,
        "recording": recording,
    }


def _apply_reverse(entry: dict, actor: str) -> tuple[bool, str]:
    plan = policy.undo_plan(entry.get("action") or "", bool(entry.get("reversed")))
    if plan is None or not entry.get("ok"):
        return False, "That entry cannot be reversed."
    action = entry.get("action") or ""
    if action == "post.create":
        post_id = entry.get("target_id") or (entry.get("snapshot") or {}).get("post_id")
        if not post_id:
            return False, "That entry has no post to hide or restore."
        ok, message = store.set_post_removed(int(post_id), plan == "hide")
    elif action.startswith("bot_member"):
        ok, message = members_api.apply_undo(plan, entry)
    elif action.startswith("bot_event"):
        ok, message = events_api.apply_undo(plan, entry)
    elif action.startswith("bot_"):
        ok, message = content.apply_undo(plan, entry)
    elif action.startswith("desk."):
        ok, message = desks.apply_undo(plan, entry)
    elif (action.split(".", 1)[0] if action else "") in {"group", "worship", "bill", "inventory", "attendance"}:
        ok, message = office.apply_undo(plan, entry)
    else:
        ok, message = sermons.apply_undo(plan, entry)
    if not ok:
        return False, message
    store.mark_reversed(int(entry["id"]), actor, clear=plan in ("show", "reapply"))
    return True, message


def _token():
    token = request.args.get("as")
    if request.method != "GET":
        body = _payload()
        if isinstance(body, dict) and body.get("as") not in (None, ""):
            token = body.get("as")
    return token


def _facts(row: dict) -> dict:
    cached = row.get("acting")
    if isinstance(cached, dict) and cached.get("user_id"):
        return cached
    people = policy.assigned_people(row.get("voices") or [])
    if len(people) != 1:
        return {"user_id": None, "role": None, "admin_granted": False}
    return store.account_facts(people[0])


def _sermon_person(row: dict):
    """The one account the owner chose. The caller cannot name a different one."""
    facts = _facts(row)
    person, err = policy.resolve_sermon_user(
        _token(),
        row.get("voices") or [],
        row.get("created_by"),
        role=facts.get("role"),
        admin_granted=bool(facts.get("admin_granted")),
    )
    if err:
        return None, _json(False, error=err, status=400)
    return person, None


def _office_desk():
    row, err = _require_key()
    if err:
        return None, None, err
    denied = _need(row, "office")
    if denied:
        return None, None, denied
    person, missing = _sermon_person(row)
    if missing:
        return None, None, missing
    facts = _facts(row)
    role_err = policy.office_blocked(facts.get("role"), bool(facts.get("admin_granted")))
    if role_err:
        return None, None, _json(False, error=role_err, status=403)
    return row, person, None


def _desk():
    row, err = _require_key()
    if err:
        return None, None, err
    denied = _need(row, "sermon_builder")
    if denied:
        return None, None, denied
    person, missing = _sermon_person(row)
    if missing:
        return None, None, missing
    return row, person, None


def _finish_person(row: dict, result: dict, person: dict):
    if result.get("ok") and person:
        data = result.setdefault("data", {})
        data["as"] = person["as"]
        data["user_id"] = person["user_id"]
    return _finish(row, result)


def _actor_id(row: dict) -> int | None:
    try:
        uid = int(row.get("created_by") or 0)
    except (TypeError, ValueError):
        uid = 0
    return uid or None


def _finish(row: dict, result: dict):
    if not result.get("ok"):
        if result.get("status") == 500 and result.get("action"):
            store.write_log(
                int(row["id"]),
                result.get("action") or "sermon",
                ok=False,
                detail=result.get("error") or "",
            )
        return _json(
            False,
            error=result.get("error") or "That did not work.",
            status=result.get("status") or 400,
            code=result.get("code"),
            missing=result.get("missing"),
        )
    data = dict(result.get("data") or {})
    log = result.get("log")
    if log:
        log_id = store.write_log(
            int(row["id"]),
            log.get("action") or "sermon",
            ok=True,
            detail=log.get("detail") or "",
            target_type=log.get("target_type"),
            target_id=log.get("target_id"),
            snapshot=log.get("snapshot"),
        )
        data["log_id"] = log_id
        if policy.undo_plan(log.get("action") or "", False):
            data["undo"] = "POST /api/bot/reverse with this log_id."
    return _json(True, data)


def _needs_owner(row: dict, what: str):
    actor = _actor_id(row)
    if actor:
        return actor, None
    return None, _json(False, error=f"This key has no owner on it, so it cannot {what}.", status=400)


@bot_access_bp.route("/settings/bot-access", methods=["GET", "POST"])
@login_required
def page():
    owner = _owner_user()
    if not owner:
        abort(403)
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        dest = "bot_access.usage" if (request.form.get("next") or "") == "usage" else "bot_access.page"
        if action == "create":
            ok, message = login.create_bot(
                request.form.get("name") or "",
                request.form.get("email") or "",
                request.form.get("twofa_email") or "",
                owner.get("id"),
            )
            flash(message, "success" if ok else "error")
        elif action == "reset":
            try:
                key_id = int(request.form.get("key_id") or 0)
            except (TypeError, ValueError):
                key_id = 0
            ok, message = login.reset_bot(key_id)
            flash(message, "success" if ok else "error")
        elif action == "grants":
            member_rows = {int(row["id"]): row for row in store.list_members()}
            chosen = []
            for value in request.form.getlist("admin_grant"):
                try:
                    uid = int(value)
                except (TypeError, ValueError):
                    continue
                member = member_rows.get(uid)
                if member and member.get("role") == "Admin" and uid not in chosen:
                    chosen.append(uid)
            ok, note = store.save_admin_grants(chosen, owner.get("id"))
            flash(note or "Admin bot access saved.", "success" if ok else "error")
        elif action == "save":
            member_rows = {int(row["id"]): row for row in store.list_members()}
            try:
                key_id = int(request.form.get("key_id") or 0)
            except (TypeError, ValueError):
                key_id = 0
            controls = {
                row["id"]: request.form.get(f"switch_{row['id']}") == "1"
                for row in policy.SWITCHES
            }
            saved_inboxes, inbox_note = store.set_inboxes(
                key_id,
                request.form.get("email") or "",
                request.form.get("twofa_email") or "",
            )
            if not saved_inboxes:
                flash(inbox_note or "Those inboxes could not be saved.", "error")
                return redirect(url_for("bot_access.page"))
            try:
                picked_act = int(request.form.get("act_as") or 0)
            except (TypeError, ValueError):
                picked_act = 0
            act_as = picked_act if picked_act in member_rows else None
            act_role = (member_rows.get(act_as) or {}).get("role") if act_as else None
            granted = act_role != "Admin" or act_as in store.admin_grant_ids()
            church_author = None
            try:
                picked = int(request.form.get("church_author") or 0)
            except (TypeError, ValueError):
                picked = 0
            if picked in member_rows:
                church_author = picked
            ok, note = store.save_key(
                key_id,
                request.form.get("active") == "1",
                controls,
                church_author,
                act_as,
                request.form.get("voice_church") == "1",
                act_role=act_role,
                admin_granted=granted,
            )
            if not ok:
                flash(note or "Could not save that bot.", "error")
            else:
                flash(note or "Bot access saved.", "success" if not note else "error")
        elif action == "reverse":
            try:
                log_id = int(request.form.get("log_id") or 0)
            except (TypeError, ValueError):
                log_id = 0
            entry = store.get_log(log_id) if log_id else None
            if not entry:
                flash("That log entry is gone.", "error")
            else:
                ok, message = _apply_reverse(entry, f"owner:{owner.get('id')}")
                flash(message, "success" if ok else "error")
        return redirect(url_for(dest))
    store.ensure_login_columns()
    store.ensure_admin_grants()
    members = store.list_members()
    return render_template(
        "settings/bot_access.html",
        keys=store.list_keys(),
        members=members,
        admins=[row for row in members if row.get("role") == "Admin"],
        grants=store.admin_grant_ids(),
        groups=policy.switch_groups(),
        closed=policy.CLOSED,
    )


@bot_access_bp.route("/settings/bot-access/usage", methods=["GET"])
@login_required
def usage():
    owner = _owner_user()
    if not owner:
        abort(403)
    store.ensure_login_columns()
    return render_template("settings/bot_usage.html", entries=store.list_usage(120))


def _from_login(result):
    data, error, status = result[0], result[1], result[2]
    code = result[3] if len(result) > 3 else None
    if error:
        return _json(False, error=error, status=status, code=code)
    return _json(True, data)


@bot_access_bp.route("/api/bot/login", methods=["POST"])
def api_login():
    return _from_login(login.present(_bearer()))


@bot_access_bp.route("/api/bot/login/exchange", methods=["POST"])
def api_exchange():
    twofa = (request.headers.get("X-Bot-2FA") or "").strip()
    if not twofa:
        twofa = str(_payload().get("twofa_key") or "").strip()
    label = str(_payload().get("client") or "")
    return _from_login(login.exchange(_bearer(), twofa, label))


@bot_access_bp.route("/api/bot/key/reset", methods=["POST"])
@bot_access_bp.route("/api/bot/password-reset", methods=["POST"])
def api_password_reset():
    row, err = _require_reset()
    if err:
        return err
    if store.recent_reset_count(int(row["id"])) >= policy.RESET_LIMIT_PER_HOUR:
        return _json(
            False,
            error="This key already reset itself 3 times this hour. Try again later.",
            status=429,
        )
    ok, message = login.reset_bot(int(row["id"]))
    if not ok:
        return _json(False, error=message, status=502)
    store.write_log(
        int(row["id"]),
        "key_reset",
        ok=True,
        detail="A new API key was emailed to the main inbox.",
    )
    return _json(True, {
        "step": "reset",
        "sent": True,
        "twofa_sent": False,
        "message": message,
    })


@bot_access_bp.route("/api/bot/key/reset-request", methods=["POST"])
def api_key_reset_request():
    """Always the same reply. A matching inbox is mailed. A miss sends nothing."""
    try:
        email = str(_payload().get("email") or "")
    except Exception:
        email = ""
    try:
        login.reset_by_inbox(email)
    except Exception as exc:
        print(f"bot reset-request: {type(exc).__name__}")
    return _json(True, {"step": "reset-request", "message": policy.RESET_REQUEST_REPLY})


def _status_surface(row: dict, block: dict | None) -> dict:
    facts = row.get("acting") if isinstance(row.get("acting"), dict) else _facts(row)
    name = _acting_name(row, facts) if facts.get("user_id") else ""
    surface = {
        "blocked": bool(block),
        "acting_user": {
            "id": facts.get("user_id"),
            "name": name,
            "role": facts.get("role"),
        },
        "missing": list(block.get("missing") or []) if block else [],
        "fix": (block or {}).get("fix") or "",
        "switches": row.get("controls") or policy.default_controls(),
        "expired_switches": [],
        "writes_off": policy.writes_blocked(row.get("controls")),
    }
    if block:
        surface["code"] = block.get("code")
    return surface


@bot_access_bp.route("/api/bot/help", methods=["GET"])
@bot_access_bp.route("/api/bot/helper", methods=["GET"])
def api_help():
    row, err = _require_session()
    if err:
        return err
    block = _block_info(row)
    why = "admin_grant" if block else None
    payload = policy.help_payload(row.get("controls"), row.get("voices"), blocked_why=why)
    surface = {"blocked": bool(block), "missing": list((block or {}).get("missing") or []), "writes_off": policy.writes_blocked(row.get("controls"))}
    if block:
        surface["code"] = block.get("code")
        surface["fix"] = block.get("fix")
    return _json(True, payload, surface=surface)


@bot_access_bp.route("/api/bot/whoami", methods=["GET"])
@bot_access_bp.route("/api/bot/me", methods=["GET"])
def api_whoami():
    row, err = _require_session()
    if err:
        return err
    block = _block_info(row)
    facts = _facts(row)
    people = policy.assigned_people(row.get("voices") or [])
    actor, actor_err = policy.resolve_sermon_user(
        None,
        row.get("voices") or [],
        row.get("created_by"),
        role=facts.get("role"),
        admin_granted=bool(facts.get("admin_granted")),
    )
    data = {
        "name": row.get("name"),
        "prefix": row.get("key_prefix"),
        "active": True,
        "switches": row.get("controls") or policy.default_controls(),
        "voices": policy.help_payload(row.get("controls"), row.get("voices"))["voices"],
        "acts_as": actor,
        "acts_as_error": actor_err,
        "sermon_user": actor,
        "sermon_people": [f"user:{people[0]}"] if len(people) == 1 else [],
        "help": "GET /api/bot/help",
        "blocked": bool(block),
        "writes_off": policy.writes_blocked(row.get("controls")),
        "expired_switches": [],
        "missing": list((block or {}).get("missing") or []),
        "fix": (block or {}).get("fix") or "",
    }
    return _json(True, data, surface=_status_surface(row, block))


@bot_access_bp.route("/api/bot/diagnostics", methods=["GET"])
def api_diagnostics():
    row, err = _require_session()
    if err:
        return err
    block = _block_info(row)
    facts = _facts(row)
    people = policy.assigned_people(row.get("voices") or [])
    data = {
        "name": row.get("name"),
        "key_prefix": row.get("key_prefix"),
        "prefix": row.get("key_prefix"),
        "active": True,
        "switches": row.get("controls") or policy.default_controls(),
        "blocked": bool(block),
        "missing": list((block or {}).get("missing") or []),
        "fix": (block or {}).get("fix") or "",
        "writes_off": policy.writes_blocked(row.get("controls")),
        "expired_switches": [],
        "acting_user": {
            "id": facts.get("user_id"),
            "name": _acting_name(row, facts) if facts.get("user_id") else "",
            "role": facts.get("role"),
        },
        "sermon_people": [f"user:{people[0]}"] if len(people) == 1 else [],
        "session_expires_in": store.session_seconds_left(row.get("session_row_id")),
        "pending_2fa": store.pending_twofa_count(int(row["id"])),
        "reset_count_hour": store.recent_reset_count(int(row["id"])),
        "grace_key_active": store.grace_key_active(int(row["id"])),
    }
    return _json(True, data, surface=_status_surface(row, block))


@bot_access_bp.route("/api/bot/log", methods=["GET"])
def api_log():
    row, err = _require_key()
    if err:
        return err
    rows = store.list_log(int(row["id"]))
    return _json(True, {"entries": rows, "count": len(rows)})


@bot_access_bp.route("/api/bot/reverse", methods=["POST"])
def api_reverse():
    row, err = _require_key()
    if err:
        return err
    payload = _payload()
    try:
        log_id = int(payload.get("log_id") or 0)
    except (TypeError, ValueError):
        log_id = 0
    entry = store.get_log(log_id) if log_id else None
    if not entry or int(entry.get("key_id") or 0) != int(row["id"]):
        return _json(False, error="That log entry is not on this key.", status=404)
    step = policy.undo_plan(entry.get("action") or "", bool(entry.get("reversed")))
    ok, message = _apply_reverse(entry, f"key:{row['id']}")
    if not ok:
        return _json(False, error=message, status=400)
    words = {"hide": "hidden", "show": "restored", "restore": "restored", "reapply": "redone"}
    return _json(True, {"log_id": log_id, "result": words.get(step, step), "message": message})


@bot_access_bp.route("/api/bot/posts", methods=["GET", "POST"])
def api_posts():
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "posts")
    if denied:
        return denied
    payload = _payload()
    token = payload.get("as") or request.args.get("as") or ""
    facts = _facts(row)
    voice, voice_err = policy.resolve_bot_post(
        token,
        row.get("voices") or [],
        role=facts.get("role"),
        admin_granted=bool(facts.get("admin_granted")),
    )
    if voice_err:
        return _json(False, error=voice_err, status=403)
    if request.method == "GET":
        posts = store.list_voice_posts(voice)
        return _json(True, {"as": voice["as"], "posts": posts, "count": len(posts)})
    post, post_err = policy.validate_post(
        payload.get("kind") or "post",
        payload.get("title") or "",
        payload.get("body") or "",
        payload.get("visibility") or "public",
    )
    if post_err:
        return _json(False, error=post_err, status=400)
    post_id, save_err = store.publish_post(voice, post)
    if not post_id:
        store.write_log(
            int(row["id"]), "post.create", ok=False, detail=save_err or "Could not save that post.",
            target_type="community_post",
        )
        return _json(False, error=save_err or "Could not save that post.", status=400)
    snapshot = {
        "post_id": post_id,
        "as": voice["as"],
        "posted_as": voice["posted_as"],
        "author_user_id": voice["user_id"],
        "kind": post["kind"],
        "title": post["title"],
        "body": post["body"],
        "visibility": post["visibility"],
    }
    log_id = store.write_log(
        int(row["id"]),
        "post.create",
        ok=True,
        detail=f"{post['kind']} as {voice['as']}: {post['title']}",
        target_type="community_post",
        target_id=post_id,
        snapshot=snapshot,
    )
    data = {
        "post_id": post_id,
        "log_id": log_id,
        "as": voice["as"],
        "kind": post["kind"],
        "title": post["title"],
        "author_user_id": voice["user_id"],
        "undo": "POST /api/bot/reverse with this log_id hides the post. The row is kept.",
    }
    if save_err:
        data["note"] = save_err
    return _json(True, data)


@bot_access_bp.route("/api/bot/security", methods=["GET"])
def api_security():
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "security")
    if denied:
        return denied
    return _json(True, _security_payload())


@bot_access_bp.route("/api/bot/read/<area>", methods=["GET"])
def api_read(area: str):
    row, err = _require_key()
    if err:
        return err
    if area not in policy.READS:
        return _json(False, error="That read is not on the bot. GET /api/bot/help lists the ones that are.", status=404)
    denied = _need(row, area)
    if denied:
        return denied
    try:
        limit = int(request.args.get("limit") or store.READ_LIMIT)
    except (TypeError, ValueError):
        limit = store.READ_LIMIT
    rows, recording, note = store.read_area(area, limit)
    data = {"area": area, "rows": rows, "count": len(rows), "recording": recording}
    if note:
        data["note"] = note
    return _json(True, data)


@bot_access_bp.route("/api/bot/sermons", methods=["GET", "POST"])
def api_sermons():
    row, person, err = _desk()
    if err:
        return err
    if request.method == "GET":
        if request.args.get("id"):
            try:
                sermon_id = int(request.args.get("id"))
            except (TypeError, ValueError):
                return _json(False, error="Sermon id must be a number.", status=400)
            return _finish_person(row, sermons.sermon_detail(sermon_id, person["user_id"]), person)
        return _finish_person(
            row,
            sermons.list_builder_sermons(request.args.get("q") or "", request.args.get("limit"), person["user_id"]),
            person,
        )
    return _finish_person(row, sermons.create_builder_sermon(person["user_id"], _payload()), person)


@bot_access_bp.route("/api/bot/sermons/<int:sermon_id>", methods=["GET", "POST"])
def api_sermon(sermon_id: int):
    row, person, err = _desk()
    if err:
        return err
    if request.method == "GET":
        return _finish_person(row, sermons.sermon_detail(sermon_id, person["user_id"]), person)
    return _finish_person(row, sermons.update_builder_sermon(sermon_id, _payload(), person["user_id"]), person)


@bot_access_bp.route("/api/bot/sermons/<int:sermon_id>/sections", methods=["POST"])
def api_sermon_sections(sermon_id: int):
    row, person, err = _desk()
    if err:
        return err
    return _finish_person(row, sermons.save_section(sermon_id, _payload(), person["user_id"]), person)


@bot_access_bp.route("/api/bot/sermons/<int:sermon_id>/sections/hide", methods=["POST"])
def api_sermon_section_hide(sermon_id: int):
    row, person, err = _desk()
    if err:
        return err
    return _finish_person(row, sermons.hide_section(sermon_id, _payload(), person["user_id"]), person)


@bot_access_bp.route("/api/bot/sermons/<int:sermon_id>/sections/reorder", methods=["POST"])
def api_sermon_section_reorder(sermon_id: int):
    row, person, err = _desk()
    if err:
        return err
    return _finish_person(row, sermons.reorder_sections(sermon_id, _payload(), person["user_id"]), person)


@bot_access_bp.route("/api/bot/sermons/<int:sermon_id>/hide", methods=["POST"])
def api_sermon_hide(sermon_id: int):
    row, person, err = _desk()
    if err:
        return err
    return _finish_person(row, sermons.hide_builder_sermon(sermon_id, person["user_id"]), person)


@bot_access_bp.route("/api/bot/illustrations", methods=["GET", "POST"])
def api_illustrations():
    row, person, err = _desk()
    if err:
        return err
    if request.method == "GET":
        return _finish_person(row, sermons.list_illustrations(
            request.args.get("q") or "", request.args.get("limit"), request.args.get("id"), person["user_id"],
        ), person)
    return _finish_person(row, sermons.create_illustration_item(person["user_id"], _payload()), person)


@bot_access_bp.route("/api/bot/illustrations/<int:illus_id>", methods=["POST"])
def api_illustration(illus_id: int):
    row, person, err = _desk()
    if err:
        return err
    return _finish_person(row, sermons.update_illustration_item(person["user_id"], illus_id, _payload()), person)


def _log_download(row: dict, illus_id: int, detail: str):
    store.write_log(
        int(row["id"]),
        "illustration.download",
        ok=True,
        detail=detail,
        target_type="illustration",
        target_id=int(illus_id),
        snapshot={"illustration_id": int(illus_id)},
    )


@bot_access_bp.route("/api/bot/illustrations/<int:illus_id>/hide", methods=["POST"])
def api_illustration_hide(illus_id: int):
    row, person, err = _desk()
    if err:
        return err
    return _finish_person(row, sermons.hide_illustration(person["user_id"], illus_id), person)


@bot_access_bp.route("/api/bot/illustrations/<int:illus_id>/download", methods=["GET"])
def api_illustration_download(illus_id: int):
    row, person, err = _desk()
    if err:
        return err
    as_file = (request.args.get("file") or "") in ("1", "true", "yes")
    result = sermons.download_illustration(
        person["user_id"], illus_id, request.args.get("format") or "md", as_file,
    )
    if not result.get("ok"):
        return _finish_person(row, result, person)
    _log_download(row, illus_id, result.get("download_detail") or "illustration")
    payload = result.get("download")
    if payload:
        data = payload["bytes"]
        return Response(
            data,
            mimetype=payload["mimetype"],
            headers={
                "Content-Type": payload["mimetype"],
                "Content-Disposition": payload["disposition"],
                "Content-Length": str(len(data)),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )
    return _finish_person(row, result, person)


@bot_access_bp.route("/api/bot/comments", methods=["GET"])
def api_comments():
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "comments")
    if denied:
        return denied
    return _finish(row, comments.list_comments(
        request.args.get("area") or "",
        request.args.get("parent") or request.args.get("parent_id"),
        request.args.get("q") or "",
        request.args.get("status") or "visible",
        request.args.get("limit"),
    ))


@bot_access_bp.route("/api/bot/comments/<area>/<int:comment_id>", methods=["GET"])
def api_comment(area: str, comment_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "comments")
    if denied:
        return denied
    return _finish(row, comments.comment_detail(area, comment_id))


@bot_access_bp.route("/api/bot/vault", methods=["GET", "POST"])
def api_vault():
    row, person, err = _desk()
    if err:
        return err
    if request.method == "GET":
        return _finish_person(row, sermons.list_vault(
            person["user_id"], request.args.get("q") or "", request.args.get("limit"), request.args.get("id"),
        ), person)
    return _finish_person(row, sermons.create_vault_item(person["user_id"], _payload()), person)


@bot_access_bp.route("/api/bot/vault/<int:item_id>", methods=["POST"])
def api_vault_item(item_id: int):
    row, person, err = _desk()
    if err:
        return err
    return _finish_person(row, sermons.update_vault_item(person["user_id"], item_id, _payload()), person)


@bot_access_bp.route("/api/bot/verses", methods=["GET"])
def api_verses():
    row, person, err = _desk()
    if err:
        return err
    ref = request.args.get("ref") or request.args.get("reference") or ""
    return _finish_person(row, sermons.lookup_reference(ref, request.args.get("translation")), person)


@bot_access_bp.route("/api/bot/lineup", methods=["GET", "POST"])
def api_lineup():
    row, person, err = _desk()
    if err:
        return err
    if request.method == "GET":
        return _finish_person(row, sermons.lineup_for(request.args.get("days")), person)
    return _finish_person(row, sermons.set_lineup(person["user_id"], _payload()), person)


@bot_access_bp.route("/api/bot/groups", methods=["GET"])
def api_groups():
    row, person, err = _office_desk()
    if err:
        return err
    return _finish_person(row, office.list_groups(), person)


@bot_access_bp.route("/api/bot/groups/<int:group_id>", methods=["GET"])
def api_group(group_id: int):
    row, person, err = _office_desk()
    if err:
        return err
    return _finish_person(row, office.group_detail(group_id), person)


@bot_access_bp.route("/api/bot/groups/<int:group_id>/members", methods=["POST"])
def api_group_members(group_id: int):
    row, person, err = _office_desk()
    if err:
        return err
    return _finish_person(row, office.set_member(person["user_id"], group_id, _payload()), person)


@bot_access_bp.route("/api/bot/worship/team", methods=["GET", "POST"])
def api_worship_team():
    row, person, err = _office_desk()
    if err:
        return err
    if request.method == "GET":
        return _finish_person(row, office.worship_team(), person)
    return _finish_person(row, office.set_worship_role(person["user_id"], _payload()), person)


@bot_access_bp.route("/api/bot/worship/songs", methods=["GET", "POST"])
def api_worship_songs():
    row, person, err = _office_desk()
    if err:
        return err
    if request.method == "GET":
        return _finish_person(row, office.list_songs(), person)
    return _finish_person(row, office.save_song(person["user_id"], _payload()), person)


@bot_access_bp.route("/api/bot/worship/defaults", methods=["GET", "POST"])
def api_worship_defaults():
    row, person, err = _office_desk()
    if err:
        return err
    if request.method == "GET":
        return _finish_person(row, office.list_defaults(), person)
    return _finish_person(row, office.save_defaults(person["user_id"], _payload()), person)


@bot_access_bp.route("/api/bot/donations", methods=["POST"])
def api_donations():
    row, person, err = _office_desk()
    if err:
        return err
    return _finish_person(row, office.record_donation(person["user_id"], _payload()), person)


@bot_access_bp.route("/api/bot/bills/<int:bill_id>", methods=["POST"])
def api_bill(bill_id: int):
    row, person, err = _office_desk()
    if err:
        return err
    return _finish_person(row, office.update_bill(person["user_id"], bill_id, _payload()), person)


@bot_access_bp.route("/api/bot/accounting", methods=["GET"])
def api_accounting():
    row, person, err = _office_desk()
    if err:
        return err
    return _finish_person(row, office.accounting_overview(), person)


@bot_access_bp.route("/api/bot/accounting/expenses", methods=["POST"])
def api_expense():
    row, person, err = _office_desk()
    if err:
        return err
    return _finish_person(row, office.record_expense(person["user_id"], _payload()), person)


@bot_access_bp.route("/api/bot/inventory", methods=["GET"])
def api_inventory():
    row, person, err = _office_desk()
    if err:
        return err
    return _finish_person(row, office.inventory_overview(), person)


@bot_access_bp.route("/api/bot/inventory/adjust", methods=["POST"])
def api_inventory_adjust():
    row, person, err = _office_desk()
    if err:
        return err
    return _finish_person(row, office.adjust_inventory(person["user_id"], _payload()), person)


@bot_access_bp.route("/api/bot/attendance", methods=["POST"])
def api_attendance():
    row, person, err = _office_desk()
    if err:
        return err
    return _finish_person(row, office.record_attendance(person["user_id"], _payload()), person)


def _upload_file():
    for name in ("file", "photo", "image", "hero_image", "media_file", "option_image", "chords_file"):
        upload = request.files.get(name)
        if upload and upload.filename:
            return upload
    return None


@bot_access_bp.route("/api/bot/upload", methods=["POST"])
def api_upload():
    from app.utils import bot_uploads as uploads
    place = (request.form.get("place") or "").strip().lower()
    upload = _upload_file()
    if place == "post":
        row, err = _require_key()
        if err:
            return err
        denied = _need(row, "posts")
        if denied:
            return denied
        facts = _facts(row)
        voice, voice_err = policy.resolve_bot_post(
            request.form.get("as") or "",
            row.get("voices") or [],
            role=facts.get("role"),
            admin_granted=bool(facts.get("admin_granted")),
        )
        if voice_err:
            return _json(False, error=voice_err, status=403)
        return _finish(
            row,
            uploads.save_upload(int(voice["user_id"]), place, upload, request.form, voice=voice),
        )
    row, person, err = _office_desk()
    if err:
        return err
    return _finish_person(
        row,
        uploads.save_upload(int(person["user_id"]), place, upload, request.form),
        person,
    )


@bot_access_bp.route("/api/bot/courses", methods=["GET", "POST"])
def api_courses():
    row, person, err = _office_desk()
    if err:
        return err
    if request.method == "GET":
        return _finish_person(row, areas.course_list(request.args), person)
    return _finish_person(row, areas.course_save(person["user_id"], _payload()), person)


@bot_access_bp.route("/api/bot/courses/<int:series_id>", methods=["GET"])
def api_course(series_id: int):
    row, person, err = _office_desk()
    if err:
        return err
    return _finish_person(row, areas.course_open(series_id), person)


@bot_access_bp.route("/api/bot/modules", methods=["GET", "POST"])
def api_modules():
    row, person, err = _office_desk()
    if err:
        return err
    if request.method == "GET":
        return _finish_person(row, areas.modules_view(), person)
    return _finish_person(row, areas.modules_save(_payload()), person)


@bot_access_bp.route("/api/bot/moderation", methods=["GET", "POST"])
def api_moderation():
    row, person, err = _office_desk()
    if err:
        return err
    if request.method == "GET":
        return _finish_person(row, areas.moderation_board(request.args), person)
    facts = _facts(row)
    return _finish_person(
        row,
        areas.moderation_act(person["user_id"], facts.get("role"), _payload()),
        person,
    )


@bot_access_bp.route("/api/bot/insights", methods=["GET", "POST"])
def api_insights():
    row, person, err = _office_desk()
    if err:
        return err
    if request.method == "GET":
        return _finish_person(row, areas.insights_view(), person)
    return _finish_person(row, areas.insights_run(person["user_id"], _payload()), person)


@bot_access_bp.route("/api/bot/desks", methods=["GET"])
def api_desks():
    row, person, err = _office_desk()
    if err:
        return err
    return _finish_person(row, desks.catalog(), person)


@bot_access_bp.route("/api/bot/desk/<area>", methods=["GET", "POST"])
def api_desk(area: str):
    row, person, err = _office_desk()
    if err:
        return err
    if request.method == "GET":
        return _finish_person(row, desks.read_desk(area, request.args, person["user_id"]), person)
    facts = _facts(row)
    return _finish_person(
        row,
        desks.write_desk(person["user_id"], facts.get("role"), area, _payload()),
        person,
    )


def _hard(row: dict) -> bool:
    return policy.switch_on(row.get("controls"), "hard_delete")


def _actor(row: dict) -> dict:
    facts = _facts(row)
    uid = facts.get("user_id")
    return {"user_id": uid, "name": _acting_name(row, facts) if uid else "Church"}


def _member_actor(row: dict) -> int:
    try:
        return int(_facts(row).get("user_id") or 0)
    except (TypeError, ValueError):
        return 0


def _comment_rate(row: dict):
    count = store.recent_action_count(int(row["id"]), "bot_comment_reply")
    if guard.over_comment_rate(count, policy.COMMENT_RATE_PER_HOUR):
        return _json(
            False,
            error="This bot already replied 30 times this hour.",
            status=429,
            code="rate_limit",
        )
    return None


@bot_access_bp.route("/api/bot/posts/<int:post_id>", methods=["GET", "POST"])
def api_post_one(post_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "posts")
    if denied:
        return denied
    if request.method == "GET":
        return _finish(row, content.get_post(post_id))
    return _finish(row, content.edit_post(post_id, _payload()))


@bot_access_bp.route("/api/bot/posts/<int:post_id>/hide", methods=["POST"])
def api_post_hide(post_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "posts")
    if denied:
        return denied
    return _finish(row, content.hide_post(post_id, True))


@bot_access_bp.route("/api/bot/posts/<int:post_id>/unhide", methods=["POST"])
def api_post_show(post_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "posts")
    if denied:
        return denied
    return _finish(row, content.hide_content(
        "community_posts", post_id, hide=False, action="bot_post_unhide",
    ))


@bot_access_bp.route("/api/bot/posts/<int:post_id>/delete", methods=["POST"])
def api_post_remove(post_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "posts")
    if denied:
        return denied
    return _finish(row, content.delete_content(
        "community_posts", post_id, _payload(), _hard(row),
    ))


@bot_access_bp.route("/api/bot/sermons/<int:sermon_id>/unhide", methods=["POST"])
def api_sermon_show(sermon_id: int):
    row, _person, err = _desk()
    if err:
        return err
    return _finish(row, content.hide_content(
        "pastoral_sermons", sermon_id, hide=False, action="bot_sermon_unhide",
    ))


@bot_access_bp.route("/api/bot/sermons/<int:sermon_id>/delete", methods=["POST"])
def api_sermon_remove(sermon_id: int):
    row, _person, err = _desk()
    if err:
        return err
    return _finish(row, content.delete_content(
        "pastoral_sermons", sermon_id, _payload(), _hard(row),
    ))


@bot_access_bp.route("/api/bot/sermons/<int:sermon_id>/sections/<int:section_id>/delete", methods=["POST"])
def api_section_remove(sermon_id: int, section_id: int):
    row, _person, err = _desk()
    if err:
        return err
    return _finish(row, content.delete_content(
        "sermon_sections", section_id, _payload(), _hard(row), sermon_id=sermon_id,
    ))


@bot_access_bp.route("/api/bot/illustrations/<int:illus_id>/unhide", methods=["POST"])
def api_illustration_show(illus_id: int):
    row, _person, err = _desk()
    if err:
        return err
    return _finish(row, content.hide_content(
        "illustration_library", illus_id, hide=False, action="bot_illustration_unhide",
    ))


@bot_access_bp.route("/api/bot/illustrations/<int:illus_id>/delete", methods=["POST"])
def api_illustration_remove(illus_id: int):
    row, _person, err = _desk()
    if err:
        return err
    return _finish(row, content.delete_content(
        "illustration_library", illus_id, _payload(), _hard(row),
    ))


@bot_access_bp.route("/api/bot/vault/<int:item_id>/delete", methods=["POST"])
def api_vault_remove(item_id: int):
    row, _person, err = _desk()
    if err:
        return err
    return _finish(row, content.delete_content(
        "pastoral_vault", item_id, _payload(), _hard(row),
    ))


@bot_access_bp.route("/api/bot/lineup/<int:plan_id>/delete", methods=["POST"])
def api_lineup_remove(plan_id: int):
    row, _person, err = _desk()
    if err:
        return err
    return _finish(row, content.clear_lineup(plan_id, _payload(), _hard(row)))


@bot_access_bp.route("/api/bot/comments/<area>/<int:parent_id>", methods=["POST"])
def api_comment_reply(area: str, parent_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "comments")
    if denied:
        return denied
    limited = _comment_rate(row)
    if limited:
        return limited
    body = _payload()
    text = body.get("body") or body.get("text") or ""
    return _finish(row, comments.reply_comment(area, parent_id, text, _actor(row)))


@bot_access_bp.route("/api/bot/comments/<area>/<int:parent_id>/<int:comment_id>", methods=["POST"])
def api_comment_edit(area: str, parent_id: int, comment_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "comments")
    if denied:
        return denied
    body = _payload()
    return _finish(row, comments.edit_comment(area, parent_id, comment_id, body.get("body") or body.get("text") or ""))


@bot_access_bp.route("/api/bot/comments/<area>/<int:parent_id>/<int:comment_id>/hide", methods=["POST"])
def api_comment_hide(area: str, parent_id: int, comment_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "comments")
    if denied:
        return denied
    return _finish(row, comments.hide_comment(area, parent_id, comment_id, {}, False))


@bot_access_bp.route("/api/bot/comments/<area>/<int:parent_id>/<int:comment_id>/delete", methods=["POST"])
def api_comment_remove(area: str, parent_id: int, comment_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "comments")
    if denied:
        return denied
    return _finish(row, comments.hide_comment(area, parent_id, comment_id, _payload(), _hard(row)))


@bot_access_bp.route("/api/bot/content/<kind>/<int:item_id>/moderate", methods=["POST"])
def api_content_moderate(kind: str, item_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need_any(row, "moderation", "office")
    if denied:
        return denied
    return _finish(row, content.moderate(kind, item_id, _payload()))


@bot_access_bp.route("/api/bot/members", methods=["GET", "POST"])
def api_members():
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "members")
    if denied:
        return denied
    if request.method == "GET":
        return _finish(row, members_api.list_members(request.args.get("q") or "", request.args.get("page")))
    return _finish(row, members_api.create_member(_member_actor(row), _payload()))


@bot_access_bp.route("/api/bot/members/visitors", methods=["GET"])
def api_member_visitors():
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "members")
    if denied:
        return denied
    return _finish(row, members_api.list_visitors())


@bot_access_bp.route("/api/bot/members/export", methods=["GET"])
def api_member_export():
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "members_export")
    if denied:
        return denied
    return _finish(row, members_api.export_members(request.args.get("format") or "json"))


@bot_access_bp.route("/api/bot/members/registrations/<int:user_id>/approve", methods=["POST"])
def api_member_approve(user_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "members")
    if denied:
        return denied
    return _finish(row, members_api.decide_registration(_member_actor(row), user_id, True))


@bot_access_bp.route("/api/bot/members/registrations/<int:user_id>/reject", methods=["POST"])
def api_member_reject(user_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "members")
    if denied:
        return denied
    return _finish(row, members_api.decide_registration(_member_actor(row), user_id, False))


@bot_access_bp.route("/api/bot/members/access/templates", methods=["GET", "POST"])
def api_access_templates():
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "members_access")
    if denied:
        return denied
    if request.method == "GET":
        return _finish(row, members_api.templates(_member_actor(row), None, None, False))
    return _finish(row, members_api.templates(_member_actor(row), None, _payload(), True))


@bot_access_bp.route("/api/bot/members/access/templates/<int:template_id>", methods=["POST"])
def api_access_template(template_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "members_access")
    if denied:
        return denied
    return _finish(row, members_api.templates(_member_actor(row), template_id, _payload(), True))


@bot_access_bp.route("/api/bot/members/<int:member_id>", methods=["GET", "POST"])
def api_member(member_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "members")
    if denied:
        return denied
    if request.method == "GET":
        return _finish(row, members_api.member_detail(member_id))
    return _finish(row, members_api.update_member(_member_actor(row), member_id, _payload()))


@bot_access_bp.route("/api/bot/members/<int:member_id>/delete", methods=["POST"])
def api_member_remove(member_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "members")
    if denied:
        return denied
    return _finish(row, members_api.delete_member(_member_actor(row), member_id, _payload(), _hard(row)))


@bot_access_bp.route("/api/bot/members/<int:member_id>/access", methods=["GET", "POST"])
def api_member_access(member_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "members_access")
    if denied:
        return denied
    writing = request.method != "GET"
    return _finish(row, members_api.member_access(
        _member_actor(row), member_id, _payload() if writing else None, writing,
    ))


@bot_access_bp.route("/api/bot/events", methods=["GET", "POST"])
def api_events():
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "events")
    if denied:
        return denied
    if request.method == "GET":
        return _finish(row, events_api.list_events(
            request.args.get("from") or "",
            request.args.get("to") or "",
            request.args.get("campus_id"),
        ))
    return _finish(row, events_api.create_event(_member_actor(row), _payload()))


@bot_access_bp.route("/api/bot/events/<int:event_id>", methods=["GET", "POST"])
def api_event(event_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "events")
    if denied:
        return denied
    if request.method == "GET":
        return _finish(row, events_api.event_detail(event_id))
    return _finish(row, events_api.update_event(_member_actor(row), event_id, _payload()))


@bot_access_bp.route("/api/bot/events/<int:event_id>/delete", methods=["POST"])
def api_event_remove(event_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "events")
    if denied:
        return denied
    return _finish(row, events_api.delete_event(_member_actor(row), event_id, _payload(), _hard(row)))


@bot_access_bp.route("/api/bot/events/<int:event_id>/signups", methods=["GET", "POST"])
def api_event_signups(event_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "events")
    if denied:
        return denied
    writing = request.method != "GET"
    return _finish(row, events_api.signups(event_id, _payload() if writing else None, writing))


@bot_access_bp.route("/api/bot/events/<int:event_id>/signups/<int:signup_id>/delete", methods=["POST"])
def api_event_signup_remove(event_id: int, signup_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "events")
    if denied:
        return denied
    return _finish(row, events_api.signups(event_id, _payload(), True, signup_id))


@bot_access_bp.route("/api/bot/events/<int:event_id>/comments/<int:comment_id>", methods=["POST"])
def api_event_comment(event_id: int, comment_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "comments")
    if denied:
        return denied
    body = _payload()
    if body.get("hide") in (True, 1, "1", "true", "True"):
        return _finish(row, comments.hide_comment("event", event_id, comment_id, body, _hard(row)))
    return _finish(row, comments.edit_comment(
        "event", event_id, comment_id, body.get("body") or body.get("text") or "",
    ))


@bot_access_bp.route("/api/bot/events/<int:event_id>/email", methods=["POST"])
def api_event_email(event_id: int):
    row, err = _require_key()
    if err:
        return err
    denied = _need(row, "comms_send")
    if denied:
        return denied
    return _finish(row, events_api.email_event(
        _member_actor(row),
        event_id,
        _payload(),
        policy.switch_on(row.get("controls"), "comms_send"),
    ))
